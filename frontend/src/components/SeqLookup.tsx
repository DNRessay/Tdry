import { useState } from 'react'
import { LookupHit, lookupFetch, lookupSearch } from '../api'

type Props = { kind: 'mrna' | 'plantdna'; onPick: (sequence: string, note: string) => void }

const COPY = {
  mrna: { title: 'No sequence at hand? Search NCBI RefSeq', placeholder: 'Gene name, e.g. PUM1' },
  plantdna: { title: 'No sequence at hand? Search NCBI plant genes', placeholder: 'Plant gene, e.g. PHYB' },
}

export default function SeqLookup({ kind, onPick }: Props) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<LookupHit[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)

  async function search() {
    if (!q.trim()) return
    setBusy('search')
    setError('')
    try {
      setHits((await lookupSearch(kind, q.trim())).results)
      setSearched(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  async function pick(h: LookupHit) {
    setBusy(h.id)
    setError('')
    try {
      const s = await lookupFetch(kind, h.id)
      onPick(s.sequence, s.truncated ? `${s.label}: using the first ${s.sequence.length} of ${s.length} bases.` : `${s.label}: ${s.length} bases loaded.`)
      setHits([])
      setSearched(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="lookup">
      <h3>{COPY[kind].title}</h3>
      <div className="row">
        <input value={q} placeholder={COPY[kind].placeholder} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} aria-label="Database search" className="big" />
        <button onClick={search} disabled={!!busy || !q.trim()}>
          {busy === 'search' ? 'Searching…' : 'Search'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {searched && !hits.length && !error && <p className="muted">Nothing found. Try the official gene symbol.</p>}
      <ul className="picks">
        {hits.map((h) => (
          <li key={h.id}>
            <button className="pick" disabled={!!busy} onClick={() => pick(h)}>
              <strong>{h.title}</strong>
              <span>
                <i>{h.organism}</i>
                {h.length ? `, ${h.length.toLocaleString()} bases` : ''}
              </span>
              {busy === h.id && <span>Loading sequence…</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
