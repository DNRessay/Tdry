import { useState } from 'react'
import { EnzymeJob, Protein, RnaAnalysis, RnaSite } from './api'
import NameStep from './components/NameStep'
import KindStep, { Kind } from './components/KindStep'
import ProteinTarget from './components/ProteinTarget'
import MrnaTarget from './components/MrnaTarget'
import PlantTarget from './components/PlantTarget'
import Binder from './components/Binder'
import EnzymeDesign from './components/EnzymeDesign'
import Results, { ResultData } from './components/Results'
import AgentChat from './components/AgentChat'
import { KIND_LABEL, SavedProject, loadProjects, newId, persist } from './store'

const STEPS = ['Name', 'Target', 'Details', 'Binder', 'Results']

function summarize(r: ResultData, protein: Protein | null, site: RnaSite | null): string {
  if (r.kind === 'protein') return `${protein?.name ?? 'Protein'} vs ${r.data.ligand.query}, affinity ${r.data.binding_affinity_pct}%`
  if (r.kind === 'enzyme') return r.data.status === 'done' ? `${r.data.designs?.length ?? 0} enzyme designs` : `Enzyme campaign, ${r.data.status}`
  if (r.kind === 'mrna') return `${site?.motif ?? 'mRNA'} site, ${r.data.status.replace(/_/g, ' ')}`
  return `${r.data.results.length} mutations scored`
}

