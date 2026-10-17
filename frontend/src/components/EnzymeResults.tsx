import { useEffect, useRef, useState } from 'react'
import { enzymeFile, enzymeStatus, EnzymeJob, resumeEnzyme } from '../api'

type Props = { data: EnzymeJob; onUpdate: (d: EnzymeJob) => void }

const HEADLINE: Record<EnzymeJob['status'], string> = {
  queued: 'Queued for a GPU.',
  running: 'Campaign running.',
  done: 'Campaign finished.',
  error: 'The run hit an error. Progress so far is saved.',
  stalled: 'No sign of life from the GPU job. Progress so far is saved.',
}

export default function EnzymeResults({ data, onUpdate }: Props) {
  const [err, setErr] = useState('')
  const cb = useRef(onUpdate)
  cb.current = onUpdate

  useEffect(() => {
    if (data.status === 'done') return
    let stop = false
    const tick = () =>
      enzymeStatus(data.job_id)
        .then((d) => !stop && cb.current(d))
        .catch((e) => !stop && setErr((e as Error).message))
    tick()
    const t = setInterval(tick, 20000)
    return () => {
      stop = true
      clearInterval(t)
    }
  }, [data.job_id, data.status === 'done'])

  const c = data.counts ?? {}
  const designs = data.designs ?? []

  return (
    <>
      <p className="verdict">{HEADLINE[data.status]}</p>
      {data.mode && <p className="muted small">{data.mode === 'commercial' ? 'Commercial mode: RFdiffusion2 + LigandMPNN + Boltz' : 'Demo mode: AlphaProtein Novo (non-commercial)'}</p>}
      {data.status !== 'done' && (
        <p className="muted">
          Stage: {data.stage ?? 'starting'}. Generated {c.generated ?? 0}/{data.total ?? '?'}, resequenced {c.resequenced ?? 0}, folded {c.folded ?? 0}, evaluated {c.evaluated ?? 0}. Everything is saved to S3 as it goes.
        </p>
      )}
      {data.error && <p className="error">{data.error}</p>}
      {err && <p className="muted small">{err}</p>}
      {(data.status === 'error' || data.status === 'stalled') && (
        <div className="actions">
          <button
            onClick={() =>
              resumeEnzyme(data.job_id)
                .then((d) => cb.current(d))
                .catch((e) => setErr((e as Error).message))
            }
          >
            Resume from saved progress
          </button>
        </div>
      )}
      {data.status === 'done' && (
        <>
          <ul className="plain">
            {designs.map((d, i) => (
              <li key={d.name}>
                <strong>
                  #{i + 1} {d.name}
                </strong>
                <span className="muted"> score {d.score}</span>
                <p className="muted small">
                  {Object.entries(d.metrics)
                    .filter(([, v]) => typeof v === 'number')
                    .slice(0, 6)
                    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`)
                    .join(' · ')}
                </p>
                {d.sequence && <textarea readOnly rows={3} value={d.sequence} aria-label={`Sequence ${d.name}`} />}
                <div className="chips">
                  {d.files.map((f) => (
                    <button
                      key={f.key}
                      className="chip"
                      onClick={() =>
                        enzymeFile(data.job_id, f.key)
                          .then((r) => window.open(r.url, '_blank'))
                          .catch((e) => setErr((e as Error).message))
                      }
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          {data.notice && <p className="muted small">{data.notice}</p>}
        </>
      )}
    </>
  )
}
