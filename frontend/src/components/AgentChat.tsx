import { useEffect, useRef, useState } from 'react'
import { AgentStep, ChatMessage, chat } from '../api'

type Turn = ChatMessage & { steps?: AgentStep[] }

export default function AgentChat() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => end.current?.scrollIntoView({ block: 'nearest' }), [turns, busy])

  async function send() {
    const text = input.trim()
    if (!text || busy) return
    const next: Turn[] = [...turns, { role: 'user', content: text }]
    setTurns(next)
    setInput('')
    setBusy(true)
    setError('')
    try {
      const { reply, steps } = await chat(next.map(({ role, content }) => ({ role, content })))
      setTurns([...next, { role: 'assistant', content: reply, steps }])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel chat">
      <h2>Ask the agent</h2>
      <div className="log">
        {!turns.length && <p className="muted">Try: “Find human JAK3 and score tofacitinib against it.”</p>}
        {turns.map((t, i) => (
          <div key={i} className={`turn ${t.role}`}>
            <p>{t.content}</p>
            {t.steps && t.steps.length > 0 && (
              <p className="muted small">
                Used {t.steps.map((s) => (s.error ? `${s.tool} (failed)` : s.tool)).join(', ')}
              </p>
            )}
          </div>
        ))}
        {busy && <p className="muted">Working…</p>}
        {error && <p className="error">{error}</p>}
        <div ref={end} />
      </div>
      <div className="row">
        <input
          value={input}
          placeholder="Ask about a target or compound"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          aria-label="Message"
        />
        <button onClick={send} disabled={busy || !input.trim()}>
          Send
        </button>
      </div>
    </section>
  )
}
