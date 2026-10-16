import Card from './Card'

export type Kind = 'protein' | 'mrna' | 'plantdna'

const OPTIONS: { kind: Kind | 'dna'; title: string; text: string; tone: string; soon?: boolean }[] = [
  { kind: 'protein', title: 'Protein', text: 'Pick a protein, see its structure, then score a compound against it.', tone: 'protein' },
  { kind: 'mrna', title: 'mRNA', text: 'Find the open loops in your mRNA and design a protein to hold one.', tone: 'mrna' },
  { kind: 'plantdna', title: 'Plant DNA', text: 'Score which mutations in a plant gene are likely to matter. Plants only.', tone: 'plant' },
  { kind: 'dna', title: 'DNA', text: 'Non-plant DNA. Not available yet.', tone: 'dna', soon: true },
]

function Glyph({ tone }: { tone: string }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 2.4, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  return (
    <svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true">
      {tone === 'protein' && <path {...common} d="M8 34c6-18 10 6 16-10s10 6 16-10M8 40c6-10 10 4 16-4s10 4 16-4" />}
      {tone === 'mrna' && <path {...common} d="M8 36V20a8 8 0 0 1 16 0v16M24 36V28a8 8 0 0 1 16 0v8M8 36h32" />}
      {tone === 'plant' && <path {...common} d="M24 42V22M24 22c0-8 6-12 14-12 0 8-6 12-14 12ZM24 30c0-6-5-9-12-9 0 6 5 9 12 9Z" />}
      {tone === 'dna' && <path {...common} d="M14 8c0 10 20 12 20 22s-20 12-20 10M34 8c0 10-20 12-20 22M17 14h14M17 36h14" />}
    </svg>
  )
}

export default function KindStep({ onPick, onBack }: { onPick: (k: Kind) => void; onBack: () => void }) {
  return (
    <Card question="What are you working with?" hint="Everything after this adapts to your choice." wide onBack={onBack}>
      <div className="kinds">
        {OPTIONS.map((o) => (
          <button
            key={o.kind}
            className={`kind ${o.tone}`}
            disabled={o.soon}
            onClick={() => o.kind !== 'dna' && onPick(o.kind)}
          >
            <Glyph tone={o.tone} />
            <strong>{o.title}</strong>
            <span>{o.text}</span>
          </button>
        ))}
      </div>
    </Card>
  )
}
