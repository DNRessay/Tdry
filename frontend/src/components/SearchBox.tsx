import { useState } from 'react'
import { Protein, searchProteins } from '../api'

type Props = {
  selected: string | null
  onResults: (p: Protein[]) => void
  onSelect: (p: Protein) => void
  results: Protein[]
}

export default function SearchBox({ selected, results, onResults, onSelect }: Props) {
  const [query, setQuery] = useState('')
  const [species, setSpecies] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)

  async function run() {
    if (!query.trim()) return
    setBusy(true)
    setError('')
    try {
      const { results } = await searchProteins(query.trim(), species.trim() || 'generic')
      onResults(results)
      setSearched(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>Find a target</h2>
      <div className="row">
        <input
          value={query}
          placeholder="Protein, gene or keyword, e.g. caspase-9"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run()}
          aria-label="Protein search"
        />
      </div>
      <div className="row">
        <input value={species} placeholder="Species (optional)" onChange={(e) => setSpecies(e.target.value)} aria-label="Species" />
        <button onClick={run} disabled={busy || !query.trim()}>
          {busy ? 'Searching…' : 'Search'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {searched && !results.length && !error && <p className="muted">No proteins matched. Try a gene symbol or drop the species filter.</p>}
      <ul className="results">
        {results.map((p) => (
          <li key={p.accession}>
            <button className={p.accession === selected ? 'result active' : 'result'} onClick={() => onSelect(p)}>
              <span className="result-name">{p.name || p.entry}</span>
              <span className="result-meta">
                {p.accession} · {p.gene || 'no gene'} · {p.length} aa
              </span>
              <span className="result-meta">
                <i>{p.organism}</i>
                {p.alphafold ? ` · pLDDT ${p.alphafold.plddt.toFixed(0)}` : ' · no AlphaFold model'}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
