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
OPEN_NOTICE = (
    "Designs come from RFdiffusion2, LigandMPNN and Boltz. Confirm each model's current licence and weights terms before "
    "commercial use. Ranking here is a coarse sort of pLDDT, ligand ipTM and backbone RMSD; validate before ordering DNA."
)
NOTICE = (
    "Designs come from AlphaProtein Novo and are subject to the AP Novo Generator Output Terms of Use. "
    "For theoretical modeling only; ranking here is a coarse sort of pLDDT and motif RMSD."
)


def get_s3():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("s3", region_name=region)


def _get(key):
    s3 = get_s3()
    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except Exception:
        return None


def _put(key, body, ctype="application/json"):
    s3 = get_s3()
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


def _common(data):
    """Fields shared by both engines. Returns a dict of validated values."""
    motif_str = (data.get("motif_str") or "").strip()
    atoms = (data.get("motif_atoms") or "").strip()
    try:
        n = int(data.get("num_designs") or 0)
    except (ValueError, TypeError):
        raise ApiError(400, "num_designs must be an integer between 1 and 300")
    _check(1 <= n <= 300, "num_designs must be 1-300")
    ligands = data.get("ligands") or []
    _check(isinstance(ligands, list) and len(ligands) <= 3, "up to 3 ligands")
    for l in ligands:
        _check(re.fullmatch(r"[A-Za-z0-9]{1,5}", str(l.get("ccd_code", ""))), "ligand needs a CCD / residue code like 6NT")
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(data.get("name") or "enzyme"))[:24].strip("_") or "enzyme"
    return motif_str, atoms, n, ligands, name


def _demo_inputs(data):
    cif = data.get("cif") or ""
    _check(isinstance(cif, str) and "data_" in cif[:2000] and len(cif) <= 3_000_000, "upload a motif CIF (under 3 MB)")
    motif_str, atoms, n, ligands, name = _common(data)
    _check(re.fullmatch(r"[A-Za-z0-9,\-|{}/ ]{1,400}", motif_str), "motif_str looks invalid, e.g. A1,A2|10-40,{},2-30,{}/B1")
    _check(not atoms or re.fullmatch(r"[A-Za-z0-9:,'*\s]{1,400}", atoms), "motif_atoms looks invalid, e.g. A1:NE2,ND1 A2:OD1")
    seq_len = (data.get("seq_length") or "").strip()
    _check(not seq_len or re.fullmatch(r"\d{1,4}(-\d{1,4})?", seq_len), "seq_length must be 150 or 120-160")
    unidx = (data.get("unindexed_motif_residues") or "").strip()
    _check(not unidx or re.fullmatch(r"[A-Za-z0-9,\-\s]{1,200}", unidx), "unindexed_motif_residues looks invalid")
    try:
        steps = int(data.get("num_sampling_steps") or 1000)
    except (ValueError, TypeError):
        raise ApiError(400, "num_sampling_steps must be an integer")
    _check(50 <= steps <= 1000, "num_sampling_steps must be 50-1000")
    try:
        seeds = int(data.get("fold_seeds") or 1)
    except (ValueError, TypeError):
        raise ApiError(400, "fold_seeds must be an integer")
    _check(1 <= seeds <= 5, "fold_seeds must be 1-5")
    suite = data.get("suite") or None
    _check(suite is None or suite in SUITES, f"suite must be one of {sorted(SUITES)}")
    for l in ligands:
        _check(re.fullmatch(r"[A-Za-z]", str(l.get("id", ""))), "ligand needs a chain letter")
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
    files = {"input/motif.cif": (cif.encode(), "chemical/x-cif"), "input/manifest.json": (manifest, "application/json")}
    return name, n, "novo", files


def _open_inputs(data):
    pdb = data.get("cif") or ""  # the card sends the uploaded file text in this field for both modes
    _check(isinstance(pdb, str) and re.search(r"^(ATOM|HETATM)", pdb, re.M) and len(pdb) <= 3_000_000, "upload a motif PDB (under 3 MB)")
    motif_str, atoms, n, ligands, name = _common(data)
    _check(re.fullmatch(r"[A-Za-z0-9,\-/ ]{1,400}", motif_str), "contigs look invalid, e.g. 46,A106-106,59,A166-166,2,A169-169,46")
    contig_atoms = {}
    for tok in atoms.split():
        m = re.fullmatch(r"([A-Za-z]\d{1,5}):([A-Z0-9',]{1,60})", tok)
        _check(m, "fixed atoms look invalid, e.g. A106:NE,CD,CZ A166:OD1,CG")
        contig_atoms[m.group(1)] = m.group(2)
    try:
        per = int(data.get("seqs_per_design") or 4)
    except (ValueError, TypeError):
        raise ApiError(400, "seqs_per_design must be an integer")
    _check(1 <= per <= 8, "seqs_per_design must be 1-8")
    cfg = {"engine": "open", "contigs": motif_str, "contig_atoms": contig_atoms, "unindexed": bool(data.get("unindexed")),
           "ligands": [l["ccd_code"].upper() for l in ligands], "num_designs": n, "seqs_per_design": per}
    return name, n, "open", {"input/motif.pdb": (pdb.encode(), "chemical/x-pdb"), "input/open.json": (cfg, "application/json")}


@api
def submit(data):
    if not BUCKET:
        raise ApiError(503, "NOVO_BUCKET not configured")
    code = os.environ.get("NOVO_ACCESS_CODE", "")
    if not code:
        raise ApiError(503, "NOVO_ACCESS_CODE not configured")
    if not hmac.compare_digest(str(data.get("access_code") or ""), code):
        raise ApiError(403, "wrong access code")

    mode = data.get("mode") or "demo"
    _check(mode in ("demo", "commercial"), "mode must be demo or commercial")
    if mode == "demo":
        if os.environ.get("DEMO_MODE_ENABLED", "true").lower() != "true":
            raise ApiError(403, "demo mode (AlphaProtein Novo, non-commercial) is disabled on this deployment; use commercial mode")
        _check(data.get("noncommercial") is True, "confirm non-commercial use (AP Novo weights terms)")
        name, n, engine, files = _demo_inputs(data)
    else:
        name, n, engine, files = _open_inputs(data)

    jid = uuid.uuid4().hex
    p = f"novo/{jid}/"
    for key, (body, ctype) in files.items():
        _put(p + key, body, ctype)
    job = {"id": jid, "status": "queued", "stage": "queued", "name": name, "num_designs": n, "engine": engine, "mode": mode,
           "created": time.time(), "updated": time.time()}
    _put(p + "job.json", job)
    try:
        _launch("submit", jid)
    except Exception as e:
        # Inputs are saved; the user can press Resume once the launcher is reachable.
        job.update(status="error", error=f"Saved, but the GPU launcher could not be reached: {str(e)[:200]}. Press Resume.")
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
        job["notice"] = OPEN_NOTICE if job.get("engine") == "open" else NOTICE
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
    s3 = get_s3()
    url = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": full}, ExpiresIn=3600)
    return {"url": url}
