import { useState } from "react";
import { EnzymeMode, submitEnzyme } from "../api";
import Card from "./Card";
import { ResultData } from "./Results";

const DEMO_ENABLED = import.meta.env.VITE_ENABLE_DEMO !== "false";
const SUITES = [
  "",
  "kemp_eliminase",
  "serine_esterase",
  "dehp_esterase",
  "carbene_transfer",
  "nitrene_transfer",
];

type Props = {
  name: string;
  onBack: () => void;
  onDone: (r: ResultData) => void;
};

export default function EnzymeDesign({ name, onBack, onDone }: Props) {
  const [mode, setMode] = useState<EnzymeMode>(
    DEMO_ENABLED ? "demo" : "commercial",
  );
  const [unindexed, setUnindexed] = useState(true);
  const [per, setPer] = useState(4);
  const demo = mode === "demo";
  const [cif, setCif] = useState("");
  const [file, setFile] = useState("");
  const [motif, setMotif] = useState("");
  const [atoms, setAtoms] = useState("");
  const [seqLen, setSeqLen] = useState("");
  const [lig, setLig] = useState("");
  const [chain, setChain] = useState("B");
  const [n, setN] = useState(20);
  const [author, setAuthor] = useState(true);
  const [suite, setSuite] = useState("");
  const [code, setCode] = useState("");
  const [nc, setNc] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const ready =
    cif && motif.trim() && code && (nc || !demo) && n >= 1 && n <= 300;

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const { job_id } = await submitEnzyme({
        mode,
        unindexed,
        seqs_per_design: per,
        name,
        cif,
        motif_str: motif.trim(),
        motif_atoms: atoms.trim(),
        seq_length: seqLen.trim(),
        is_author_naming: demo && author,
        num_designs: n,
        ligands: lig.trim()
          ? [
              {
                id: chain.trim().toUpperCase(),
                ccd_code: lig.trim().toUpperCase(),
              },
            ]
          : [],
        suite: demo ? suite : "",
        access_code: code,
        noncommercial: demo && nc,
      });
      onDone({ kind: "enzyme", data: { job_id, mode, status: "queued" } });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      question="Design an enzyme"
      hint={
        demo
          ? "Demo mode: AlphaProtein Novo. Give it a CIF with the catalytic residues and the transition-state ligand. Non-commercial use only."
          : "Commercial mode: RFdiffusion2, LigandMPNN and Boltz. Give it a PDB with the catalytic residues and the ligand. A campaign runs on a GPU for hours; progress is saved, so you can close this page."
      }
      wide
      onBack={onBack}
    >
      <div className="row">
        {DEMO_ENABLED && (
          <button
            className={demo ? "" : "ghost"}
            onClick={() => setMode("demo")}
          >
            Demo (non-commercial)
          </button>
        )}
        <button
          className={demo ? "ghost" : ""}
          onClick={() => setMode("commercial")}
        >
          Commercial
        </button>
      </div>
      <label className="field">
        <span>
          {demo ? "Motif CIF" : "Motif PDB"} {file && `(${file})`}
        </span>
        <input
          type="file"
          accept={demo ? ".cif,.mmcif" : ".pdb"}
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            setFile(f.name);
            setCif(await f.text());
          }}
        />
      </label>
      <label className="field">
        <span>{demo ? "Motif string" : "Contigs"}</span>
        <input
          value={motif}
          onChange={(e) => setMotif(e.target.value)}
          placeholder={
            demo
              ? "A1,A2|10-100,{},2-80,{},10-100/B1"
              : "46,A106-106,59,A166-166,2,A169-169,46"
          }
        />
      </label>
      <label className="field">
        <span>Fixed atoms (optional)</span>
        <input
          value={atoms}
          onChange={(e) => setAtoms(e.target.value)}
          placeholder={
            demo ? "A1:OE2,OE1,CD,CG A2:OG,CB,CA" : "A106:NE,CD,CZ A166:OD1,CG"
          }
        />
      </label>
      <div className="row">
        {demo && (
          <>
            <label className="field">
              <span>Total length (optional)</span>
              <input
                value={seqLen}
                onChange={(e) => setSeqLen(e.target.value)}
                placeholder="120-160"
              />
            </label>
            <label className="field">
              <span>Ligand chain</span>
              <input
                value={chain}
                maxLength={1}
                onChange={(e) => setChain(e.target.value)}
              />
            </label>
          </>
        )}
        <label className="field">
          <span>{demo ? "Ligand CCD code" : "Ligand code(s) in the PDB"}</span>
          <input
            value={lig}
            onChange={(e) => setLig(e.target.value)}
            placeholder="6NT"
          />
        </label>
        <label className="field">
          <span>Designs (1-300)</span>
          <input
            type="number"
            min={1}
            max={300}
            value={n}
            onChange={(e) => setN(Number(e.target.value))}
          />
        </label>
      </div>
      <div className="row">
        {demo ? (
          <label className="field">
            <span>Evaluation suite</span>
            <select value={suite} onChange={(e) => setSuite(e.target.value)}>
              {SUITES.map((s) => (
                <option key={s} value={s}>
                  {s || "none"}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label className="field">
            <span>Sequences per backbone (1-8)</span>
            <input
              type="number"
              min={1}
              max={8}
              value={per}
              onChange={(e) => setPer(Number(e.target.value))}
            />
          </label>
        )}
        <label className="field">
          <span>Access code</span>
          <input
            type="password"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </label>
      </div>
      {demo ? (
        <label className="check">
          <input
            type="checkbox"
            checked={author}
            onChange={(e) => setAuthor(e.target.checked)}
          />{" "}
          Residue numbers in the CIF are author numbers
        </label>
      ) : (
        <label className="check">
          <input
            type="checkbox"
            checked={unindexed}
            onChange={(e) => setUnindexed(e.target.checked)}
          />{" "}
          Unindexed motif (the model chooses where the catalytic residues go)
        </label>
      )}
      {demo && (
        <label className="check">
          <input
            type="checkbox"
            checked={nc}
            onChange={(e) => setNc(e.target.checked)}
          />{" "}
          I am using this for non-commercial research, for a non-commercial
          organisation, and not for toxins, pathogens, weapons or controlled
          substances (AP Novo weights terms).
        </label>
      )}
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button disabled={busy || !ready} onClick={submit}>
          {busy ? "Submitting…" : "Start campaign"}
        </button>
      </div>
    </Card>
  );
}
