import { useState } from 'react'
import Card from './Card'

export default function NameStep({ initial, onNext }: { initial: string; onNext: (name: string) => void }) {
  const [name, setName] = useState(initial)
  const ok = name.trim().length > 0
  return (
    <Card question="What do you want to call this project?">
      <input
        className="big"
        autoFocus
        value={name}
        maxLength={60}
        placeholder="e.g. Marula leaf pilot"
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && ok && onNext(name.trim())}
        aria-label="Project name"
      />
      <div className="actions">
        <button onClick={() => onNext(name.trim())} disabled={!ok}>
          Continue
        </button>
      </div>
    </Card>
  )
}
