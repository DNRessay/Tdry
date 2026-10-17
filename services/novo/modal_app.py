"""AP Novo campaigns on Modal. S3 is the source of truth: output is synced up while the job runs,
restored on retry/resume, and status/results are read from S3 by the API (Lambda), never from Modal."""
import csv
import json
import os
import shutil
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

BASE = "nvidia/cuda:12.6.3-cudnn-devel-ubuntu24.04"

# Demo engine: AP Novo + AlphaFold 3 (non-commercial weights).
image = (
    modal.Image.from_registry(BASE, add_python="3.12")
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

# Commercial engine: RFdiffusion2 (BSD-3) -> LigandMPNN (MIT) -> Boltz (MIT). No AP Novo or AlphaFold code here.
# PyRosetta is deliberately NOT installed (commercial licence needed); if RFdiffusion2 asks for it, the run fails loudly.
open_image = (
    modal.Image.micromamba(python_version="3.12")
    .apt_install("git", "wget", "build-essential")
    .pip_install("fastapi[standard]", "boto3", "numpy", "openmm[cuda12]", "pdbfixer")
    .run_commands(
        "git clone --depth 1 https://github.com/RosettaCommons/RFdiffusion2.git /opt/RFdiffusion2",
        "cd /opt/RFdiffusion2/envs && sed -i '/pyrosetta/d;/conda.rosettacommons.org/d' cuda124_env.yml && micromamba create -y -n rfd2 -f cuda124_env.yml",
        "git clone --depth 1 https://github.com/dauparas/LigandMPNN.git /opt/LigandMPNN",
        "cd /opt/LigandMPNN && bash get_model_params.sh ./model_params",
        "micromamba create -y -n lmpnn python=3.11 pip && /opt/conda/envs/lmpnn/bin/pip install -r /opt/LigandMPNN/requirements.txt 'setuptools<82'",
        "micromamba create -y -n boltz python=3.11 pip && /opt/conda/envs/boltz/bin/pip install boltz",
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


def sync_up(prefix, local: Path, seen: dict, final=False):
    """Upload new/changed files under out/. While running, skips files touched in the last 5s (still being written);
    final=True (pipeline finished or crashed, nothing is writing) uploads everything."""
    now = time.time()
    for p in (local / "out").rglob("*"):
        if not p.is_file() or p.suffix == ".tmp" or any(x.startswith("tmp_") for x in p.parts):
            continue
        st = p.stat()
        sig = (st.st_size, int(st.st_mtime))
        if (not final and now - st.st_mtime < 5) or seen.get(p) == sig:
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


def fasta_records(path: Path):
    if not path.exists():
        return []
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
    return [r.split(":")[0] for r in recs]


def fasta_seq(path: Path):
    r = fasta_records(path)
    return r[-1] if r else ""


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


def tail_of(log_path: Path, n=1200):
    try:
        return log_path.read_text()[-n:]
    except Exception:
        return ""


def sh(cmd, log, log_path, cwd=None, env=None):
    r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=cwd, env=env)
    log.flush()
    if r.returncode:
        raise RuntimeError(f"{Path(str(cmd[1])).name} exited {r.returncode}: {tail_of(log_path)}")


# ----------------------------------------------------------------------------- demo engine (AP Novo)
def run_novo_pipeline(local: Path, out: Path, log, log_path: Path):
    sh(
        [
            "python", "/opt/novo/run_pipeline.py",
            f"--manifest={local / 'input' / 'manifest.json'}", f"--output_dir={out}",
            "--apn_model_dir=/weights/apnovo_generator", "--af3_model_dir=/weights/af3_la",
            "--ligandmpnn_dir=/opt/LigandMPNN", "--ligandmpnn_python=/opt/lmpnn/bin/python",
        ],
        log, log_path, cwd="/opt/novo",
    )


# ----------------------------------------------------------------------------- commercial engine
OPEN_PY = "/opt/conda/envs"
BATCH = 5
RELAX_ITERS = int(os.environ.get("RELAX_ITERS", "1000"))


def progress_open(out: Path):
    c = {
        "generated": len(list((out / "01_design").glob("b*/d_*.pdb"))),
        "resequenced": len(list((out / "02_sequence").glob("*.fa"))),
        "folded": len(list((out / "03_fold").glob("res/boltz_results_*/predictions/*/confidence_*_model_0.json"))),
        "evaluated": 0,
    }
    stage = next((s for s, k in [("folding", "folded"), ("sequence design", "resequenced"), ("backbone design", "generated")] if c[k]), "starting")
    return stage, c


def fixed_residues(trb: Path):
    """Motif residues RFdiffusion2 placed, so LigandMPNN keeps their identity. Empty string if the .trb can't be read."""
    try:
        import pickle
        idx = pickle.load(trb.open("rb")).get("con_hal_pdb_idx") or []
        return " ".join(f"{c}{i}" for c, i in idx)
    except Exception as e:
        print("no fixed residues for", trb.name, e)
        return ""


def run_open_pipeline(local: Path, out: Path, log, log_path: Path):
    cfg = json.loads((local / "input" / "open.json").read_text())
    ligands = cfg.get("ligands") or []
    n, per = cfg["num_designs"], cfg["seqs_per_design"]
    d1, d2, d3 = out / "01_design", out / "02_sequence", out / "03_fold"
    for d in (d1, d2, d3):
        d.mkdir(exist_ok=True)

    # 1. backbones, in batches so a crash loses at most one batch (done batches are skipped after restore)
    env = {**os.environ, "PYTHONPATH": "/opt/RFdiffusion2"}
    for b in range(0, n, BATCH):
        bd = d1 / f"b{b:04d}"
        if (bd / ".done").exists():
            continue
        bd.mkdir(exist_ok=True)
        args = [
            f"{OPEN_PY}/rfd2/bin/python", "/opt/RFdiffusion2/rf_diffusion/run_inference.py", "--config-name=aa",
            "inference.ckpt_path=/weights/rfd2/model_weights/RFD_173.pt",
            f"inference.input_pdb={local / 'input' / 'motif.pdb'}",
            f"inference.num_designs={min(BATCH, n - b)}", f"inference.output_prefix={bd}/d", f"inference.seed_offset={b}",
            f"inference.contig_as_guidepost={bool(cfg.get('unindexed'))}",
            f"contigmap.contigs=['{cfg['contigs']}']", f"hydra.run.dir={bd}/hydra",
        ]
        if ligands:
            args.append(f"inference.ligand='{','.join(ligands)}'")
        if cfg.get("contig_atoms"):  # hydra wants the dict as a quoted string with escaped inner quotes
            inner = ",".join(f"\\'{k}\\':\\'{v}\\'" for k, v in cfg["contig_atoms"].items())
            args.append("contigmap.contig_atoms='{" + inner + "}'")
        sh(args, log, log_path, cwd="/opt/RFdiffusion2", env=env)
        (bd / ".done").write_text("1")
    backbones = sorted(d1.glob("b*/d_*.pdb"))
    if not backbones:
        raise RuntimeError("RFdiffusion2 produced no backbones (expected d_*.pdb); check pipeline.log")

    # 2. sequences with LigandMPNN
    for p in backbones:
        name = f"{p.parent.name}_{p.stem}"
        if (d2 / f"{name}.fa").exists():
            continue
        tmp = d2 / f"tmp_{name}"
        shutil.rmtree(tmp, ignore_errors=True)  # stale from a crashed attempt
        cmd = [
            f"{OPEN_PY}/lmpnn/bin/python", "/opt/LigandMPNN/run.py", "--model_type", "ligand_mpnn",
            "--checkpoint_ligand_mpnn", "/opt/LigandMPNN/model_params/ligandmpnn_v_32_010_25.pt",
            "--pdb_path", str(p), "--out_folder", str(tmp), "--number_of_batches", str(per),
            "--batch_size", "1", "--temperature", "0.1", "--seed", "111",
        ]
        fixed = fixed_residues(p.with_suffix(".trb"))
        if fixed:
            cmd += ["--fixed_residues", fixed]
        sh(cmd, log, log_path, cwd="/opt/LigandMPNN")
        (tmp / "seqs" / f"{p.stem}.fa").replace(d2 / f"{name}.fa")
        shutil.rmtree(tmp, ignore_errors=True)

    # 3. fold protein + ligand with Boltz (single-sequence; existing predictions are skipped on resume)
    yd = d3 / "in"
    yd.mkdir(exist_ok=True)
    for fa in sorted(d2.glob("*.fa")):
        for i, seq in enumerate(fasta_records(fa)[1:]):
            y = yd / f"{fa.stem}_s{i}.yaml"
            if y.exists():
                continue
            lines = ["sequences:", "  - protein:", "      id: A", f"      sequence: {seq}", "      msa: empty"]
            for j, ccd in enumerate(ligands):
                lines += ["  - ligand:", f"      id: {chr(ord('B') + j)}", f"      ccd: {ccd}"]
            y.write_text("\n".join(lines) + "\n")
    sh(
        [f"{OPEN_PY}/boltz/bin/boltz", "predict", str(yd), "--out_dir", str(d3 / "res"), "--cache", "/weights/boltz",
         "--accelerator", "gpu", "--devices", "1", "--diffusion_samples", "1", "--output_format", "pdb"],
        log, log_path,
    )

    # 4. relax + clash check with OpenMM (Rosetta-free); one json per design so a restore skips finished ones
    d4 = out / "04_relax"
    d4.mkdir(exist_ok=True)
    for conf in sorted((d3 / "res").glob("boltz_results_*/predictions/*/confidence_*_model_0.json")):
        nm = conf.parent.name
        if (d4 / f"{nm}.json").exists():
            continue
        try:
            metrics = relax_one(conf.parent / f"{nm}_model_0.pdb", d4 / f"{nm}_relaxed.pdb")
        except Exception as e:  # a failed relax must not sink the campaign; the design just lacks these metrics
            metrics = {"relax_error": str(e)[:200]}
        (d4 / f"{nm}.json").write_text(json.dumps(metrics))


def relax_one(src: Path, dst: Path):
    """Rosetta-free check on a folded complex: ligand clash/contact metrics, then an OpenMM minimisation of the protein
    (AMBER14 + implicit solvent, weak restraints). dE is energy released by relaxing, a strain/clash proxy; the scale is
    only comparable between designs of similar length, so it is reported but not used in the score."""
    import numpy as np
    from openmm import CustomExternalForce, LangevinMiddleIntegrator, Platform, unit
    from openmm import app
    from pdbfixer import PDBFixer

    prot, lig = [], []
    for line in src.read_text().splitlines():
        elem = line[76:78].strip() if len(line) > 77 else line[12:16].strip()[:1]
        if line.startswith("ATOM") and line[21] == "A":
            prot.append(line)
        elif line.startswith("HETATM") and line[17:20].strip() != "HOH" and elem != "H":
            lig.append(line)
    xyz = lambda L: np.array([[float(l[30:38]), float(l[38:46]), float(l[46:54])] for l in L])
    m = {}
    heavy = [l for l in prot if (l[76:78].strip() or l[12:16].strip()[:1]) != "H"]
    if lig and heavy:
        d = np.linalg.norm(xyz(heavy)[:, None, :] - xyz(lig)[None, :, :], axis=2)
        res = [l[22:27] for l in heavy]
        m["ligand_min_dist"] = round(float(d.min()), 2)
        m["ligand_clashes"] = int((d < 2.2).sum())
        m["ligand_contacts"] = len({res[i] for i in np.where((d < 4.5).any(axis=1))[0]})

    tmp = dst.with_suffix(".prot.pdb")
    tmp.write_text("\n".join(prot) + "\nEND\n")
    fx = PDBFixer(filename=str(tmp))
    fx.findMissingResidues()
    fx.missingResidues = {}
    fx.findMissingAtoms()
    fx.addMissingAtoms()
    fx.addMissingHydrogens(7.0)
    ff = app.ForceField("amber14-all.xml", "implicit/obc2.xml")
    system = ff.createSystem(fx.topology, nonbondedMethod=app.NoCutoff, constraints=app.HBonds)
    rest = CustomExternalForce("0.5*k*((x-x0)^2+(y-y0)^2+(z-z0)^2)")
    rest.addGlobalParameter("k", 400.0)  # kJ/mol/nm^2, weak: lets clashes relax without unfolding
    for p in ("x0", "y0", "z0"):
        rest.addPerParticleParameter(p)
    for a in fx.topology.atoms():
        if a.element.symbol != "H":
            rest.addParticle(a.index, fx.positions[a.index].value_in_unit(unit.nanometer))
    rest.setForceGroup(1)
    system.addForce(rest)
    try:
        platform = Platform.getPlatformByName("CUDA")
    except Exception:
        platform = Platform.getPlatformByName("CPU")
    sim = app.Simulation(fx.topology, system, LangevinMiddleIntegrator(300 * unit.kelvin, 1 / unit.picosecond, 0.002 * unit.picoseconds), platform)
    sim.context.setPositions(fx.positions)
    e = lambda: sim.context.getState(getEnergy=True, groups={0}).getPotentialEnergy().value_in_unit(unit.kilocalories_per_mole)
    e0, p0 = e(), sim.context.getState(getPositions=True).getPositions(asNumpy=True).value_in_unit(unit.angstrom)
    sim.minimizeEnergy(maxIterations=RELAX_ITERS)
    e1, st = e(), sim.context.getState(getPositions=True)
    p1 = st.getPositions(asNumpy=True).value_in_unit(unit.angstrom)
    ca = [a.index for a in fx.topology.atoms() if a.name == "CA"]
    n = len(ca)
    A, B = p0[ca] - p0[ca].mean(0), p1[ca] - p1[ca].mean(0)
    U, _, Vt = np.linalg.svd(A.T @ B)
    R = U @ np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))]) @ Vt
    with dst.open("w") as f:
        app.PDBFile.writeFile(sim.topology, st.getPositions(), f)
    tmp.unlink(missing_ok=True)
    m.update(relax_dE_per_res=round((e0 - e1) / max(n, 1), 2), relax_ca_rmsd=round(float(np.sqrt(((A @ R - B) ** 2).sum(1).mean())), 2), relax_platform=platform.getName())
    return m


