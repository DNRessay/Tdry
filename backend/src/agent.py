import json
import os
import random
import requests
from common import api, ApiError
from search import search_proteins
from predict import predict_binding

URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_STEPS = 5

SYSTEM = (
    "You are a bioinformatics pre-screening assistant. Use the tools to find proteins "
    "(UniProt/AlphaFold) and to score protein-ligand binding. Binding scores are heuristic "
    "pre-screening estimates, not physics-based docking: say so when reporting them. "
    "Be concise and cite accessions."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_proteins",
            "description": "Search UniProt for proteins by name, gene or keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "species": {"type": "string", "description": "Organism name or 'generic'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_docking",
            "description": "Score binding of a compound (PubChem name or CID) to a UniProt accession.",
            "parameters": {
                "type": "object",
                "properties": {
                    "protein_id": {"type": "string"},
                    "target_compound": {"type": "string"},
                },
                "required": ["protein_id", "target_compound"],
            },
        },
    },
]


def run_tool(name, args):
    try:
        if name == "search_proteins":
            res = search_proteins(args["query"], args.get("species", "generic"), limit=5)
            return [
                {k: p[k] for k in ("accession", "name", "gene", "organism", "length")}
                | {"plddt": (p["alphafold"] or {}).get("plddt")}
                for p in res
            ]
        if name == "predict_docking":
            return predict_binding(args["protein_id"], args["target_compound"])
        return {"error": f"unknown tool {name}"}
    except (ApiError, requests.RequestException, KeyError) as e:
        return {"error": str(e)}


def groq(messages):
    keys = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
    if not keys:
        raise ApiError(500, "GROQ_API_KEYS not configured")
    random.shuffle(keys)
    for key in keys:
        r = requests.post(
            URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.2,
            },
            timeout=25,
        )
        if r.status_code in (401, 429):
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]
    raise ApiError(429, "all Groq keys are rate limited")


@api
def handler(data):
    history = [m for m in data.get("messages", []) if m.get("role") in ("user", "assistant")]
    if not history:
        raise ApiError(400, "messages are required")
    messages = [{"role": "system", "content": SYSTEM}] + history
    steps = []
    for _ in range(MAX_STEPS):
        msg = groq(messages)
        calls = msg.get("tool_calls")
        if not calls:
            return {"reply": msg.get("content") or "", "steps": steps}
        messages.append(msg)
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except ValueError:
                args = {}
            result = run_tool(name, args)
            err = result.get("error") if isinstance(result, dict) else None
            steps.append({"tool": name, "args": args, "error": err})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)[:6000]})
    return {"reply": "Stopped after the maximum number of tool steps. Narrow the question and retry.", "steps": steps}
