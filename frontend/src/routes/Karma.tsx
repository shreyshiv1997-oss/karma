import { useEffect, useState } from 'react'
import { get } from '../api/client'
import type { KarmaLedger } from '../api/types'
import { KarmaRing, karmaBand, karmaHue } from '../components/KarmaRing'
import { useAuth } from '../store/auth'

/**
 * The Karma Ledger — the audit trail behind the number.
 *
 * The split view is the honesty mechanism: you can see that social popularity
 * is not the same as work reputation, and exactly how the two blend. That is
 * the UI answer to "can I farm social karma to get hired?" — no, and here is
 * why, in public.
 */

const DOMAIN_LABEL: Record<string, string> = {
  trust: 'Trust',
  work: 'Work',
  social: 'Social',
  migration: 'Migration',
}

const DOMAIN_COLOR: Record<string, string> = {
  trust: 'var(--karma-gold)',
  work: 'var(--lime)',
  social: 'var(--violet)',
  migration: 'var(--text-faint)',
}

export function Karma() {
  const { user } = useAuth()
  const [ledger, setLedger] = useState<KarmaLedger | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    get<KarmaLedger>('/karma/ledger')
      .then(setLedger)
      .catch((err: Error) => setError(err.message))
  }, [])

  if (error) {
    return (
      <p role="alert" style={{ color: 'var(--rose)' }}>
        {error}
      </p>
    )
  }

  if (!ledger) {
    return <div className="skeleton" style={{ height: 320, borderRadius: 'var(--r-card)' }} />
  }

  const band = karmaBand(ledger.blended)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      <header className="card" style={{ padding: 'var(--s5)', textAlign: 'center' }}>
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 'var(--s3)' }}>
          <KarmaRing value={ledger.blended} size={88} label={`Karma ${ledger.blended} of 100, ${band}`} />
        </div>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 22, letterSpacing: '-0.02em' }}>
          {band.charAt(0).toUpperCase() + band.slice(1)}
        </h1>
        <p style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 4 }}>
          {user?.display_name} · @{user?.handle}
        </p>
      </header>

      {/* The split — marketplace trust and social reputation, shown separately. */}
      <section className="card" style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
        <h2 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          How it blends
        </h2>
        <Meter label="Work karma" value={ledger.work} weight="60%" color="var(--lime)" />
        <Meter label="Social karma" value={ledger.social} weight="40%" color="var(--violet)" />
        <div style={{ height: 1, background: 'var(--line)' }} />
        <Meter label="Blended" value={ledger.blended} weight="" color={karmaHue(ledger.blended)} strong />
        <p style={{ fontSize: 12.5, color: 'var(--text-faint)', lineHeight: 1.5 }}>
          Work is weighted higher than social, because trusting someone in your home should
          depend on their work record — not on how popular they are.
        </p>
      </section>

      {/* The ledger itself. Append-only, filterable, auditable. */}
      <section className="card" style={{ padding: 'var(--s5)' }}>
        <h2 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 'var(--s3)' }}>
          Ledger · {ledger.total_events} event{ledger.total_events === 1 ? '' : 's'}
        </h2>
        <ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column' }}>
          {ledger.events.map((event) => (
            <li
              key={event.id}
              style={{
                display: 'flex',
                gap: 'var(--s3)',
                alignItems: 'baseline',
                padding: '10px 0',
                borderBottom: '1px solid var(--line)',
              }}
            >
              <span
                className="num"
                style={{
                  width: 38,
                  flexShrink: 0,
                  fontWeight: 700,
                  fontSize: 14,
                  color: event.delta > 0 ? 'var(--lime)' : event.delta < 0 ? 'var(--rose)' : 'var(--text-faint)',
                }}
              >
                {event.delta > 0 ? `+${event.delta}` : event.delta}
              </span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ fontSize: 14.5 }}>{event.reason}</span>
                <span style={{ display: 'block', fontSize: 12, color: 'var(--text-faint)' }}>
                  <span style={{ color: DOMAIN_COLOR[event.domain] }}>{DOMAIN_LABEL[event.domain] ?? event.domain}</span>
                  {' · '}
                  {new Date(event.created_at).toLocaleDateString('en-IN', {
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric',
                  })}
                </span>
              </span>
            </li>
          ))}
          {ledger.truncated && (
            <li style={{ color: 'var(--text-faint)', fontSize: 12.5, padding: 'var(--s3) 0 0' }}>
              Showing the {ledger.events.length} most recent of {ledger.total_events}.
            </li>
          )}
          {ledger.total_events === 0 && (
            <li style={{ color: 'var(--text-muted)', padding: 'var(--s4) 0' }}>
              No events yet. Verify your phone to earn your first karma.
            </li>
          )}
        </ol>
      </section>
    </div>
  )
}

function Meter({
  label,
  value,
  weight,
  color,
  strong,
}: {
  label: string
  value: number
  weight: string
  color: string
  strong?: boolean
}) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 5 }}>
        <span style={{ fontSize: 14, fontWeight: strong ? 600 : 400 }}>
          {label}
          {weight && <span style={{ color: 'var(--text-faint)', fontSize: 12.5 }}> · {weight} of blend</span>}
        </span>
        <span className="num" style={{ fontWeight: 700, fontFamily: 'var(--font-display)', fontSize: strong ? 20 : 16, color }}>
          {value}
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${value} of 100`}
        style={{ height: strong ? 8 : 6, background: 'var(--surface-2)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}
      >
        <div
          style={{
            height: '100%',
            width: `${Math.max(0, Math.min(100, value))}%`,
            background: color,
            borderRadius: 'var(--r-pill)',
            transition: 'width var(--d-celebrate) var(--ease)',
          }}
        />
      </div>
    </div>
  )
}
