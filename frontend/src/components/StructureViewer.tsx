import { useEffect, useRef, useState } from 'react'
// @ts-ignore
import * as $3Dmol from '3dmol'

const colorFor = (b: number) => (b > 90 ? '#0053D6' : b > 70 ? '#65CBF3' : b > 50 ? '#FFDB13' : '#FF7D45')

export const LEGEND = [
  { color: '#0053D6', label: 'Very high (>90)' },
  { color: '#65CBF3', label: 'Confident (70–90)' },
  { color: '#FFDB13', label: 'Low (50–70)' },
  { color: '#FF7D45', label: 'Very low (<50)' },
]

export default function StructureViewer({ pdbUrl }: { pdbUrl: string | null }) {
  const host = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState('')

  useEffect(() => {
    if (!pdbUrl || !host.current) return
    let cancelled = false
    const viewer = ($3Dmol as any).createViewer(host.current, { backgroundColor: '#14282B' })
    setStatus('Loading structure…')
    fetch(pdbUrl)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.text()
      })
      .then((pdb) => {
        if (cancelled) return
        viewer.addModel(pdb, 'pdb')
        viewer.setStyle({}, { cartoon: { colorfunc: (a: { b: number }) => colorFor(a.b) } })
        viewer.zoomTo()
        viewer.render()
        setStatus('')
      })
      .catch((e) => !cancelled && setStatus(`Could not load structure (${e.message})`))
    return () => {
      cancelled = true
      viewer.clear()
      if (host.current) host.current.innerHTML = ''
    }
  }, [pdbUrl])

  if (!pdbUrl) return <div className="viewer empty">Select a protein with an AlphaFold model to see its structure.</div>

  return (
    <div className="viewer-wrap">
      <div className="viewer" ref={host} />
      {status && <p className="viewer-status">{status}</p>}
      <ul className="legend">
        {LEGEND.map((l) => (
          <li key={l.label}>
            <span style={{ background: l.color }} />
            {l.label}
          </li>
        ))}
      </ul>
    </div>
  )
}
