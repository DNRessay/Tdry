import os
import requests
from common import api, ApiError


@api
def handler(data):
    compound = (data.get("compound") or "").strip()
    if not compound:
        raise ApiError(400, "compound is required")
    url = os.environ.get("NOVO_URL", "").rstrip("/")
    if not url:
        raise ApiError(503, "NOVO_URL not configured; run AlphaProtein Novo on your own GPU host and set NovoUrl")
    r = requests.post(
        f"{url}/design",
        json={"compound": compound, "protein_accession": data.get("protein_accession")},
        timeout=25,
    )
    if r.status_code >= 400:
        raise ApiError(502, f"novo service error: {r.text[:300]}")
    return r.json()
