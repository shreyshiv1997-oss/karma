import type { FareBreakdown as Breakdown } from '../api/types'

/**
 * Transparent pricing, rendered exactly as the backend computed it.
 *
 * Each multiplier animates in as a labelled row when it becomes active, so the
 * total never changes without explaining itself. Figures use tabular numerals
 * so the column does not jitter as values update.
 */

const inr = (value: number) =>
  `₹${value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export function FareBreakdownView({
  fare,
  emphasis = 'total',
}: {
  fare: Breakdown
  emphasis?: 'none' | 'total'
}) {
  const activeMultipliers = [
    { key: 'skill', label: 'Skill tier', value: fare.skill_multiplier, hint: tierHint(fare.skill_multiplier) },
    { key: 'urgency', label: 'Urgent', value: fare.urgency_multiplier, hint: 'same-day dispatch' },
    { key: 'night', label: 'Night (22:00–06:00)', value: fare.night_multiplier, hint: 'out-of-hours' },
  ].filter((m) => m.value !== 1)

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        fontSize: 14.5,
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      <Row label="Base fare" value={inr(fare.base_fare)} />
      <Row label="Distance" value={inr(fare.distance_fare)} />
      <Row label="Time" value={inr(fare.time_fare)} />

      {activeMultipliers.map((m) => (
        <Row
          key={m.key}
          label={m.label}
          value={`×${m.value.toFixed(2)}`}
          accent
          hint={m.hint}
          /* A newly-active multiplier animates in, answering "why did my total change?" */
          animate
        />
      ))}

      <Separator />
      <Row label="Subtotal" value={inr(fare.subtotal)} strong />
      <Row label="Platform fee (15%)" value={inr(fare.platform_fee)} muted />
      <Separator />

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          paddingTop: 2,
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 15,
            fontWeight: 600,
            letterSpacing: '-0.01em',
          }}
        >
          Total
        </span>
        <span
          className="num"
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: emphasis === 'total' ? 24 : 20,
            fontWeight: 700,
            letterSpacing: '-0.02em',
          }}
        >
          {inr(fare.total)}
        </span>
      </div>
    </div>
  )
}

function tierHint(multiplier: number): string {
  if (multiplier >= 1.18) return 'gold tier'
  if (multiplier >= 1.08) return 'silver tier'
  return 'standard tier'
}

function Row({
  label,
  value,
  muted,
  strong,
  accent,
  hint,
  animate,
}: {
  label: string
  value: string
  muted?: boolean
  strong?: boolean
  accent?: boolean
  hint?: string
  animate?: boolean
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        gap: 'var(--s3)',
        animation: animate ? 'rise var(--d-enter) var(--ease)' : undefined,
      }}
    >
      <span style={{ color: muted ? 'var(--text-faint)' : 'var(--text-muted)', fontSize: 14 }}>
        {label}
        {hint && (
          <span style={{ color: 'var(--text-faint)', fontSize: 12.5 }}> · {hint}</span>
        )}
      </span>
      <span
        className="num"
        style={{
          fontWeight: strong ? 600 : accent ? 600 : 400,
          color: accent ? 'var(--karma-gold)' : 'var(--text)',
        }}
      >
        {value}
      </span>
    </div>
  )
}

function Separator() {
  return <div style={{ height: 1, background: 'var(--line)', margin: '4px 0' }} />
}