def ca_rmsd(a: Path, b: Path):
    """CA RMSD after Kabsch superposition; None if the chains differ in length or can't be read."""
    import numpy as np

    def cas(p):
        xs = []
        for line in p.read_text().splitlines():
            if line.startswith("ATOM") and line[12:16].strip() == "CA" and line[21] in ("A", " "):
                xs.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        return np.array(xs)

    try:
        P, Q = cas(a), cas(b)
        if len(P) == 0 or len(P) != len(Q):
            return None
        P, Q = P - P.mean(0), Q - Q.mean(0)
        U, _, Vt = np.linalg.svd(P.T @ Q)
        d = np.sign(np.linalg.det(U @ Vt))
        R = U @ np.diag([1, 1, d]) @ Vt
        return float(np.sqrt(((P @ R - Q) ** 2).sum(1).mean()))
    except Exception:
        return None


def rank_open(out: Path, top=50):
    """Coarse sort: pLDDT + 20*ligand ipTM - 5*CA RMSD to the backbone - 3 per ligand clash (max 10). Not real filtering."""
    rows = []
    for conf in (out / "03_fold").glob("res/boltz_results_*/predictions/*/confidence_*_model_0.json"):
        nm = conf.parent.name  # e.g. b0000_d_0_s1
        c = json.loads(conf.read_text())
        bb_name, _, si = nm.rpartition("_s")
        batch, _, stem = bb_name.partition("_d_")
        backbone = out / "01_design" / batch / f"d_{stem}.pdb"
        folded = conf.parent / f"{nm}_model_0.pdb"
        rmsd = ca_rmsd(backbone, folded) if backbone.exists() and folded.exists() else None
        plddt = float(c.get("complex_plddt", 0)) * 100
        lig = float(c.get("ligand_iptm", 0) or 0)
        rx_path = out / "04_relax" / f"{nm}.json"
        rx = json.loads(rx_path.read_text()) if rx_path.exists() else {}
        score = plddt + 20 * lig - (5 * rmsd if rmsd is not None else 0) - 3 * min(rx.get("ligand_clashes", 0), 10)
        m = {"plddt": round(plddt, 1), "ligand_iptm": round(lig, 3), "iptm": round(float(c.get("iptm", 0) or 0), 3)}
        if rmsd is not None:
            m["ca_rmsd_to_backbone"] = round(rmsd, 2)
        m.update({k: v for k, v in rx.items() if k != "relax_platform"})
        seq = fasta_records(out / "02_sequence" / f"{bb_name}.fa")
        files = [{"label": "Folded complex", "key": f"out/{folded.relative_to(out)}"}] if folded.exists() else []
        relaxed = out / "04_relax" / f"{nm}_relaxed.pdb"
        if relaxed.exists():
            files.append({"label": "Relaxed protein (OpenMM)", "key": f"out/{relaxed.relative_to(out)}"})
        if backbone.exists():
            files.append({"label": "RFdiffusion2 backbone", "key": f"out/{backbone.relative_to(out)}"})
        rows.append({"name": nm, "score": round(score, 2), "sequence": seq[int(si) + 1] if len(seq) > int(si) + 1 else "", "metrics": m, "files": files})
    rows.sort(key=lambda d: d["score"], reverse=True)
    return rows[:top]


