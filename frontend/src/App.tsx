import { useState } from 'react'
import { Protein, RnaAnalysis, RnaSite } from './api'
import NameStep from './components/NameStep'
import KindStep, { Kind } from './components/KindStep'
import ProteinTarget from './components/ProteinTarget'
import MrnaTarget from './components/MrnaTarget'
import PlantTarget from './components/PlantTarget'
import Binder from './components/Binder'
import Results, { ResultData } from './components/Results'
import AgentChat from './components/AgentChat'

const KIND_LABEL: Record<Kind, string> = { protein: 'Protein', mrna: 'mRNA', plantdna: 'Plant DNA' }
const STEPS = ['Name', 'Target', 'Details', 'Binder', 'Results']

export default function App() {
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [kind, setKind] = useState<Kind | null>(null)
  const [protein, setProtein] = useState<Protein | null>(null)
  const [seq, setSeq] = useState('')
  const [analysis, setAnalysis] = useState<RnaAnalysis | null>(null)
  const [site, setSite] = useState<RnaSite | null>(null)
  const [result, setResult] = useState<ResultData | null>(null)
  const [chat, setChat] = useState(false)

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
  }
  const detail =
    kind === 'protein' ? protein?.name : kind === 'mrna' ? (site ? `${site.motif} site` : '') : kind === 'plantdna' && seq ? 'sequence added' : ''

  return (
    <div className="shell">
      <header>
        <span className="brand">T-Dry-Lab</span>
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
        {step === 3 && kind && (
          <Binder
            kind={kind}
            protein={protein}
            seq={seq}
            site={site}
            onBack={back}
            onDone={(r) => {
              setResult(r)
              setStep(4)
            }}
          />
        )}
        {step === 4 && result && <Results name={name} result={result} protein={protein} onBack={back} onAsk={() => setChat(true)} onRestart={restart} />}
      </main>

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
