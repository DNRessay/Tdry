import os
import requests
from common import api, ApiError

MAX_BASES = 8191
MAX_VARIANTS = 50
NOTICE = "BOTANIC-1 is a plant DNA model (research use only). Do not use it for human, animal, viral or RNA-folding questions."


def clean(data):
    seq = "".join((data.get("sequence") or "").split()).upper()
    if not 1 <= len(seq) <= MAX_BASES or set(seq) - set("ACGTN"):
        raise ApiError(400, f"sequence must be 1-{MAX_BASES} bases of A/C/G/T/N (plant genomic DNA)")
    variants = data.get("variants")
    if not isinstance(variants, list) or not 1 <= len(variants) <= MAX_VARIANTS:
        raise ApiError(400, f"variants must be a list of 1-{MAX_VARIANTS} items: {{pos (0-based), alt}}")
    out = []
    for v in variants:
        try:
            pos, alt = int(v["pos"]), str(v["alt"]).upper()
        except (KeyError, TypeError, ValueError):
            raise ApiError(400, "each variant needs pos (int) and alt (A/C/G/T)")
        if not 0 <= pos < len(seq) or alt not in ("A", "C", "G", "T") or alt == seq[pos]:
            raise ApiError(400, f"invalid variant at pos {pos}: alt must be A/C/G/T, differ from the reference base, and pos must be inside the sequence")
        out.append({"pos": pos, "alt": alt})
    return seq, out


@api
def handler(data):
    seq, variants = clean(data)
    url = os.environ.get("BOTANIC_URL", "").rstrip("/")
    if not url:
        raise ApiError(503, "BOTANIC_URL not configured; deploy services/botanic on a GPU host")
    r = requests.post(f"{url}/score", json={"sequence": seq, "variants": variants}, timeout=25)
    if r.status_code >= 400:
        raise ApiError(502, f"botanic service error: {r.text[:300]}")
    body = r.json()
    body["results"].sort(key=lambda x: x["llr"])
    body["notice"] = NOTICE
    body["interpretation"] = "LLR = log P(alt) - log P(ref); strongly negative = likely disruptive. Not calibrated across positions or species."
    return body
