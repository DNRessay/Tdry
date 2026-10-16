import { useEffect, useMemo, useState } from 'react'
import { designNovo, designRna, LookupHit, lookupSearch, predictDocking, scorePlantVariants, Protein, RnaSite } from '../api'
import Card from './Card'
import { Kind } from './KindStep'
import { clean } from './PlantTarget'
import { ResultData } from './Results'

type Props = {
  kind: Kind
  protein: Protein | null
  seq: string
  site: RnaSite | null
  onDone: (r: ResultData) => void
  onBack: () => void
}

function parseVariants(text: string, seq: string) {
  const items = text.split(/[\s,;]+/).filter(Boolean)
  return items.map((t) => {
    const m = t.match(/^(\d+):?([ACGTacgt])$/)
    if (!m) return { raw: t, error: 'Use position:base, like 251:C' }
    const pos = Number(m[1])
    const alt = m[2].toUpperCase()
    if (pos >= seq.length) return { raw: t, error: `Position ${pos} is past the end (${seq.length} bases)` }
    if (seq[pos] === alt) return { raw: t, error: `Base ${pos} is already ${alt}` }
    return { raw: t, pos, alt, ref: seq[pos] }
  })
}

export default function Binder({ kind, protein, seq, site, onDone, onBack }: Props) {
  const [compound, setCompound] = useState('')
  const [loops, setLoops] = useState(5)
  const [vtext, setVtext] = useState('')
  const [busy, setBusy] = useState(false)
  const [suggest, setSuggest] = useState<string[]>([])
  const [known, setKnown] = useState<LookupHit[] | null>(null)
  const [error, setError] = useState('')
  const dna = clean(seq)
  const parsed = useMemo(() => parseVariants(vtext, dna), [vtext, dna])
  const goodVariants = parsed.filter((v) => !('error' in v)) as { pos: number; alt: string; ref: string }[]

  useEffect(() => {
    if (kind !== 'protein' || !protein) return
    let stale = false
    lookupSearch('binder', protein.accession)
      .then((r) => !stale && setKnown(r.results))
      .catch(() => !stale && setKnown([]))
    return () => {
      stale = true
    }
  }, [kind, protein])

  useEffect(() => {
    const q = compound.trim()
    if (kind !== 'protein' || q.length < 2) {
      setSuggest([])
      return
    }
    let stale = false
    const timer = setTimeout(() => {
      lookupSearch('compound', q)
        .then((r) => !stale && setSuggest(r.results.map((x) => x.title).filter((n) => n.toLowerCase() !== q.toLowerCase())))
        .catch(() => !stale && setSuggest([]))
    }, 300)
    return () => {
      stale = true
      clearTimeout(timer)
    }
  }, [compound, kind])

  async function go(fn: () => Promise<ResultData>) {
    setBusy(true)
    setError('')
    try {
      onDone(await fn())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (kind === 'protein')
    return (
      <Card question="Which compound should it bind?" hint="Start from a known binder, type a PubChem name or CID, or ask AlphaProtein Novo for a new design. Scores are a quick pre-screen, not physics-based docking." wide onBack={onBack}>
        <h3>Known binders for {protein?.name}</h3>
        {known === null && <p className="muted">Looking up ChEMBL…</p>}
        {known && !known.length && <p className="muted">ChEMBL has no measured binders for this protein. Type a compound below.</p>}
        {known && known.length > 0 && (
          <ul className="picks grid">
            {known.map((k) => (
              <li key={k.id}>
                <button className={compound === k.id ? 'pick active' : 'pick'} onClick={() => setCompound(k.id)}>
                  <strong>{k.title}</strong>
                  <span>{k.detail}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <h3>Or type your own</h3>
        <input
          className="big"
          value={compound.startsWith('smiles:') ? '' : compound}
          placeholder={compound.startsWith('smiles:') ? 'Selected from the list above' : 'e.g. imatinib'}
          onChange={(e) => setCompound(e.target.value)}
          aria-label="Compound"
        />
        <div className="chips">
          {suggest.map((c) => (
            <button key={c} className="chip" onClick={() => setCompound(c)}>
              {c}
            </button>
          ))}
        </div>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button className="ghost" disabled={busy || !compound.trim() || compound.startsWith('smiles:')} onClick={() => go(async () => ({ kind: 'novo', data: await designNovo(compound.trim(), protein?.accession) }))}>
            Design a new one with Novo
          </button>
          <button disabled={busy || !compound.trim() || !protein} onClick={() => go(async () => ({ kind: 'protein', data: await predictDocking(protein!.accession, compound.trim()) }))}>
            {busy ? 'Working…' : 'Score it'}
          </button>
        </div>
      </Card>
    )

  if (kind === 'mrna')
    return (
      <Card question="How many design attempts?" hint={`We try ${site?.motif} first, then move to the next best site if the design fails. It stops at your limit.`} onBack={onBack}>
        <div className="segment" role="group" aria-label="Design attempts">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} className={n === loops ? 'seg on' : 'seg'} onClick={() => setLoops(n)}>
              {n}
            </button>
          ))}
        </div>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button disabled={busy} onClick={() => go(async () => ({ kind: 'mrna', data: await designRna(clean(seq).replace(/T/g, 'U'), loops, site ?? undefined) }))}>
            {busy ? 'Designing…' : 'Design a binder'}
          </button>
        </div>
      </Card>
    )

  return (
    <Card question="Which mutations should we score?" hint="Write each as position:base, counting from 0. Example: 251:C means the base at 251 becomes C." wide onBack={onBack}>
      <input className="big" autoFocus value={vtext} placeholder="251:C 155:A" onChange={(e) => setVtext(e.target.value)} aria-label="Variants" />
      {parsed.length > 0 && (
        <div className="chips">
          {parsed.map((v) =>
            'error' in v ? (
              <span key={v.raw} className="chip bad" title={v.error}>
                {v.raw}: {v.error}
              </span>
            ) : (
              <span key={v.raw} className="chip ok">
                {v.pos} {v.ref} to {v.alt}
              </span>
            ),
          )}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button
          disabled={busy || !goodVariants.length || goodVariants.length !== parsed.length}
          onClick={() => go(async () => ({ kind: 'plantdna', data: await scorePlantVariants(dna, goodVariants.map(({ pos, alt }) => ({ pos, alt }))) }))}
        >
          {busy ? 'Scoring…' : 'Score mutations'}
        </button>
      </div>
    </Card>
  )
}
