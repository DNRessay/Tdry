const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export type AlphaFold = { entry_id: string; pdb_url: string; cif_url: string; plddt: number } | null

export type Protein = {
  accession: string
  entry: string
  name: string
  gene: string
  organism: string
  length: number
  sequence: string
  alphafold: AlphaFold
}

export type Prediction = {
  protein: { accession: string; name: string; gene: string; organism: string; length: number }
  ligand: { query: string; cid: number; mw: number; logp: number; hbd: number; hba: number; tpsa: number; rotb: number }
  alphafold: AlphaFold
  binding_affinity_pct: number
  structural_confidence_pct: number
  components: { size_fit: number; hydrophobic_complementarity: number; druglikeness: number; lipinski_violations: number }
  recommendation: string
  similar_screened: { accession: string; name: string; organism: string; score: number; last_compound: string; last_affinity_pct: number }[]
  method: string
}

export type ChatMessage = { role: 'user' | 'assistant'; content: string }
export type AgentStep = { tool: string; args: Record<string, unknown>; error: string | null }

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error ?? `Request failed (${res.status})`)
  return data as T
}

export const searchProteins = (query: string, species: string) =>
  post<{ results: Protein[] }>('/proteins/search', { query, species })

export const predictDocking = (protein_id: string, target_compound: string) =>
  post<Prediction>('/docking/predict', { protein_id, target_compound })

export const chat = (messages: ChatMessage[]) =>
  post<{ reply: string; steps: AgentStep[] }>('/agent/chat', { messages })
