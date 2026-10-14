import math
import os
import uuid
from urllib.parse import quote
import requests
from common import api, ApiError
from search import fetch_protein, fetch_alphafold

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound"
PROPS = "MolecularWeight,XLogP,HBondDonorCount,HBondAcceptorCount,TPSA,RotatableBondCount"
COLLECTION = "proteins"
AMINO = "ACDEFGHIKLMNPQRSTVWY"
HYDROPHOBIC = set("AVILMFWC")


def fetch_ligand(compound):
    key = "cid" if compound.isdigit() else "name"
    r = requests.get(f"{PUBCHEM}/{key}/{quote(compound)}/property/{PROPS}/JSON", timeout=15)
    if r.status_code == 404:
        raise ApiError(422, f"compound '{compound}' not found in PubChem (use a compound name or CID)")
    r.raise_for_status()
    p = r.json()["PropertyTable"]["Properties"][0]
    return {
        "cid": p["CID"],
        "mw": float(p.get("MolecularWeight", 0)),
        "logp": float(p.get("XLogP", 0) or 0),
        "hbd": p.get("HBondDonorCount", 0),
        "hba": p.get("HBondAcceptorCount", 0),
        "tpsa": float(p.get("TPSA", 0) or 0),
        "rotb": p.get("RotatableBondCount", 0),
    }


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def score(seq, ligand, plddt):
    violations = sum([ligand["mw"] > 500, ligand["logp"] > 5, ligand["hbd"] > 5, ligand["hba"] > 10])
    druglike = 1 - violations / 4
    size_fit = math.exp(-(((ligand["mw"] - 380) / 200) ** 2))
    prot_h = sum(c in HYDROPHOBIC for c in seq) / max(len(seq), 1)
    complement = 1 - abs(clamp((ligand["logp"] + 1) / 6) - clamp(prot_h / 0.6))
    confidence = clamp(plddt / 100) if plddt else 0.5
    affinity = 100 * (0.35 * size_fit + 0.25 * complement + 0.20 * druglike + 0.20 * confidence)
    return {
        "binding_affinity_pct": round(affinity, 1),
        "structural_confidence_pct": round(confidence * 100, 1),
        "components": {
            "size_fit": round(size_fit, 3),
            "hydrophobic_complementarity": round(complement, 3),
            "druglikeness": round(druglike, 3),
            "lipinski_violations": violations,
        },
    }


def recommend(affinity, confidence):
    if affinity >= 70 and confidence >= 70:
        return "Advance to in-vitro validation"
    if affinity >= 50:
        return "Re-screen with physics-based docking (AutoDock Vina / DiffDock) before lab work"
    return "Deprioritize; exclude from the testing set"


def embed(seq):
    n = max(len(seq), 1)
    vec = [seq.count(a) / n for a in AMINO]
    norm = math.sqrt(sum(v * v for v in vec)) or 1
    return [v / norm for v in vec]


def _qdrant():
    url = os.environ.get("QDRANT_URL", "").rstrip("/")
    if not url:
        return None, None
    key = os.environ.get("QDRANT_API_KEY", "")
    return url, ({"api-key": key} if key else {})


def similar_proteins(protein, affinity, compound):
    url, headers = _qdrant()
    if not url:
        return []
    try:
        if requests.get(f"{url}/collections/{COLLECTION}", headers=headers, timeout=8).status_code == 404:
            requests.put(
                f"{url}/collections/{COLLECTION}",
                headers=headers,
                json={"vectors": {"size": 20, "distance": "Cosine"}},
                timeout=8,
            ).raise_for_status()
        vec = embed(protein["sequence"])
        hits = requests.post(
            f"{url}/collections/{COLLECTION}/points/search",
            headers=headers,
            json={"vector": vec, "limit": 6, "with_payload": True},
            timeout=8,
        ).json().get("result", [])
        requests.put(
            f"{url}/collections/{COLLECTION}/points",
            headers=headers,
            json={
                "points": [
                    {
                        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, protein["accession"])),
                        "vector": vec,
                        "payload": {
                            "accession": protein["accession"],
                            "name": protein["name"],
                            "organism": protein["organism"],
                            "last_compound": compound,
                            "last_affinity_pct": affinity,
                        },
                    }
                ]
            },
            timeout=8,
        ).raise_for_status()
        return [
            {"score": round(h["score"], 4), **h["payload"]}
            for h in hits
            if h["payload"].get("accession") != protein["accession"]
        ][:5]
    except requests.RequestException:
        return []


def predict_binding(protein_id, compound):
    protein = fetch_protein(protein_id)
    af = fetch_alphafold(protein_id)
    ligand = fetch_ligand(compound)
    s = score(protein["sequence"], ligand, af["plddt"] if af else None)
    return {
        "protein": {k: protein[k] for k in ("accession", "name", "gene", "organism", "length")},
        "ligand": {"query": compound, **ligand},
        "alphafold": af,
        **s,
        "recommendation": recommend(s["binding_affinity_pct"], s["structural_confidence_pct"]),
        "similar_screened": similar_proteins(protein, s["binding_affinity_pct"], compound),
        "method": "heuristic pre-screen (sequence + ligand physchem + AlphaFold pLDDT); not a physics-based docking result",
    }


@api
def handler(data):
    protein_id = (data.get("protein_id") or "").strip()
    compound = (data.get("target_compound") or "").strip()
    if not protein_id or not compound:
        raise ApiError(400, "protein_id and target_compound are required")
    return predict_binding(protein_id, compound)
