from concurrent.futures import ThreadPoolExecutor
import requests
from common import api, ApiError

UNIPROT = "https://rest.uniprot.org/uniprotkb"
ALPHAFOLD = "https://alphafold.ebi.ac.uk/api/prediction"
FIELDS = "accession,id,protein_name,gene_names,organism_name,length,sequence"


def _name(item):
    desc = item.get("proteinDescription", {})
    for key in ("recommendedName", "submissionNames", "alternativeNames"):
        node = desc.get(key)
        if isinstance(node, list):
            node = node[0] if node else None
        if node:
            return node.get("fullName", {}).get("value", "")
    return ""


def _parse(item):
    genes = item.get("genes") or []
    gene = genes[0].get("geneName", {}).get("value", "") if genes else ""
    seq = item.get("sequence", {})
    return {
        "accession": item["primaryAccession"],
        "entry": item.get("uniProtkbId", ""),
        "name": _name(item),
        "gene": gene,
        "organism": item.get("organism", {}).get("scientificName", ""),
        "length": seq.get("length", 0),
        "sequence": seq.get("value", ""),
    }


def fetch_protein(accession):
    r = requests.get(
        f"{UNIPROT}/search",
        params={"query": f"accession:{accession}", "format": "json", "size": 1, "fields": FIELDS},
        timeout=15,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        raise ApiError(404, f"protein {accession} not found in UniProt")
    return _parse(results[0])


def fetch_alphafold(accession):
    r = requests.get(f"{ALPHAFOLD}/{accession}", timeout=15)
    if r.status_code != 200:
        return None
    data = r.json()
    if not data:
        return None
    m = data[0]
    return {
        "entry_id": m.get("entryId"),
        "pdb_url": m.get("pdbUrl"),
        "cif_url": m.get("cifUrl"),
        "plddt": m.get("globalMetricValue"),
    }


def _safe_af(accession):
    try:
        return fetch_alphafold(accession)
    except requests.RequestException:
        return None


def search_proteins(query, species="generic", limit=8):
    q = query
    if species and species.lower() != "generic":
        q = f'({query}) AND (organism_name:"{species}")'
    r = requests.get(
        f"{UNIPROT}/search",
        params={"query": q, "format": "json", "size": limit, "fields": FIELDS},
        timeout=15,
    )
    r.raise_for_status()
    proteins = [_parse(i) for i in r.json().get("results", [])]
    with ThreadPoolExecutor(max_workers=8) as pool:
        structures = list(pool.map(lambda p: _safe_af(p["accession"]), proteins))
    for p, s in zip(proteins, structures):
        p["alphafold"] = s
    return proteins


@api
def handler(data):
    query = (data.get("query") or "").strip()
    if not query:
        raise ApiError(400, "query is required")
    return {"results": search_proteins(query, data.get("species", "generic"))}
