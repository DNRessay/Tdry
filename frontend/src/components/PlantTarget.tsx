import { useState } from 'react'
import Card from './Card'
import SeqLookup from './SeqLookup'

export const clean = (s: string) => s.replace(/\s+/g, '').toUpperCase()
export const validPlant = (s: string) => s.length > 0 && s.length <= 8191 && !/[^ACGTN]/.test(s)

export default function PlantTarget({ seq, setSeq, onNext, onBack }: { seq: string; setSeq: (s: string) => void; onNext: () => void; onBack: () => void }) {
  const [note, setNote] = useState('')
  const c = clean(seq)
  const bad = c.length > 0 && !validPlant(c)
  return (
    <Card question="Paste the plant DNA" hint="Plant genomic DNA only, up to 8,191 bases. Research use only. Not for human, animal or viral sequences." wide onBack={onBack}>
      <textarea autoFocus rows={6} value={seq} placeholder="ACGT… (A, C, G, T or N)" onChange={(e) => setSeq(e.target.value)} aria-label="Plant DNA sequence" />
      {note && <p className="muted">{note}</p>}
      <SeqLookup
        kind="plantdna"
        onPick={(s, n) => {
          setSeq(s)
          setNote(n)
        }}
      />
      <div className="actions">
        <span className={bad ? 'error' : 'muted'}>
          {bad ? (c.length > 8191 ? 'Too long. Trim to 8,191 bases.' : 'Only A, C, G, T and N are allowed.') : c.length ? `${c.length} bases` : ''}
        </span>
        <button onClick={onNext} disabled={!validPlant(c)}>
          Continue
        </button>
      </div>
    </Card>
  )
}
