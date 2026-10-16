import os
import re
import requests
from common import api, ApiError

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBCHEM_AC = "https://pubchem.ncbi.nlm.nih.gov/rest/autocomplete/compound"
CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"
LIMITS = {"mrna": 2000, "plantdna": 8191}


def eutils(tool, **params):
    params.update(tool="t-dry-lab", email=os.environ.get("NCBI_EMAIL", ""))
    key = os.environ.get("NCBI_API_KEY")
    if key:
        params["api_key"] = key
    r = requests.get(f"{EUTILS}/{tool}.fcgi", params=params, timeout=15)
    r.raise_for_status()
    return r


def search_mrna(q):
    ids = eutils("esearch", db="nuccore", retmode="json", retmax=8,
                 term=f"({q}) AND biomol_mrna[PROP] AND srcdb_refseq[PROP]").json()["esearchresult"]["idlist"]
    if not ids:
        return []
    res = eutils("esummary", db="nuccore", retmode="json", id=",".join(ids)).json()["result"]
    return [
        {"id": res[i]["accessionversion"], "title": res[i]["title"], "organism": res[i].get("organism", ""), "length": res[i].get("slen", 0)}
        for i in ids if i in res
    ]


def search_plant(q):
    ids = eutils("esearch", db="gene", retmode="json", retmax=8,
                 term=f"({q}) AND viridiplantae[Organism] AND alive[prop]").json()["esearchresult"]["idlist"]
    if not ids:
        return []
    res = eutils("esummary", db="gene", retmode="json", id=",".join(ids)).json()["result"]
    out = []
    for i in ids:
        g = res.get(i)
        loc = (g or {}).get("genomicinfo") or []
        if not loc:
            continue
        a, b = int(loc[0]["chrstart"]), int(loc[0]["chrstop"])
        lo, hi = min(a, b) + 1, max(a, b) + 1
        strand = 2 if a > b else 1
        out.append({
            "id": f"{loc[0]['chraccver']}|{lo}|{hi}|{strand}",
            "title": f"{g.get('name', '')}: {g.get('description', '')}",
            "organism": (g.get("organism") or {}).get("scientificname", ""),
            "length": hi - lo + 1,
        })
    return out


def parse_fasta(text):
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith(">")]
    seq = "".join(lines).upper()
    if not seq or re.search(r"[^ACGTUN]", seq):
        raise ApiError(502, "database returned an unexpected sequence")
    return seq


def fetch_sequence(kind, ident):
    limit = LIMITS[kind]
    if kind == "mrna":
        if not re.fullmatch(r"[A-Z]{1,2}_?\d+(\.\d+)?", ident):
            raise ApiError(400, "invalid accession")
        seq = parse_fasta(eutils("efetch", db="nuccore", id=ident, rettype="fasta", retmode="text").text)
        total = len(seq)
        return {"sequence": seq[:limit], "length": total, "truncated": total > limit, "label": ident}
    try:
        acc, lo, hi, strand = ident.split("|")
        lo, hi, strand = int(lo), int(hi), int(strand)
    except ValueError:
        raise ApiError(400, "invalid id")
    if not re.fullmatch(r"[A-Z]{1,2}_?\d+(\.\d+)?", acc):
        raise ApiError(400, "invalid accession")
    total = hi - lo + 1
    if total > limit:
        if strand == 2:
            lo = hi - limit + 1
        else:
            hi = lo + limit - 1
    seq = parse_fasta(eutils("efetch", db="nuccore", id=acc, rettype="fasta", retmode="text",
                             seq_start=lo, seq_stop=hi, strand=strand).text)
    return {"sequence": seq, "length": total, "truncated": total > limit, "label": acc}


def search_compound(q):
    r = requests.get(f"{PUBCHEM_AC}/{requests.utils.quote(q, safe='')}/json", params={"limit": 8}, timeout=10)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return [{"id": n, "title": n} for n in (r.json().get("dictionary_terms", {}).get("compound") or [])]


def search_binders(accession):
    if not re.fullmatch(r"[A-Z0-9]{6,10}", accession.upper()):
        raise ApiError(400, "query must be a UniProt accession for binder lookup")
    t = requests.get(f"{CHEMBL}/target.json", params={"target_components__accession": accession.upper(), "limit": 5}, timeout=15)
    t.raise_for_status()
    targets = t.json().get("targets", [])
    single = [x for x in targets if x.get("target_type") == "SINGLE PROTEIN"] or targets
    if not single:
        return []
    a = requests.get(
        f"{CHEMBL}/activity.json",
        params={"target_chembl_id": single[0]["target_chembl_id"], "pchembl_value__isnull": "false", "order_by": "-pchembl_value", "limit": 80},
        timeout=20,
    )
    a.raise_for_status()
    seen, out = set(), []
    for x in a.json().get("activities", []):
        mid, smi = x.get("molecule_chembl_id"), x.get("canonical_smiles")
        if not mid or mid in seen or not smi or len(smi) > 200:
            continue
        seen.add(mid)
        name = x.get("molecule_pref_name")
        out.append({
            "id": name.title() if name else f"smiles:{smi}",
            "title": name.title() if name else mid,
            "detail": f"{x.get('standard_type', 'activity')} pChEMBL {x.get('pchembl_value')} ({mid})",
        })
        if len(out) == 10:
            break
    return out


@api
def handler(data):
    kind, action = data.get("type"), data.get("action", "search")
    q = (data.get("query") or "").strip()
    if kind == "compound":
        if not q:
            raise ApiError(400, "query is required")
        return {"results": search_compound(q)}
    if kind == "binder":
        if not q:
            raise ApiError(400, "query is required")
        return {"results": search_binders(q)}
    if kind not in LIMITS:
        raise ApiError(400, "type must be mrna, plantdna, compound or binder")
    if action == "fetch":
        ident = (data.get("id") or "").strip()
        if not ident:
            raise ApiError(400, "id is required")
        return fetch_sequence(kind, ident)
    if not q:
        raise ApiError(400, "query is required")
    return {"results": search_mrna(q) if kind == "mrna" else search_plant(q)}
