import { useState } from 'react'
import type { Candidate } from '../api/types'
import { KarmaRing } from './KarmaRing'

/**
 * The Match Card — explainability as design.
 *
 * Every ranked worker arrives with human-readable `reasons[]` from the backend
 * scorer. They are shown verbatim, never paraphrased, because "never show a
 * number you cannot justify" is the product's whole strategy.
 *
 * The fusion addition is the proof strip: the worker's actual completed work,
 * pulled from the social graph. That strip is the two products shaking hands.
 */

type Props = {
  candidate: Candidate
  onBook?: (candidate: Candidate) => void
  onMessage?: (candidate: Candidate) => void
  booked?: boolean
  busy?: boolean
}

export function MatchCard({ candidate, onBook, onMessage, booked, busy }: Props) {
  const [expanded, setExpanded] = useState(false)

  return (
    <article
      className="card"
      style={{ padding: 'var(--s4)', display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}
    >
      <header style={{ display: 'flex', gap: 'var(--s3)', alignItems: 'center' }}>
        <Avatar name={candidate.display_name} url={candidate.avatar_url} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <h3
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 16,
                fontWeight: 600,
                lineHeight: 1.3,
              }}
            >
              {candidate.display_name}
            </h3>
            <TierBadge tier={candidate.verification_tier} />
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            <span className="num">{candidate.total_jobs}</span> jobs · ★{' '}
            <span className="num">{candidate.rating.toFixed(1)}</span> ·{' '}
            <span className="num">{candidate.distance_km}</span> km · ETA{' '}
            <span className="num">{candidate.eta_minutes}</span> min
          </p>
        </div>

        <div style={{ textAlign: 'center', flexShrink: 0 }}>
          <KarmaRing value={candidate.karma} size={40} label={`${candidate.display_name}, karma ${candidate.karma}`} />
          <div style={{ fontSize: 10.5, color: 'var(--text-faint)', marginTop: 2 }}>
            <span className="num">{candidate.score.toFixed(0)}</span> match
          </div>
        </div>
      </header>

      {/* Why this match — the explainability contract. */}
      <div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls={`reasons-${candidate.user_id}`}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            background: 'none',
            border: 'none',
            padding: '4px 0',
            cursor: 'pointer',
            fontSize: 12.5,
            fontWeight: 600,
            color: 'var(--text-muted)',
            letterSpacing: '0.02em',
            textTransform: 'uppercase',
          }}
        >
          <span aria-hidden="true" style={{ transform: expanded ? 'rotate(90deg)' : 'none', transition: 'transform var(--d-state) var(--ease)', display: 'inline-block' }}>
            ›
          </span>
          Why this match
        </button>

        {expanded && (
          <ul
            id={`reasons-${candidate.user_id}`}
            style={{
              listStyle: 'none',
              padding: 0,
              margin: '4px 0 0',
              display: 'flex',
              flexDirection: 'column',
              gap: 3,
            }}
          >
            {candidate.reasons.map((reason) => (
              <li key={reason} style={{ fontSize: 14, color: 'var(--text)', display: 'flex', gap: 6 }}>
                <span aria-hidden="true" style={{ color: 'var(--lime)', flexShrink: 0 }}>
                  ✓
                </span>
                {reason}
              </li>
            ))}
          </ul>
        )}
      </div>

      {candidate.proof_count > 0 && (
        <p style={{ fontSize: 12.5, color: 'var(--text-faint)' }}>
          <span className="num">{candidate.proof_count}</span> verified proof
          {candidate.proof_count === 1 ? '' : 's'} of work on profile
        </p>
      )}

      <div style={{ display: 'flex', gap: 'var(--s2)' }}>
        {onMessage && (
          <button type="button" className="btn btn-ghost" style={{ flex: 1 }} onClick={() => onMessage(candidate)}>
            Message
          </button>
        )}
        {onBook && (
          <button
            type="button"
            className="btn btn-primary"
            style={{ flex: 1 }}
            onClick={() => onBook(candidate)}
            disabled={booked || busy}
          >
            {booked ? 'Booked ✓' : 'Book now'}
          </button>
        )}
      </div>
    </article>
  )
}

export function TierBadge({ tier }: { tier: string }) {
  const label = tier === 'gold' ? 'Gold verified' : tier === 'silver' ? 'Silver verified' : 'Verified'
  const glyph = tier === 'gold' ? '◆' : tier === 'silver' ? '◇' : '○'
  return (
    <span className={`pill tier-${tier}`}>
      <span aria-hidden="true">{glyph}</span>
      {label}
    </span>
  )
}

export function Avatar({ name, url, size = 44 }: { name: string; url: string | null; size?: number }) {
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()

  if (url) {
    return (
      <img
        src={url}
        alt=""
        aria-hidden="true"
        style={{ width: size, height: size, borderRadius: 'var(--r-pill)', objectFit: 'cover', flexShrink: 0 }}
      />
    )
  }

  return (
    <span
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: 'var(--r-pill)',
        background: 'var(--surface-2)',
        border: '1px solid var(--line)',
        display: 'grid',
        placeItems: 'center',
        fontSize: size * 0.36,
        fontWeight: 700,
        color: 'var(--text-muted)',
        fontFamily: 'var(--font-display)',
        flexShrink: 0,
      }}
    >
      {initials}
    </span>
  )
}
