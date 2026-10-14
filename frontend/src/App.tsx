import { useState } from 'react'
import { Protein } from './api'
import SearchBox from './components/SearchBox'
import StructureViewer from './components/StructureViewer'
import DockingPanel from './components/DockingPanel'
import AgentChat from './components/AgentChat'

export default function App() {
  const [results, setResults] = useState<Protein[]>([])
  const [selected, setSelected] = useState<Protein | null>(null)

  return (
    <div className="app">
      <header>
        <h1>Bio AI Assistant</h1>
        <p>Pre-screen proteins and compounds before lab work. Scores are heuristic estimates, not docking simulations.</p>
      </header>
      <main>
        <div className="col">
          <SearchBox
            results={results}
            selected={selected?.accession ?? null}
            onResults={(r) => {
              setResults(r)
              setSelected(null)
            }}
            onSelect={setSelected}
          />
        </div>
        <div className="col wide">
          <section className="panel">
            <h2>{selected ? selected.name : 'Structure'}</h2>
            <StructureViewer pdbUrl={selected?.alphafold?.pdb_url ?? null} />
          </section>
          <DockingPanel protein={selected} />
        </div>
        <div className="col">
          <AgentChat />
        </div>
      </main>
    </div>
  )
}