# ----------------------------------------------------------------------------- shared harness
ENGINES = {
    "novo": (run_novo_pipeline, progress, rank),
    "open": (run_open_pipeline, progress_open, rank_open),
}


def campaign(job_id: str, engine: str):
    pipeline, prog, rank_fn = ENGINES[engine]
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
                stage, counts = prog(out)
                set_status(prefix, job, status="running", stage=stage, counts=counts)
            except Exception as e:  # never let the heartbeat kill the job
                print("sync error:", e)

    t = threading.Thread(target=beat, daemon=True)
    t.start()
    log_path = out / "pipeline.log"
    log = log_path.open("a")
    try:
        pipeline(local, out, log, log_path)
        stop.set()
        t.join()
        log.flush()
        designs = rank_fn(out)
        write_json(prefix + "results.json", {"designs": designs, "finished": time.time(), "engine": engine})
        sync_up(prefix, local, seen, final=True)
        stage, counts = prog(out)
        counts["evaluated"] = len(designs)
        set_status(prefix, job, status="done", stage="done", counts=counts, error=None)
    except Exception as e:
        stop.set()
        try:
            sync_up(prefix, local, seen, final=True)
            stage, counts = prog(out)
            set_status(prefix, job, status="error", stage=stage, counts=counts, error=str(e)[-1800:])
        finally:
            raise  # Modal retries; progress is already in S3 and the next attempt resumes from it


