import { useState } from 'react'
import { Protein, searchProteins } from '../api'
import Card from './Card'
import StructureViewer from './StructureViewer'

type Props = { selected: Protein | null; onSelect: (p: Protein) => void; onNext: () => void; onBack: () => void }

export default function ProteinTarget({ selected, onSelect, onNext, onBack }: Props) {
  const [query, setQuery] = useState('')
  const [species, setSpecies] = useState('')
  const [results, setResults] = useState<Protein[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)

  async function run() {
    if (!query.trim()) return
    setBusy(true)
    setError('')
    try {
      const { results } = await searchProteins(query.trim(), species.trim() || 'generic')
      setResults(results)
      setSearched(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card question="Which protein do you want to target?" hint="Search by name, gene or keyword. Pick one to see its structure." wide onBack={onBack}>
      <div className="row">
        <input
          className="big"
          autoFocus
          value={query}
          placeholder="e.g. caspase-9"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run()}
          aria-label="Protein search"
        />
        <input value={species} placeholder="Species (optional)" onChange={(e) => setSpecies(e.target.value)} aria-label="Species" className="narrow" />
        <button onClick={run} disabled={busy || !query.trim()}>
          {busy ? 'Searching…' : 'Search'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {searched && !results.length && !error && <p className="muted">No proteins matched. Try a gene symbol or drop the species.</p>}
      <div className="split">
        <ul className="picks">
          {results.map((p) => (
            <li key={p.accession}>
              <button className={p.accession === selected?.accession ? 'pick active' : 'pick'} onClick={() => onSelect(p)}>
                <strong>{p.name || p.entry}</strong>
                <span>
                  {p.accession}, {p.gene || 'no gene'}, {p.length} aa
                </span>
                <span>
                  <i>{p.organism}</i>
                  {p.alphafold ? `, pLDDT ${p.alphafold.plddt.toFixed(0)}` : ', no AlphaFold model'}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {selected && <StructureViewer pdbUrl={selected.alphafold?.pdb_url ?? null} />}
      </div>
      <div className="actions">
        <button onClick={onNext} disabled={!selected}>
          Use this protein
        </button>
      </div>
    </Card>
  )
}
