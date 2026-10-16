import { useState } from 'react'
import { scorePlantVariants, PlantResult } from '../api'

function parse(text: string) {
  return text
    .split(/[\s,;]+/)
    .filter(Boolean)
    .map((t) => {
      const m = t.match(/^(\d+):?([ACGTacgt])$/)
      if (!m) throw new Error(`Bad variant "${t}". Use position:base, e.g. 251:C`)
      return { pos: Number(m[1]), alt: m[2].toUpperCase() }
    })
}

export default function PlantPanel() {
  const [seq, setSeq] = useState('')
  const [vars, setVars] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [res, setRes] = useState<PlantResult | null>(null)

  async function run() {
    setBusy(true)
    setError('')
    setRes(null)
    try {
      setRes(await scorePlantVariants(seq, parse(vars)))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>Plant variant scoring (BOTANIC-1)</h2>
      <p className="muted">Plant genomic DNA only. Research use only. Not for human, animal or viral sequences.</p>
      <div className="row">
        <textarea value={seq} rows={4} placeholder="Plant DNA window, up to 8,191 bp (A/C/G/T/N)" onChange={(e) => setSeq(e.target.value)} aria-label="Plant DNA sequence" />
      </div>
      <div className="row">
        <input value={vars} placeholder="Variants, 0-based pos:alt e.g. 251:C 155:A" onChange={(e) => setVars(e.target.value)} aria-label="Variants" />
        <button onClick={run} disabled={busy || !seq.trim() || !vars.trim()}>
          {busy ? 'Scoring…' : 'Score'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {res && (
        <div>
          <ul className="results">
            {res.results.map((r) => (
              <li key={`${r.pos}${r.alt}`}>
                {r.pos}: {r.ref}→{r.alt} · LLR {r.llr.toFixed(3)}
              </li>
            ))}
          </ul>
          <p className="muted">{res.interpretation}</p>
        </div>
      )}
    </section>
  )
}