RETRY = dict(timeout=24 * 3600, secrets=[secret], volumes={"/weights": weights}, cpu=8, memory=65536,
             retries=modal.Retries(max_retries=3, initial_delay=30.0, backoff_coefficient=1.0))


@app.function(image=image, gpu=GPU, **RETRY)
def run_novo(job_id: str):
    campaign(job_id, "novo")


@app.function(image=open_image, gpu=GPU, **RETRY)
def run_open(job_id: str):
    campaign(job_id, "open")


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
        (run_open if job.get("engine") == "open" else run_novo).spawn(job_id)
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
    """DEMO engine weights: modal run services/novo/modal_app.py::download_weights --accept-terms"""
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


@app.local_entrypoint()
def download_open_weights():
    """COMMERCIAL engine weights: modal run services/novo/modal_app.py::download_open_weights
    (RFdiffusion2 checkpoint from IPD; Boltz downloads its own on first run into the same volume)."""
    fetch_open_weights.remote()


@app.function(image=open_image, volumes={"/weights": weights}, timeout=3600)
def fetch_open_weights():
    Path("/weights/rfd2/model_weights").mkdir(parents=True, exist_ok=True)
    subprocess.run(["wget", "-nc", "-P", "/weights/rfd2/model_weights", "https://files.ipd.uw.edu/pub/rfdiffusion2/model_weights/RFD_173.pt"], check=True)
    weights.commit()
