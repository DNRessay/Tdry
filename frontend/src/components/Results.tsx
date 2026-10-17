import { EnzymeJob, PlantResult, Prediction, Protein, RnaResult } from '../api'
import Card from './Card'
import StructureViewer from './StructureViewer'
import EnzymeResults from './EnzymeResults'

export type ResultData =
  | { kind: 'protein'; data: Prediction }
  | { kind: 'mrna'; data: RnaResult }
  | { kind: 'plantdna'; data: PlantResult }
  | { kind: 'enzyme'; data: EnzymeJob }

type Props = { name: string; result: ResultData; protein: Protein | Omit<Protein, 'sequence'> | null; createdAt: number; onBack?: () => void; onAsk: () => void; onRestart: () => void; onEnzymeUpdate: (d: EnzymeJob) => void }

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

const RNA_HEADLINE: Record<RnaResult['status'], string> = {
  success: 'A binder passed all checks.',
  exhausted: 'No design passed within your attempts.',
  needs_compute: 'Your mRNA is ready. Binder design needs your compute services.',
  failed_inaccessible: 'This mRNA is folded shut, so nothing can bind it.',
  failed_no_motif: 'No known binding motif sits in an open stretch.',
}

export default function Results({ name, result, protein, createdAt, onBack, onAsk, onRestart, onEnzymeUpdate }: Props) {
  return (
    <Card question={`Results for ${name}`} wide onBack={onBack}>
      <p className="print-head">
        T-Dry-Lab, {new Date(createdAt).toLocaleString()}
        {protein ? `, target ${protein.name} (${protein.accession})` : ''}
      </p>
      {result.kind === 'protein' && (
        <>
          <div className="meters">
            <Meter label="Binding affinity" value={result.data.binding_affinity_pct} />
            <Meter label="Structural confidence" value={result.data.structural_confidence_pct} />
          </div>
          <p className="verdict">{result.data.recommendation}</p>
          <p className="muted">
            {result.data.ligand.query} (CID {result.data.ligand.cid}), {result.data.ligand.mw.toFixed(1)} Da, logP {result.data.ligand.logp}. Lipinski violations: {result.data.components.lipinski_violations}.
          </p>
          {protein?.alphafold?.pdb_url && <StructureViewer pdbUrl={protein.alphafold.pdb_url} />}
          {result.data.similar_screened.length > 0 && (
            <>
              <h3>Similar proteins already screened</h3>
              <ul className="plain">
                {result.data.similar_screened.map((s) => (
                  <li key={s.accession}>
                    {s.name} ({s.accession}), similarity {s.score}, {s.last_compound} scored {s.last_affinity_pct}%
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="muted small">{result.data.method}</p>
        </>
      )}
      {result.kind === 'mrna' && (
        <>
          <p className="verdict">{RNA_HEADLINE[result.data.status]}</p>
          {result.data.note && <p className="muted">{result.data.note}</p>}
          <ul className="plain rows">
            {result.data.loops.map((l) => (
              <li key={l.loop}>
                <span>
                  Attempt {l.loop}: {l.site.motif}, bases {l.site.start} to {l.site.end}
                </span>
                <span className={`chip ${l.result === 'pass' ? 'ok' : l.result === 'fail' ? 'bad' : ''}`}>{l.result}</span>
              </li>
            ))}
          </ul>
          {result.data.winner?.sequence && <textarea readOnly rows={3} value={result.data.winner.sequence} aria-label="Winning protein sequence" />}
        </>
      )}
      {result.kind === 'enzyme' && <EnzymeResults data={result.data} onUpdate={onEnzymeUpdate} />}
      {result.kind === 'plantdna' && (
        <>
          <p className="verdict">Most disruptive mutations first.</p>
          <ul className="plain rows">
            {result.data.results.map((r) => {
              const max = Math.max(...result.data.results.map((x) => Math.abs(x.llr)), 0.001)
              return (
                <li key={`${r.pos}${r.alt}`}>
                  <span>
                    {r.pos}: {r.ref} to {r.alt}
                  </span>
                  <span className="bar">
                    <i style={{ width: `${(Math.abs(r.llr) / max) * 100}%` }} className={r.llr < 0 ? 'neg' : 'pos'} />
                  </span>
                  <strong>{r.llr.toFixed(2)}</strong>
                </li>
              )
            })}
          </ul>
          <p className="muted small">{result.data.interpretation}</p>
          <p className="muted small">{result.data.notice}</p>
        </>
      )}
      <div className="actions">
        <button className="ghost" onClick={() => window.print()}>
          Print results
        </button>
        <button className="ghost" onClick={onAsk}>
          Ask the assistant
        </button>
        <button onClick={onRestart}>New project</button>
      </div>
    </Card>
  )
}
