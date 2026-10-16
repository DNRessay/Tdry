import hmac
import json
import os
import re
import time
import uuid

import boto3
import requests
from common import api, ApiError

BUCKET = os.environ.get("NOVO_BUCKET", "")
STALE_AFTER = 300
SUITES = {"kemp_eliminase", "serine_esterase", "dehp_esterase", "carbene_transfer", "nitrene_transfer"}
NOTICE = (
    "Designs come from AlphaProtein Novo and are subject to the AP Novo Generator Output Terms of Use. "
    "For theoretical modeling only; ranking here is a coarse sort of pLDDT and motif RMSD."
)
s3 = boto3.client("s3")


def _get(key):
    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None


def _put(key, body, ctype="application/json"):
    s3.put_object(Bucket=BUCKET, Key=key, Body=body if isinstance(body, bytes) else json.dumps(body).encode(), ContentType=ctype)


def _job_id(data):
    jid = str(data.get("job_id") or "")
    if not re.fullmatch(r"[0-9a-f]{32}", jid):
        raise ApiError(400, "invalid job_id")
    return jid


def _launch(path, jid):
    url, token = os.environ.get("NOVO_URL", "").rstrip("/"), os.environ.get("NOVO_TOKEN", "")
    if not url or not token:
        raise ApiError(503, "NOVO_URL / NOVO_TOKEN not configured; deploy services/novo/modal_app.py first")
    r = requests.post(f"{url}/{path}", json={"job_id": jid}, headers={"Authorization": f"Bearer {token}"}, timeout=20)
    if r.status_code >= 400:
        raise ApiError(502, f"novo launcher error: {r.text[:300]}")
    return r.json()


def _check(cond, msg):
    if not cond:
        raise ApiError(400, msg)


@api
def submit(data):
    if not BUCKET:
        raise ApiError(503, "NOVO_BUCKET not configured")
    code = os.environ.get("NOVO_ACCESS_CODE", "")
    if not code:
        raise ApiError(503, "NOVO_ACCESS_CODE not configured")
    if not hmac.compare_digest(str(data.get("access_code") or ""), code):
        raise ApiError(403, "wrong access code")
    _check(data.get("noncommercial") is True, "confirm non-commercial use (AP Novo weights terms)")

    cif = data.get("cif") or ""
    _check(isinstance(cif, str) and "data_" in cif[:2000] and len(cif) <= 3_000_000, "upload a motif CIF (under 3 MB)")
    motif_str = (data.get("motif_str") or "").strip()
    _check(re.fullmatch(r"[A-Za-z0-9,\-|{}/ ]{1,400}", motif_str), "motif_str looks invalid, e.g. A1,A2|10-40,{},2-30,{}/B1")
    atoms = (data.get("motif_atoms") or "").strip()
    _check(not atoms or re.fullmatch(r"[A-Za-z0-9:,'*\s]{1,400}", atoms), "motif_atoms looks invalid, e.g. A1:NE2,ND1 A2:OD1")
    seq_len = (data.get("seq_length") or "").strip()
    _check(not seq_len or re.fullmatch(r"\d{1,4}(-\d{1,4})?", seq_len), "seq_length must be 150 or 120-160")
    unidx = (data.get("unindexed_motif_residues") or "").strip()
    _check(not unidx or re.fullmatch(r"[A-Za-z0-9,\-\s]{1,200}", unidx), "unindexed_motif_residues looks invalid")
    n = int(data.get("num_designs") or 0)
    _check(1 <= n <= 300, "num_designs must be 1-300")
    steps = int(data.get("num_sampling_steps") or 1000)
    _check(50 <= steps <= 1000, "num_sampling_steps must be 50-1000")
    seeds = int(data.get("fold_seeds") or 1)
    _check(1 <= seeds <= 5, "fold_seeds must be 1-5")
    suite = data.get("suite") or None
    _check(suite is None or suite in SUITES, f"suite must be one of {sorted(SUITES)}")
    ligands = data.get("ligands") or []
    _check(isinstance(ligands, list) and len(ligands) <= 3, "up to 3 ligands")
    for l in ligands:
        _check(re.fullmatch(r"[A-Za-z]", str(l.get("id", ""))) and re.fullmatch(r"[A-Z0-9]{1,5}", str(l.get("ccd_code", ""))), "ligand needs a chain letter and a CCD code like 6NT")
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(data.get("name") or "enzyme"))[:24].strip("_") or "enzyme"
    reseq = data.get("resequence", True) is not False

    design = {"name": name, "output_prefix": name, "input_file": "motif.cif", "motif_str": motif_str,
              "is_author_naming": bool(data.get("is_author_naming")), "num_designs": n}
    if atoms:
        design["motif_atoms"] = atoms
    if seq_len:
        design["seq_length"] = seq_len
    if unidx:
        design["unindexed_motif_residues"] = unidx
    states = [{"name": "monomer", "ligands": [], "covalent_bonds": []}]
    if ligands:
        states.append({"name": "complex", "ligands": [{"id": l["id"], "ccd_code": l["ccd_code"]} for l in ligands], "covalent_bonds": []})
    manifest = {
        "defaults": {"num_sampling_steps": steps, "seed_start": 0},
        "designs": [design],
        "resequence": {"enabled": reseq, "temperature": 0.1, "num_sequences": 2, "use_side_chain_context": True},
        "folding": {"inputs": ["resequenced" if reseq else "generated"], "seeds": list(range(seeds)), "states": states},
    }
    if suite:
        manifest["evaluation"] = {"suite": suite}

    jid = uuid.uuid4().hex
    p = f"novo/{jid}/"
    _put(p + "input/motif.cif", cif.encode(), "chemical/x-cif")
    _put(p + "input/manifest.json", manifest)
    job = {"id": jid, "status": "queued", "stage": "queued", "name": name, "num_designs": n, "created": time.time(), "updated": time.time()}
    _put(p + "job.json", job)
    try:
        _launch("submit", jid)
    except ApiError:
        # Inputs are saved; the user can press Resume once the launcher is reachable.
        job.update(status="error", error="Saved, but the GPU launcher could not be reached. Press Resume.")
        _put(p + "job.json", job)
    return {"job_id": jid}


def _view(jid):
    job = _get(f"novo/{jid}/job.json")
    if not job:
        raise ApiError(404, "unknown job")
    job["job_id"] = jid
    if job.get("status") in ("queued", "running") and time.time() - job.get("updated", 0) > STALE_AFTER:
        job["status"] = "stalled"
    job["total"] = job.get("num_designs")
    if job.get("status") == "done":
        res = _get(f"novo/{jid}/results.json") or {}
        job["designs"] = res.get("designs", [])
        job["notice"] = NOTICE
    return job


@api
def status(data):
    return _view(_job_id(data))


@api
def resume(data):
    jid = _job_id(data)
    job = _view(jid)
    if job["status"] == "done":
        return job
    _launch("resume", jid)
    return job


@api
def download(data):
    jid = _job_id(data)
    key = str(data.get("key") or "")
    if not key.startswith("out/") or ".." in key:
        raise ApiError(400, "invalid key")
    full = f"novo/{jid}/{key}"
    url = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": full}, ExpiresIn=3600)
    return {"url": url}
