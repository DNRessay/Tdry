import { useMemo, useState } from 'react'
import { analyzeRna, RnaAnalysis, RnaSite } from '../api'
import Card from './Card'
import SeqLookup from './SeqLookup'

type Props = {
  seq: string
  setSeq: (s: string) => void
  analysis: RnaAnalysis | null
  setAnalysis: (a: RnaAnalysis | null) => void
  site: RnaSite | null
  setSite: (s: RnaSite) => void
  onNext: () => void
  onBack: () => void
}

function Track({ seq, analysis, site }: { seq: string; analysis: RnaAnalysis; site: RnaSite | null }) {
  const open = useMemo(() => {
    const a = new Array(seq.length).fill(0)
    for (const r of analysis.accessibility.regions)
      for (let i = r.start - 1; i < r.end && i < a.length; i++) a[i] = Math.max(a[i], r.unpaired)
    return a
  }, [seq, analysis])
  return (
    <svg className="track" viewBox={`0 0 ${seq.length} 24`} preserveAspectRatio="none" role="img" aria-label="Open and closed regions along the mRNA">
      {open.map((v, i) => (
        <rect key={i} x={i} y={4} width={1.05} height={16} className={v ? 'open' : 'shut'} style={v ? { opacity: 0.35 + 0.65 * v } : undefined} />
      ))}
      {site && <rect x={site.start - 1} y={0} width={Math.max(site.end - site.start + 1, 2)} height={24} className="mark" />}
    </svg>
  )
}

export default function MrnaTarget({ seq, setSeq, analysis, setAnalysis, site, setSite, onNext, onBack }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const clean = seq.replace(/\s+/g, '').toUpperCase().replace(/T/g, 'U')

  async function run() {
    setBusy(true)
    setError('')
    setAnalysis(null)
    try {
      setAnalysis(await analyzeRna(clean))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card question="Paste your mRNA" hint="A binder can only grip RNA that is open, so we check the folding first." wide onBack={onBack}>
      <textarea
        autoFocus
        rows={4}
        value={seq}
        placeholder="AUGUUU… (A, C, G, U or T, 10 to 2,000 bases)"
        onChange={(e) => {
          setSeq(e.target.value)
          setAnalysis(null)
        }}
        aria-label="mRNA sequence"
      />
      <div className="actions">
        <span className="muted">{clean.length ? `${clean.length} bases` : ''}</span>
        <button onClick={run} disabled={busy || clean.length < 10}>
          {busy ? 'Checking folding…' : 'Check folding'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {note && <p className="muted">{note}</p>}
      <SeqLookup
        kind="mrna"
        onPick={(s, n) => {
          setSeq(s)
          setAnalysis(null)
          setNote(n)
        }}
      />
      {analysis && (
        <>
          <p className="muted">
            Folding energy {analysis.accessibility.mfe} kcal/mol. {analysis.accessibility.regions.length} open windows. Bright stretches are open, grey are folded shut.
          </p>
          <Track seq={clean} analysis={analysis} site={site} />
          {analysis.motifs.length ? (
            <>
              <h3>Pick a motif to target</h3>
              <ul className="picks grid">
                {analysis.motifs.slice(0, 12).map((m) => {
                  const on = site?.motif === m.motif && site.start === m.start
                  return (
                    <li key={`${m.motif}${m.start}`}>
                      <button className={on ? 'pick active' : 'pick'} onClick={() => setSite(m)}>
                        <strong>{m.motif}</strong>
                        <span>
                          Bases {m.start} to {m.end}, {m.seq}
                        </span>
                        <span>{Math.round(m.unpaired * 100)}% open</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </>
          ) : (
            <p className="error">
              {analysis.accessibility.regions.length
                ? 'There are open stretches, but none match a known RNA-binding motif.'
                : 'This mRNA is folded shut everywhere, so no protein could bind it. Try a different region.'}
            </p>
          )}
        </>
      )}
      <div className="actions">
        <button onClick={onNext} disabled={!site}>
          Use this motif
        </button>
      </div>
    </Card>
  )
}
