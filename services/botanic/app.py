import os
import threading
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL = os.environ.get("BOTANIC_MODEL", "living-models/Botanic1-M")
MAX_BASES = 8191
MAX_VARIANTS = 50

app = FastAPI(title="Botanic1 plant DNA variant scoring")
_state = {}
_lock = threading.Lock()


def load():
    with _lock:
        if "model" not in _state:
            import torch
            from transformers import AutoModel, AutoTokenizer

            tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
            model = AutoModel.from_pretrained(MODEL, trust_remote_code=True)
            device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
            _state.update(model=model.to(device).eval(), tok=tok, device=device)
    return _state["model"], _state["tok"], _state["device"]


class Variant(BaseModel):
    pos: int = Field(ge=0, description="0-based position in the sequence")
    alt: str = Field(min_length=1, max_length=1)


class Req(BaseModel):
    sequence: str
    variants: list[Variant]


@app.get("/health")
def health():
    return {"model": MODEL, "loaded": "model" in _state}


@app.post("/score")
def score(req: Req):
    seq = req.sequence.strip().upper()
    if not 1 <= len(seq) <= MAX_BASES or set(seq) - set("ACGTN"):
        raise HTTPException(400, f"sequence must be 1-{MAX_BASES} bases of A/C/G/T/N")
    if not 1 <= len(req.variants) <= MAX_VARIANTS:
        raise HTTPException(400, f"send 1-{MAX_VARIANTS} variants")
    model, tok, _ = load()
    out = []
    for v in req.variants:
        alt = v.alt.upper()
        if v.pos >= len(seq):
            raise HTTPException(400, f"pos {v.pos} outside sequence")
        if alt not in "ACGT" or alt == seq[v.pos]:
            raise HTTPException(400, f"alt at pos {v.pos} must be A/C/G/T and differ from ref {seq[v.pos]}")
        llr = model.score_variant_zero_shot(sequence=seq, tokenizer=tok, variant_pos=v.pos, variant_char=alt)
        out.append({"pos": v.pos, "ref": seq[v.pos], "alt": alt, "llr": round(float(llr), 4)})
    return {"model": MODEL, "results": out}
