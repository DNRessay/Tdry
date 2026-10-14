# Bio AI Assistant

Pre-screens proteins and compounds before lab work. React (Vite + TS) on Cloudflare Pages, AWS SAM (Python 3.11) backend.

Docking scores are a heuristic pre-screen (sequence composition, ligand physicochemical properties from PubChem, AlphaFold pLDDT). They are not physics-based docking. Use them to narrow candidates, then confirm with AutoDock Vina or DiffDock.

## Endpoints

| Route | Payload |
|---|---|
| `POST /proteins/search` | `{"query": "caspase-9", "species": "generic"}` |
| `POST /docking/predict` | `{"protein_id": "P55211", "target_compound": "imatinib"}` |
| `POST /agent/chat` | `{"messages": [{"role": "user", "content": "..."}]}` |

`target_compound` is a PubChem name or CID.

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
npx wrangler pages deploy dist --project-name bio-ai-assistant
```
