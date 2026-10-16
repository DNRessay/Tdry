"""AP Novo campaigns on Modal. S3 is the source of truth: output is synced up while the job runs,
restored on retry/resume, and status/results are read from S3 by the API (Lambda), never from Modal."""
import csv
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import modal

GPU = os.environ.get("NOVO_GPU", "A100-80GB")
SYNC_EVERY = 60
STALE_AFTER = 300

app = modal.App("tdry-novo")
weights = modal.Volume.from_name("novo-weights", create_if_missing=True)
secret = modal.Secret.from_name("novo-aws")  # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, NOVO_BUCKET, NOVO_TOKEN

image = (
    modal.Image.from_registry("nvidia/cuda:12.6.3-cudnn-devel-ubuntu24.04", add_python="3.12")
    .apt_install("git", "wget", "zstd", "build-essential", "cmake", "curl")
    .pip_install("uv", "fastapi[standard]", "boto3")
    .env({"UV_SYSTEM_PYTHON": "1"})
    .run_commands(
        "git clone --depth 1 https://github.com/google-deepmind/alphaprotein-novo.git /opt/novo",
        "cd /opt/novo && uv pip install -e . && build_data",
        "git clone --depth 1 https://github.com/dauparas/LigandMPNN.git /opt/LigandMPNN",
        "cd /opt/LigandMPNN && bash get_model_params.sh ./model_params",
        "uv venv --python 3.11 /opt/lmpnn",
        "cd /opt/LigandMPNN && uv pip install --python /opt/lmpnn/bin/python -r requirements.txt 'setuptools<82'",
    )
)


def s3():
    import boto3
    return boto3.client("s3")


def bucket():
    return os.environ["NOVO_BUCKET"]


def read_json(key):
    try:
        return json.loads(s3().get_object(Bucket=bucket(), Key=key)["Body"].read())
    except s3().exceptions.NoSuchKey:
        return None


def write_json(key, obj):
    s3().put_object(Bucket=bucket(), Key=key, Body=json.dumps(obj).encode(), ContentType="application/json")


def restore(prefix, local: Path):
    """Pull everything saved for this job (input + earlier output) so the pipeline resumes."""
    n = 0
    for page in s3().get_paginator("list_objects_v2").paginate(Bucket=bucket(), Prefix=prefix):
        for o in page.get("Contents", []):
            rel = o["Key"][len(prefix):]
            if not rel or rel in ("job.json", "results.json"):
                continue
            dest = local / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            s3().download_file(bucket(), o["Key"], str(dest))
            n += 1
    return n


def sync_up(prefix, local: Path, seen: dict):
    """Upload new/changed files under out/ and logs. Skips files touched in the last 5s (still being written)."""
    now = time.time()
    for p in (local / "out").rglob("*"):
        if not p.is_file() or p.suffix == ".tmp":
            continue
        st = p.stat()
        sig = (st.st_size, int(st.st_mtime))
        if now - st.st_mtime < 5 or seen.get(p) == sig:
            continue
        s3().upload_file(str(p), bucket(), prefix + str(p.relative_to(local)))
        seen[p] = sig


def progress(out: Path):
    def n(sub, pat):
        d = out / sub
        return len([f for f in d.glob(pat) if "_motif" not in f.name]) if d.exists() else 0

    c = {
        "generated": n("01_generation", "*.cif"),
        "resequenced": n("02_resequence", "*_reseq.cif"),
        "folded": n("03_folded", "*_folded_*.cif"),
        "evaluated": n("04_eval", "*_evaluation.json"),
    }
    stage = next((s for s, k in [("evaluation", "evaluated"), ("folding", "folded"), ("resequence", "resequenced"), ("generation", "generated")] if c[k]), "starting")
    return stage, c


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def fasta_seq(path: Path):
    if not path.exists():
        return ""
    recs, cur = [], []
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            if cur:
                recs.append("".join(cur))
            cur = []
        else:
            cur.append(line.strip())
    if cur:
        recs.append("".join(cur))
    return recs[-1].split(":")[0] if recs else ""


def rank(out: Path, top=50):
    """Generic ranking: higher pLDDT, lower motif RMSD. This is a coarse sort, not the suite's own filter."""
    csv_path = out / "04_eval" / "evaluation_summary.csv"
    if not csv_path.exists():
        return []
    rows = []
    for r in csv.DictReader(csv_path.open()):
        m = {k: num(v) for k, v in r.items() if k not in ("sample_name", "spec_name") and v != ""}
        pl = [v for k, v in m.items() if "plddt" in k and isinstance(v, float)]
        pl_c = [v for k, v in m.items() if "plddt" in k and "complex" in k and isinstance(v, float)]
        rm = [v for k, v in m.items() if "motif" in k and "rmsd" in k and isinstance(v, float)]
        plddt = (sum(pl_c) / len(pl_c)) if pl_c else (sum(pl) / len(pl)) if pl else 0.0
        score = plddt - (10 * sum(rm) / len(rm) if rm else 0.0)
        name = r["sample_name"]
        files = []
        for label, rel in [("Resequenced scaffold", f"02_resequence/{name}_reseq.cif"), ("Generated backbone", f"01_generation/{name}.cif")]:
            if (out / rel).exists():
                files.append({"label": label, "key": f"out/{rel}"})
        for p in sorted((out / "03_folded").glob(f"{name}_*_folded_seed*.cif"))[:6]:
            files.append({"label": p.stem.replace(f"{name}_", ""), "key": f"out/03_folded/{p.name}"})
        seq = fasta_seq(out / "02_resequence" / f"{name}.fa") or fasta_seq(out / "01_generation" / f"{name}.fa")
        rows.append({"name": name, "score": round(score, 3), "sequence": seq, "metrics": m, "files": files})
    rows.sort(key=lambda d: d["score"], reverse=True)
    return rows[:top]


