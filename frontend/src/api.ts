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

export type RnaRegion = { start: number; end: number; unpaired: number; seq: string }
export type RnaSite = { motif: string; start: number; end: number; seq: string; unpaired: number; reason?: string }
export type RnaLoop = { loop: number; site: RnaSite; result: string; design?: { id?: string; sequence?: string; plddt?: number }; score?: Record<string, unknown> }
export type RnaResult = {
  status: 'success' | 'exhausted' | 'needs_compute' | 'failed_inaccessible' | 'failed_no_motif'
  accessibility: { mfe: number; structure: string; regions: RnaRegion[] }
  loops: RnaLoop[]
  note?: string
  winner?: RnaLoop['design']
}

export type RnaAnalysis = { accessibility: RnaResult['accessibility']; motifs: RnaSite[] }

export const analyzeRna = (sequence: string) => post<RnaAnalysis>('/rna/design', { sequence, analyze: true })

export const designRna = (sequence: string, max_loops = 5, site?: RnaSite) =>
  post<RnaResult>('/rna/design', { sequence, max_loops, site })

export type PlantScore = { pos: number; ref: string; alt: string; llr: number }
export type PlantResult = { model: string; results: PlantScore[]; notice: string; interpretation: string }

export const scorePlantVariants = (sequence: string, variants: { pos: number; alt: string }[]) =>
  post<PlantResult>('/plant/variants', { sequence, variants })

export type LookupHit = { id: string; title: string; organism?: string; length?: number; detail?: string }
export type LookupKind = 'mrna' | 'plantdna' | 'compound' | 'binder'
export type LookupSeq = { sequence: string; length: number; truncated: boolean; label: string }

export const lookupSearch = (type: LookupKind, query: string) => post<{ results: LookupHit[] }>('/lookup', { type, query })
export const lookupFetch = (type: 'mrna' | 'plantdna', id: string) => post<LookupSeq>('/lookup', { type, action: 'fetch', id })

export type EnzymeDesign = {
  name: string
  score: number
  sequence: string
  metrics: Record<string, number | string>
  files: { label: string; key: string }[]
}
export type EnzymeMode = 'demo' | 'commercial'
export type EnzymeJob = {
  job_id: string
  mode?: EnzymeMode
  status: 'queued' | 'running' | 'done' | 'error' | 'stalled'
  stage?: string
  counts?: Record<string, number>
  total?: number
  error?: string | null
  designs?: EnzymeDesign[]
  notice?: string
}
export type EnzymeInput = {
  mode: EnzymeMode
  name: string
  cif: string  // file text: a CIF in demo mode, a PDB in commercial mode
  unindexed: boolean
  seqs_per_design: number
  motif_str: string
  motif_atoms: string
  seq_length: string
  is_author_naming: boolean
  num_designs: number
  ligands: { id: string; ccd_code: string }[]
  suite: string
  access_code: string
  noncommercial: boolean
}

export const submitEnzyme = (input: EnzymeInput) => post<{ job_id: string }>('/novo/submit', input)
export const enzymeStatus = (job_id: string) => post<EnzymeJob>('/novo/status', { job_id })
export const resumeEnzyme = (job_id: string) => post<EnzymeJob>('/novo/resume', { job_id })
export const enzymeFile = (job_id: string, key: string) => post<{ url: string }>('/novo/download', { job_id, key })
