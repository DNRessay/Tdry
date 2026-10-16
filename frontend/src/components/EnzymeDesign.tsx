import { useState } from 'react'
import { submitEnzyme } from '../api'
import Card from './Card'
import { ResultData } from './Results'

const SUITES = ['', 'kemp_eliminase', 'serine_esterase', 'dehp_esterase', 'carbene_transfer', 'nitrene_transfer']

type Props = { name: string; onBack: () => void; onDone: (r: ResultData) => void }

export default function EnzymeDesign({ name, onBack, onDone }: Props) {
  const [cif, setCif] = useState('')
  const [file, setFile] = useState('')
  const [motif, setMotif] = useState('')
  const [atoms, setAtoms] = useState('')
  const [seqLen, setSeqLen] = useState('')
  const [lig, setLig] = useState('')
  const [chain, setChain] = useState('B')
  const [n, setN] = useState(20)
  const [author, setAuthor] = useState(true)
  const [suite, setSuite] = useState('')
  const [code, setCode] = useState('')
  const [nc, setNc] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const ready = cif && motif.trim() && code && nc && n >= 1 && n <= 300

  async function submit() {
    setBusy(true)
    setError('')
    try {
      const { job_id } = await submitEnzyme({
        name,
        cif,
        motif_str: motif.trim(),
        motif_atoms: atoms.trim(),
        seq_length: seqLen.trim(),
        is_author_naming: author,
        num_designs: n,
        ligands: lig.trim() ? [{ id: chain.trim().toUpperCase(), ccd_code: lig.trim().toUpperCase() }] : [],
        suite,
        access_code: code,
        noncommercial: nc,
      })
      onDone({ kind: 'enzyme', data: { job_id, status: 'queued' } })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card question="Design an enzyme" hint="Give AlphaProtein Novo a CIF with the catalytic residues and the transition-state ligand. A campaign runs on a GPU for hours; progress is saved, so you can close this page." wide onBack={onBack}>
      <label className="field">
        <span>Motif CIF {file && `(${file})`}</span>
        <input
          type="file"
          accept=".cif,.mmcif"
          onChange={async (e) => {
            const f = e.target.files?.[0]
            if (!f) return
            setFile(f.name)
            setCif(await f.text())
          }}
        />
      </label>
      <label className="field">
        <span>Motif string</span>
        <input value={motif} onChange={(e) => setMotif(e.target.value)} placeholder="A1,A2|10-100,{},2-80,{},10-100/B1" />
      </label>
      <label className="field">
        <span>Fixed atoms (optional)</span>
        <input value={atoms} onChange={(e) => setAtoms(e.target.value)} placeholder="A1:OE2,OE1,CD,CG A2:OG,CB,CA" />
      </label>
      <div className="row">
        <label className="field">
          <span>Total length (optional)</span>
          <input value={seqLen} onChange={(e) => setSeqLen(e.target.value)} placeholder="120-160" />
        </label>
        <label className="field">
          <span>Ligand chain</span>
          <input value={chain} maxLength={1} onChange={(e) => setChain(e.target.value)} />
        </label>
        <label className="field">
          <span>Ligand CCD code</span>
          <input value={lig} onChange={(e) => setLig(e.target.value)} placeholder="6NT" />
        </label>
        <label className="field">
          <span>Designs (1-300)</span>
          <input type="number" min={1} max={300} value={n} onChange={(e) => setN(Number(e.target.value))} />
        </label>
      </div>
      <div className="row">
        <label className="field">
          <span>Evaluation suite</span>
          <select value={suite} onChange={(e) => setSuite(e.target.value)}>
            {SUITES.map((s) => (
              <option key={s} value={s}>
                {s || 'none'}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Access code</span>
          <input type="password" value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
      </div>
      <label className="check">
        <input type="checkbox" checked={author} onChange={(e) => setAuthor(e.target.checked)} /> Residue numbers in the CIF are author numbers
      </label>
      <label className="check">
        <input type="checkbox" checked={nc} onChange={(e) => setNc(e.target.checked)} /> I am using this for non-commercial research, for a non-commercial organisation, and not for toxins, pathogens, weapons or controlled substances (AP Novo weights terms).
      </label>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button disabled={busy || !ready} onClick={submit}>
          {busy ? 'Submitting…' : 'Start campaign'}
        </button>
      </div>
    </Card>
  )
}
