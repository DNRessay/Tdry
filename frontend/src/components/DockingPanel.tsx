import { useState } from 'react'
import { Prediction, Protein, predictDocking } from '../api'

export default function DockingPanel({ protein }: { protein: Protein | null }) {
  const [compound, setCompound] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Prediction | null>(null)

  async function run() {
    if (!protein || !compound.trim()) return
    setBusy(true)
    setError('')
    try {
      setResult(await predictDocking(protein.accession, compound.trim()))
    } catch (e) {
      setError((e as Error).message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  const shown = result && protein && result.protein.accession === protein.accession ? result : null

  return (
    <section className="panel">
      <h2>Score a compound</h2>
      <p className="muted">{protein ? `${protein.name} (${protein.accession})` : 'Select a protein first.'}</p>
      <div className="row">
        <input
          value={compound}
          placeholder="Compound name or PubChem CID, e.g. imatinib"
          onChange={(e) => setCompound(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run()}
          disabled={!protein}
          aria-label="Compound"
        />
        <button onClick={run} disabled={busy || !protein || !compound.trim()}>
          {busy ? 'Scoring…' : 'Score'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {shown && (
        <div className="result-card">
          <div className="meters">
            <Meter label="Binding affinity" value={shown.binding_affinity_pct} />
            <Meter label="Structural confidence" value={shown.structural_confidence_pct} />
          </div>
          <p className="recommendation">{shown.recommendation}</p>
          <dl className="facts">
            <dt>Ligand</dt>
            <dd>
              {shown.ligand.query} · CID {shown.ligand.cid} · {shown.ligand.mw.toFixed(1)} Da · logP {shown.ligand.logp}
            </dd>
            <dt>Size fit</dt>
            <dd>{shown.components.size_fit}</dd>
            <dt>Hydrophobic match</dt>
            <dd>{shown.components.hydrophobic_complementarity}</dd>
            <dt>Lipinski violations</dt>
            <dd>{shown.components.lipinski_violations}</dd>
          </dl>
          {shown.similar_screened.length > 0 && (
            <>
              <h3>Similar proteins already screened</h3>
              <ul className="similar">
                {shown.similar_screened.map((s) => (
                  <li key={s.accession}>
                    {s.name} ({s.accession}) · similarity {s.score} · {s.last_compound}: {s.last_affinity_pct}%
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="muted small">{shown.method}</p>
        </div>
      )}
    </section>
  )
}

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <strong>{value}%</strong>
      </div>
      <div className="meter-track" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
        <div className="meter-fill" style={{ width: `${value}%` }} />
      </div>
    </div>
  )
}