def set_status(prefix, base, **kw):
    base.update(kw, updated=time.time())
    write_json(prefix + "job.json", base)


@app.function(
    image=image, gpu=GPU, cpu=8, memory=65536, timeout=24 * 3600, secrets=[secret], volumes={"/weights": weights},
    retries=modal.Retries(max_retries=3, initial_delay=30.0, backoff_coefficient=1.0),
)
def run_campaign(job_id: str):
    prefix = f"novo/{job_id}/"
    local = Path("/tmp/job") / job_id
    local.mkdir(parents=True, exist_ok=True)
    job = read_json(prefix + "job.json") or {}
    job["attempt"] = job.get("attempt", 0) + 1
    restored = restore(prefix, local)
    out = local / "out"
    out.mkdir(exist_ok=True)
    set_status(prefix, job, status="running", stage="starting", error=None, restored_files=restored)

    seen: dict = {}
    stop = threading.Event()

    def beat():
        while not stop.wait(SYNC_EVERY):
            try:
                sync_up(prefix, local, seen)
                stage, counts = progress(out)
                set_status(prefix, job, status="running", stage=stage, counts=counts)
            except Exception as e:  # never let the heartbeat kill the job
                print("sync error:", e)

    t = threading.Thread(target=beat, daemon=True)
    t.start()
    log = (out / "pipeline.log").open("a")
    try:
        rc = subprocess.run(
            [
                "python", "/opt/novo/run_pipeline.py",
                f"--manifest={local / 'input' / 'manifest.json'}", f"--output_dir={out}",
                "--apn_model_dir=/weights/apnovo_generator", "--af3_model_dir=/weights/af3_la",
                "--ligandmpnn_dir=/opt/LigandMPNN", "--ligandmpnn_python=/opt/lmpnn/bin/python",
            ],
            stdout=log, stderr=subprocess.STDOUT, cwd="/opt/novo",
        ).returncode
        stop.set()
        t.join()
        log.flush()
        sync_up(prefix, local, seen)
        stage, counts = progress(out)
        if rc != 0:
            tail = ""
            for f in sorted((out / "logs").glob("*.log")) + [out / "pipeline.log"]:
                if f.exists():
                    tail = f.read_text()[-1500:]
            raise RuntimeError(f"pipeline exited {rc}: {tail}")
        designs = rank(out)
        write_json(prefix + "results.json", {"designs": designs, "finished": time.time()})
        set_status(prefix, job, status="done", stage="done", counts=counts, error=None)
    except Exception as e:
        stop.set()
        try:
            sync_up(prefix, local, seen)
            stage, counts = progress(out)
            set_status(prefix, job, status="error", stage=stage, counts=counts, error=str(e)[-1800:])
        finally:
            raise  # Modal retries; progress is already in S3 and the next attempt resumes from it


@app.function(image=image, secrets=[secret], min_containers=0)
@modal.asgi_app(label="tdry-novo-api")
def api():
    from fastapi import FastAPI, Header, HTTPException
    from pydantic import BaseModel, Field

    web = FastAPI(title="T-Dry-Lab Novo")

    class Req(BaseModel):
        job_id: str = Field(pattern=r"^[0-9a-f]{32}$")

    def auth(h):
        if not os.environ.get("NOVO_TOKEN") or h != f"Bearer {os.environ['NOVO_TOKEN']}":
            raise HTTPException(401, "bad token")

    def launch(job_id):
        job = read_json(f"novo/{job_id}/job.json")
        if not job:
            raise HTTPException(404, "unknown job")
        if job.get("status") == "done":
            return {"status": "done"}
        if job.get("status") == "running" and time.time() - job.get("updated", 0) < STALE_AFTER:
            return {"status": "already_running"}
        run_campaign.spawn(job_id)
        return {"status": "spawned"}

    @web.get("/health")
    def health():
        return {"ok": True}

    @web.post("/submit")
    def submit(r: Req, authorization: str = Header("")):
        auth(authorization)
        return launch(r.job_id)

    @web.post("/resume")
    def resume(r: Req, authorization: str = Header("")):
        auth(authorization)
        return launch(r.job_id)

    return web


@app.local_entrypoint()
def download_weights(accept_terms: bool = False):
    """modal run services/novo/modal_app.py --accept-terms"""
    if not accept_terms:
        raise SystemExit(
            "Read the AP Novo and AlphaFold 3 weights terms (non-commercial use only), then re-run with --accept-terms.\n"
            "https://github.com/google-deepmind/alphaprotein-novo/blob/main/WEIGHTS_TERMS_OF_USE.md\n"
            "https://github.com/google-deepmind/alphafold3/blob/main/WEIGHTS_TERMS_OF_USE.md"
        )
    fetch_weights.remote()


@app.function(image=image, volumes={"/weights": weights}, timeout=3600)
def fetch_weights():
    for d, url in [
        ("apnovo_generator", "https://storage.googleapis.com/alphaprotein_novo/generator.bin.zst"),
        ("af3_la", "https://storage.googleapis.com/alphafold3/af3_leaving_atom.bin.zst"),
    ]:
        Path(f"/weights/{d}").mkdir(parents=True, exist_ok=True)
        subprocess.run(["wget", "-nc", "-P", f"/weights/{d}", url], check=True)
    weights.commit()