export default function App() {
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [kind, setKind] = useState<Kind | null>(null)
  const [protein, setProtein] = useState<Protein | null>(null)
  const [seq, setSeq] = useState('')
  const [analysis, setAnalysis] = useState<RnaAnalysis | null>(null)
  const [site, setSite] = useState<RnaSite | null>(null)
  const [result, setResult] = useState<ResultData | null>(null)
  const [enzymeMode, setEnzymeMode] = useState(false)
  const [chat, setChat] = useState(false)
  const [history, setHistory] = useState(false)
  const [projects, setProjects] = useState<SavedProject[]>(loadProjects)
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [viewing, setViewing] = useState<SavedProject | null>(null)

  const back = () => setStep((s) => Math.max(0, s - 1))
  const restart = () => {
    setStep(0)
    setName('')
    setKind(null)
    setProtein(null)
    setSeq('')
    setAnalysis(null)
    setSite(null)
    setResult(null)
    setCurrentId(null)
    setViewing(null)
    setChat(false)
    setHistory(false)
    setEnzymeMode(false)
  }

  function finish(r: ResultData) {
    const id = currentId ?? newId()
    const prev = projects.find((p) => p.id === id)
    const saved: SavedProject = {
      id,
      name,
      kind: r.kind === 'enzyme' ? 'enzyme' : kind!,
      createdAt: prev?.createdAt ?? Date.now(),
      protein: protein ? { ...protein, sequence: undefined } as SavedProject['protein'] : null,
      summary: summarize(r, protein, site),
      result: r,
    }
    setProjects(persist([saved, ...projects.filter((p) => p.id !== id)]))
    setCurrentId(id)
    setResult(r)
    setStep(4)
  }

  function open(p: SavedProject) {
    setViewing(p)
    setCurrentId(p.id)
    setName(p.name)
    setResult(p.result)
    setKind(p.kind === 'enzyme' ? 'protein' : p.kind)
    setProtein(p.protein ? ({ ...p.protein, sequence: '' } as Protein) : null)
    setStep(4)
    setHistory(false)
    setChat(false)
  }

  function updateEnzyme(d: EnzymeJob) {
    const r: ResultData = { kind: 'enzyme', data: d }
    setResult(r)
    setProjects((prev) => persist(prev.map((p) => (p.result.kind === 'enzyme' && p.result.data.job_id === d.job_id ? { ...p, result: r, summary: summarize(r, null, null) } : p))))
  }

  function remove(id: string) {
    setProjects(persist(projects.filter((p) => p.id !== id)))
    if (id === currentId) restart()
  }

  const detail =
    kind === 'protein' ? protein?.name : kind === 'mrna' ? (site ? `${site.motif} site` : '') : kind === 'plantdna' && seq ? 'sequence added' : ''
  const shown = viewing ?? (result ? { createdAt: projects.find((p) => p.id === currentId)?.createdAt ?? Date.now() } : null)

  return (
    <div className="shell">
      <header>
        <div className="brandrow">
          <span className="brand">T-Dry-Lab</span>
          <button className="link" onClick={() => setHistory(true)}>
            Past projects{projects.length ? ` (${projects.length})` : ''}
          </button>
        </div>
        <ol className="steps" aria-label="Progress">
          {STEPS.map((s, i) => (
            <li key={s} className={i === step ? 'now' : i < step ? 'done' : ''} aria-current={i === step ? 'step' : undefined}>
              {s}
            </li>
          ))}
        </ol>
      </header>

      {step > 0 && (
        <div className="said">
          <span>{name}</span>
          {kind && <span>{KIND_LABEL[kind]}</span>}
          {step > 2 && detail && <span>{detail}</span>}
        </div>
      )}

      <main key={step}>
        {step === 0 && (
          <NameStep
            initial={name}
            onNext={(n) => {
              setName(n)
              setStep(1)
            }}
          />
        )}
        {step === 1 && (
          <KindStep
            onBack={back}
            onPick={(k) => {
              setKind(k)
              setStep(2)
            }}
          />
        )}
        {step === 2 && kind === 'protein' && <ProteinTarget selected={protein} onSelect={setProtein} onNext={() => setStep(3)} onBack={back} />}
        {step === 2 && kind === 'mrna' && (
          <MrnaTarget seq={seq} setSeq={setSeq} analysis={analysis} setAnalysis={setAnalysis} site={site} setSite={setSite} onNext={() => setStep(3)} onBack={back} />
        )}
        {step === 2 && kind === 'plantdna' && <PlantTarget seq={seq} setSeq={setSeq} onNext={() => setStep(3)} onBack={back} />}
        {step === 3 && kind && enzymeMode && <EnzymeDesign name={name} onBack={() => setEnzymeMode(false)} onDone={finish} />}
        {step === 3 && kind && !enzymeMode && <Binder kind={kind} protein={protein} seq={seq} site={site} onBack={back} onDone={finish} onEnzyme={() => setEnzymeMode(true)} />}
        {step === 4 && result && shown && (
          <Results name={name} result={result} protein={protein} createdAt={shown.createdAt} onBack={viewing ? undefined : back} onAsk={() => setChat(true)} onRestart={restart} onEnzymeUpdate={updateEnzyme} />
        )}
      </main>

      {history && (
        <aside className="history" aria-label="Past projects">
          <div className="drawer-head">
            <h3>Past projects</h3>
            <button className="link" onClick={() => setHistory(false)}>
              Close
            </button>
          </div>
          <button className="newbtn" onClick={restart}>
            New project
          </button>
          {!projects.length && <p className="muted">Nothing here yet. Finished projects are saved on this device and show up here.</p>}
          <ul className="plain">
            {projects.map((p) => (
              <li key={p.id} className={p.id === currentId ? 'hist active' : 'hist'}>
                <button className="histopen" onClick={() => open(p)}>
                  <strong>{p.name}</strong>
                  <span>
                    {KIND_LABEL[p.kind]}, {new Date(p.createdAt).toLocaleDateString()}
                  </span>
                  <span>{p.summary}</span>
                </button>
                <button className="link" onClick={() => remove(p.id)} aria-label={`Delete ${p.name}`}>
                  Delete
                </button>
              </li>
            ))}
          </ul>
        </aside>
      )}

      {chat && (
        <aside className="drawer" aria-label="Assistant">
          <button className="link close" onClick={() => setChat(false)}>
            Close
          </button>
          <AgentChat />
        </aside>
      )}
    </div>
  )
}
