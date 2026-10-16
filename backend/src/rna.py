import json
import os
import random
import re
import requests
from common import api, ApiError

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
HARD_MAX_LOOPS = 10
WINDOW = 8
MIN_UNPAIRED = 0.6

MOTIFS = {
    "PUM1": r"UGUA[ACU]AUA",
    "RBFOX": r"UGCAUG",
    "HuR": r"UUUUU|AUUUA",
    "MBNL": r"[CU]GC[CU]",
    "LIN28": r"GGAG",
    "FUS": r"GGUG",
}


def clean_rna(seq):
    s = re.sub(r"\s+", "", seq or "").upper().replace("T", "U")
    if not 10 <= len(s) <= 2000 or set(s) - set("ACGU"):
        raise ApiError(400, "sequence must be 10-2000 nt of A/C/G/U/T")
    return s


def accessibility(seq):
    try:
        import RNA
    except ImportError:
        raise ApiError(500, "ViennaRNA not installed")
    structure, mfe = RNA.fold(seq)
    fc = RNA.fold_compound(seq)
    fc.pf()
    n = len(seq)
    unpaired = [1.0] * n
    bpp = fc.bpp()
    for i in range(1, n + 1):
        unpaired[i - 1] = 1.0 - sum(bpp[min(i, j)][max(i, j)] for j in range(1, n + 1) if j != i)
    regions = []
    for start in range(0, n - WINDOW + 1):
        p = sum(unpaired[start:start + WINDOW]) / WINDOW
        if p >= MIN_UNPAIRED:
            regions.append({"start": start + 1, "end": start + WINDOW, "unpaired": round(p, 3), "seq": seq[start:start + WINDOW]})
    regions.sort(key=lambda r: -r["unpaired"])
    return {"mfe": round(mfe, 2), "structure": structure, "regions": regions}


def motif_hits(seq, regions):
    hits = []
    for name, pat in MOTIFS.items():
        for m in re.finditer(pat, seq):
            a, b = m.start() + 1, m.end()
            open_ = [r for r in regions if r["start"] <= a and r["end"] >= b - WINDOW + 1 and r["start"] <= b]
            best = max((r["unpaired"] for r in regions if r["start"] <= b and r["end"] >= a), default=0)
            if best >= MIN_UNPAIRED or open_:
                hits.append({"motif": name, "start": a, "end": b, "seq": m.group(), "unpaired": best})
    hits.sort(key=lambda h: -h["unpaired"])
    return hits


def groq_pick(seq, candidates, tried):
    keys = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
    if not keys or not candidates:
        return candidates[0] if candidates else None
    random.shuffle(keys)
    prompt = (
        f"mRNA length {len(seq)}. Candidate RBP motif sites in accessible loops: {json.dumps(candidates[:12])}. "
        f"Already failed: {json.dumps(tried)}. Pick the single best site for designing a sequence-specific RNA-binding protein. "
        'Reply JSON only: {"index": <int index into candidates>, "reason": "<one sentence>"}'
    )
    for key in keys:
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.environ.get("RNA_MOTIF_MODEL", "llama-3.3-70b-versatile"),
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
            timeout=20,
        )
        if r.status_code in (401, 429):
            continue
        r.raise_for_status()
        try:
            out = json.loads(r.json()["choices"][0]["message"]["content"])
            c = dict(candidates[int(out["index"])])
            c["reason"] = out.get("reason", "")
            return c
        except (ValueError, KeyError, IndexError, TypeError):
            break
    return candidates[0]


def call_stage(env, payload):
    url = os.environ.get(env, "").rstrip("/")
    if not url:
        return None
    r = requests.post(url, json=payload, timeout=int(os.environ.get("STAGE_TIMEOUT", "20")))
    r.raise_for_status()
    return r.json()


def run_loop(seq, max_loops, prefer=None):
    acc = accessibility(seq)
    if not acc["regions"]:
        return {"status": "failed_inaccessible", "accessibility": acc, "loops": [], "note": "No open region; target RNA is folded shut. Stopped before any protein design."}
    hits = motif_hits(seq, acc["regions"])
    if not hits:
        return {"status": "failed_no_motif", "accessibility": acc, "loops": [], "note": "Open regions found but no known RBP motif matches."}
    loops, tried = [], []
    for i in range(1, max_loops + 1):
        remaining = [h for h in hits if (h["motif"], h["start"]) not in {(t["motif"], t["start"]) for t in tried}]
        if not remaining:
            break
        pref = next((h for h in remaining if prefer and h["motif"] == prefer.get("motif") and h["start"] == prefer.get("start")), None) if i == 1 else None
        site = pref or groq_pick(seq, remaining, tried)
        entry = {"loop": i, "site": site}
        design = call_stage("BINDER_URL", {"rna": seq, "site": site})
        if design is None:
            entry["result"] = "binder service not configured"
            loops.append(entry)
            return {"status": "needs_compute", "accessibility": acc, "loops": loops, "note": "Set BINDER_URL and SCORE_URL to GPU services to run binder design and Rosetta scoring."}
        entry["design"] = {k: design.get(k) for k in ("id", "sequence", "plddt")}
        score = call_stage("SCORE_URL", {"rna": seq, "site": site, "design": design})
        if score is None:
            entry["result"] = "score service not configured"
            loops.append(entry)
            return {"status": "needs_compute", "accessibility": acc, "loops": loops, "note": "Set SCORE_URL for Rosetta scoring."}
        entry["score"] = score
        entry["result"] = "pass" if score.get("pass") else "fail"
        loops.append(entry)
        if score.get("pass"):
            return {"status": "success", "accessibility": acc, "loops": loops, "winner": entry["design"]}
        tried.append(site)
    return {"status": "exhausted", "accessibility": acc, "loops": loops, "note": f"No passing design within {len(loops)} loops."}


@api
def handler(data):
    seq = clean_rna(data.get("sequence"))
    try:
        max_loops = int(data.get("max_loops", 5))
    except (TypeError, ValueError):
        raise ApiError(400, "max_loops must be an integer")
    if data.get("analyze"):
        acc = accessibility(seq)
        return {"accessibility": acc, "motifs": motif_hits(seq, acc["regions"])}
    prefer = data.get("site") if isinstance(data.get("site"), dict) else None
    return run_loop(seq, max(1, min(max_loops, HARD_MAX_LOOPS)), prefer)
