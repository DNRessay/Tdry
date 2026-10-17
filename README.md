# T-Dry-Lab

Pre-screens proteins and compounds before lab work. React (Vite + TS) on Cloudflare Pages, AWS SAM (Python 3.11) backend.

Docking scores are a heuristic pre-screen (sequence composition, ligand physicochemical properties from PubChem, AlphaFold pLDDT). They are not physics-based docking. Use them to narrow candidates, then confirm with AutoDock Vina or DiffDock.

## Flow

One card at a time: project name, target type (protein, mRNA, plant DNA; generic DNA is shown as unavailable), target details (protein search and structure, mRNA folding check and motif pick, or plant DNA paste), binder step (compound, design attempts, or mutations), then results. The assistant chat opens from the results card.

## Public database lookup

`POST /lookup` finds sequences when the user has none at hand. `{"type": "mrna", "query": "PUM1"}` searches NCBI RefSeq mRNAs; `{"type": "plantdna", "query": "PHYB"}` searches NCBI Gene for plant genes and fetches the gene's genomic window (first 8,191 bases from the 5' end); `{"type": "compound", "query": "imat"}` autocompletes PubChem compound names. Add `"action": "fetch", "id": "<id from search>"` to get the sequence. Optional env `NCBI_API_KEY` and `NCBI_EMAIL` raise the NCBI rate limit.

## Known binders

On the protein binder step, `POST /lookup` with `{"type": "binder", "query": "<UniProt accession>"}` returns the strongest known ligands for that protein from ChEMBL, ranked by pChEMBL. Unnamed molecules are passed on as `smiles:<SMILES>` and resolved through PubChem when scored.

## Enzyme design: demo and commercial modes (Modal + S3)

The "Design an enzyme" card has a switch. Both modes run as async GPU jobs on Modal and **save everything to S3**: the job syncs `out/` to `s3://<NovoBucket>/novo/<job_id>/` every 60 s with a heartbeat in `job.json`; after a crash Modal retries (3x) on a fresh container that restores from S3, and finished stages are skipped. The API reads status and results from S3, not Modal. A job with no heartbeat for 5 min shows as stalled with a Resume button.

| | Demo | Commercial |
|---|---|---|
| Pipeline | AlphaProtein Novo, LigandMPNN, AlphaFold 3 | RFdiffusion2, LigandMPNN, Boltz, OpenMM relax |
| Input | motif CIF + manifest fields | motif PDB + contigs, fixed atoms, ligand code |
| Licences | Non-commercial weights; outputs for theoretical modeling only | RFdiffusion2 BSD-3, LigandMPNN MIT, Boltz MIT (code and weights) |
| Image | `image` (no open stack) | `open_image` (no AP Novo or AlphaFold code) |

For a commercial deployment set `DemoModeEnabled=false` (CI: repo variable `DEMO_MODE_ENABLED=false`) so the API refuses demo jobs, and `VITE_ENABLE_DEMO=false` to hide the button. Not legal advice: before selling, confirm the current terms of every weights file yourself. RFdiffusion2's repo is BSD-3 but states no separate weights licence, and its published env lists PyRosetta (commercially licensed). This image does not install PyRosetta, so if design inference needs it the run will fail instead of quietly using it. Rosetta and ESM3-open are not part of this stack. The Rosetta-style checks come from OpenMM (BSD-like) and PDBFixer (MIT): each folded complex gets ligand clash and contact counts, then the protein is minimised (AMBER14, implicit solvent, weak restraints) and `relax_dE_per_res` and `relax_ca_rmsd` are reported. Only ligand clashes affect the score; the energy is a strain proxy, not a binding energy. Open alternatives checked: Protenix (ByteDance) is Apache 2.0 for code and its released weights and could replace Boltz as the folder (not wired in; Protenix-v2 weights are proprietary); HelixFold3 (Baidu) is non-commercial; Uni-Fold has no ligand support.

Setup, in order:

```bash
# 1. Backend: creates the bucket, a write-only IAM user and the /novo/* routes
sam deploy ... --parameter-overrides NovoToken="<random>" NovoAccessCode="<code>"   # add NovoUrl after step 3
aws iam create-access-key --user-name <NovoWriterUser output>

# 2. Modal secret, then weights for the engine(s) you use
modal secret create novo-aws AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_REGION=... NOVO_BUCKET=<NovoBucketName output> NOVO_TOKEN=<same random>
modal run services/novo/modal_app.py::download_open_weights                  # commercial
modal run services/novo/modal_app.py::download_weights --accept-terms        # demo only; read its terms first

# 3. Deploy, then redeploy the backend with NovoUrl set to the printed tdry-novo-api URL
modal deploy services/novo/modal_app.py
```

CI secrets: `NOVO_URL`, `NOVO_TOKEN`, `NOVO_ACCESS_CODE`. `NOVO_GPU` (default `A100-80GB`) is read at `modal deploy`. Campaign data expires after `NovoRetentionDays` (default 90).

Caveats: neither image build nor a real GPU run has been tested; expect to iterate on the RFdiffusion2 conda env first. Boltz folds in single-sequence mode and downloads its weights into the volume on first run. Ranking is coarse (demo: pLDDT minus motif RMSD; commercial: pLDDT + ligand ipTM minus backbone RMSD); do real filtering before ordering DNA. Smoke-test with 1-2 designs. Relaxing needs a GPU to be quick (`RELAX_ITERS`, default 1000, controls the minimiser; on one CPU core it took about 3 s per iteration).

## Endpoints

| Route | Payload |
|---|---|
| `POST /proteins/search` | `{"query": "caspase-9", "species": "generic"}` |
| `POST /docking/predict` | `{"protein_id": "P55211", "target_compound": "imatinib"}` |
| `POST /novo/submit`, `/novo/status`, `/novo/resume`, `/novo/download` | see `backend/src/novo.py` |
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
