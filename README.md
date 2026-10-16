# T-Dry-Lab

Pre-screens proteins and compounds before lab work. React (Vite + TS) on Cloudflare Pages, AWS SAM (Python 3.11) backend.

Docking scores are a heuristic pre-screen (sequence composition, ligand physicochemical properties from PubChem, AlphaFold pLDDT). They are not physics-based docking. Use them to narrow candidates, then confirm with AutoDock Vina or DiffDock.

## Flow

One card at a time: project name, target type (protein, mRNA, plant DNA; generic DNA is shown as unavailable), target details (protein search and structure, mRNA folding check and motif pick, or plant DNA paste), binder step (compound, design attempts, or mutations), then results. The assistant chat opens from the results card.

## Endpoints

| Route | Payload |
|---|---|
| `POST /proteins/search` | `{"query": "caspase-9", "species": "generic"}` |
| `POST /docking/predict` | `{"protein_id": "P55211", "target_compound": "imatinib"}` |
| `POST /agent/chat` | `{"messages": [{"role": "user", "content": "..."}]}` |
| `POST /rna/design` | `{"sequence": "AUGUUU...", "max_loops": 5, "site": {"motif": "PUM1", "start": 11}}` or `{"sequence": "...", "analyze": true}` for folding and motifs only |
| `POST /plant/variants` | `{"sequence": "<plant DNA>", "variants": [{"pos": 251, "alt": "C"}]}` |

`target_compound` is a PubChem name or CID.

## RNA binder loop

`/rna/design` runs: ViennaRNA accessibility (MFE + unpaired probability per 8-nt window) -> RBP motif match on open loops (PUM1, RBFOX, HuR, MBNL, LIN28, FUS) -> Groq picks the best site -> binder design service -> Rosetta scoring service. On failure it moves to the next site. Loops are capped (`max_loops`, default 5, hard max 10).

Stops early with `failed_inaccessible` (no open region) before any compute is spent. Binder design and Rosetta run on your own GPU/CPU services: set `BinderUrl` and `ScoreUrl` at deploy. Contracts: binder `POST {rna, site}` -> `{id, sequence, plddt}`; score `POST {rna, site, design}` -> `{pass: bool, ...}`. Without them the endpoint returns `needs_compute` after the accessibility and motif stages. Lambda has a 29 s limit, so keep those services fast or make them async.

## Plant variant scoring (BOTANIC-1)

For **plant genomic DNA only**. BOTANIC-1 (Living Models, `living-models/Botanic1-S/M/L`) is a plant genome model; it scores variant effects (LLR = log P(alt) - log P(ref), strongly negative = likely disruptive). It does not do RNA folding or accessibility, and must not be used for human, animal or viral sequences. Weights are gated on Hugging Face and licensed for non-commercial research use only.

It needs a GPU/CPU host, so it runs as a separate service, not in Lambda:

```bash
cd services/botanic
pip install -r requirements.txt
hf auth login   # after accepting the terms on the model page
uvicorn app:app --host 0.0.0.0 --port 8000
```

Set `BotanicUrl` at deploy to that host's base URL. Positions are 0-based; max 8,191 bp and 50 variants per request. `BOTANIC_MODEL` env var on the service picks the size (default `living-models/Botanic1-M`).

## Backend

```bash
cd backend
sam build
sam deploy --guided --parameter-overrides GroqApiKeys="key1,key2" QdrantUrl="https://xxx.cloud.qdrant.io:6333" QdrantApiKey="..." AllowedOrigin="https://your-app.pages.dev"
```

Qdrant is optional; leave `QdrantUrl` empty to skip similar-protein lookup. Groq keys rotate on 429. Default model is `llama-3.3-70b-versatile` (`GroqModel` parameter).

## Frontend

```bash
cd frontend
cp .env.example .env   # set VITE_API_URL to the ApiUrl stack output
npm install
npm run dev
```

Deploy:

```bash
npm run build
npx wrangler pages deploy dist --project-name t-dry-lab
```
