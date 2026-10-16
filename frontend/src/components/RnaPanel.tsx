import { useState } from 'react'
import { designRna, RnaResult } from '../api'

export default function RnaPanel() {
  const [seq, setSeq] = useState('')
  const [loops, setLoops] = useState(5)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [res, setRes] = useState<RnaResult | null>(null)

  async function run() {
    setBusy(true)
    setError('')
    setRes(null)
    try {
      setRes(await designRna(seq, loops))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>mRNA binder loop</h2>
      <div className="row">
        <textarea value={seq} rows={4} placeholder="Paste mRNA (A/C/G/U/T)" onChange={(e) => setSeq(e.target.value)} aria-label="mRNA sequence" />
      </div>
      <div className="row">
        <input type="number" min={1} max={10} value={loops} onChange={(e) => setLoops(Number(e.target.value) || 5)} aria-label="Max loops" />
        <button onClick={run} disabled={busy || !seq.trim()}>
          {busy ? 'Running…' : 'Run'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {res && (
        <div>
          <p>
            <b>{res.status}</b> · MFE {res.accessibility.mfe} kcal/mol · {res.accessibility.regions.length} open windows
          </p>
          {res.note && <p className="muted">{res.note}</p>}
          <ul className="results">
            {res.loops.map((l) => (
              <li key={l.loop}>
                Loop {l.loop}: {l.site.motif} {l.site.start}-{l.site.end} ({l.site.seq}), unpaired {l.site.unpaired} → {l.result}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
