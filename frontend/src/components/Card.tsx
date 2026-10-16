import { ReactNode } from 'react'

type Props = {
  question: string
  hint?: string
  wide?: boolean
  onBack?: () => void
  children: ReactNode
}

export default function Card({ question, hint, wide, onBack, children }: Props) {
  return (
    <section className={wide ? 'card wide' : 'card'}>
      <div className="ask">
        <span className="avatar" aria-hidden="true">T</span>
        <div>
          <h2>{question}</h2>
          {hint && <p className="hint">{hint}</p>}
        </div>
      </div>
      <div className="body">{children}</div>
      {onBack && (
        <button className="link back" onClick={onBack}>
          Back
        </button>
      )}
    </section>
  )
}
