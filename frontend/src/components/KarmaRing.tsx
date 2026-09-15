import { useEffect, useRef, useState } from 'react'

/**
 * The Karma Ring — the product's thesis rendered as ~50 lines of SVG.
 *
 * It is not a badge. It is a conic progress ring that fills as you earn and
 * changes hue along the karma gradient defined in the design manifesto:
 *
 *   0 ─────── 40 ─────── 70 ─────── 100
 *  rose ──── amber ──── lime ──── karma-gold
 *  dormant   building    trusted    proven
 *
 * Accessibility: the numeric value is the accessible content, exposed via
 * role="img" with a label. The ring itself is decorative.
 */

const SIZE = 44
const STROKE = 4
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

export function karmaHue(value: number): string {
  if (value >= 85) return 'var(--karma-proven)'
  if (value >= 70) return 'var(--karma-trusted)'
  if (value >= 40) return 'var(--karma-building)'
  return 'var(--karma-dormant)'
}

export function karmaBand(value: number): string {
  if (value >= 85) return 'proven'
  if (value >= 70) return 'trusted'
  if (value >= 40) return 'building'
  return 'dormant'
}

type Props = {
  value: number
  size?: number
  /** When set, a `+N` floats up and the number counts — a karma event just landed. */
  celebrate?: number | null
  label?: string
}

export function KarmaRing({ value, size = SIZE, celebrate = null, label }: Props) {
  const clamped = Math.max(0, Math.min(100, value))
  const [shown, setShown] = useState(clamped)
  const [pulse, setPulse] = useState(false)
  const previous = useRef(clamped)

  // Count-animate on change. transform/opacity only — never layout properties.
  useEffect(() => {
    const from = previous.current
    const to = clamped
    previous.current = to
    if (from === to) return

    setPulse(true)
    const timeout = window.setTimeout(() => setPulse(false), 320)

    const duration = 320
    const start = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setShown(Math.round(from + (to - from) * eased))
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)

    return () => {
      window.clearTimeout(timeout)
      cancelAnimationFrame(frame)
    }
  }, [clamped])

  // The arc is driven by `shown`, the same eased value the number reads, not by `clamped`.
  // Reading `clamped` here made the figure count up while the ring snapped to its final angle
  // one frame earlier -- two halves of one animation disagreeing, in the one component whose
  // whole job is to make a number feel earned. Because requestAnimationFrame already supplies
  // each intermediate value, there is deliberately no CSS transition on the dash: layering one
  // on top of the rAF ramp would ease an easing and lag the number it is meant to match. (The
  // property named here used to be `stroke-dashoffset`, which this circle never sets, so the
  // transition never applied to anything.)
  const dash = (shown / 100) * CIRCUMFERENCE
  const hue = karmaHue(clamped)
  const px = size
  const stroke = size < 40 ? 3 : STROKE

  return (
    <span
      className="karma-ring"
      style={{ position: 'relative', display: 'inline-flex', width: px, height: px }}
    >
      <svg
        width={px}
        height={px}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={label ?? `Karma ${clamped} of 100 — ${karmaBand(clamped)}`}
        style={{ transform: pulse ? 'scale(1.12)' : 'scale(1)', transition: 'transform 320ms var(--ease)' }}
      >
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="var(--line)"
          strokeWidth={stroke}
        />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke={hue}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${CIRCUMFERENCE}`}
          transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          style={{ transition: 'stroke 320ms var(--ease)' }}
        />
      </svg>

      <span
        className="num"
        style={{
          position: 'absolute',
          inset: 0,
          display: 'grid',
          placeItems: 'center',
          fontSize: px < 40 ? 12 : 13,
          fontWeight: 700,
          color: hue,
          letterSpacing: '-0.02em',
        }}
      >
        {shown}
      </span>

      {celebrate !== null && celebrate !== 0 && (
        <span
          aria-hidden="true"
          style={{
            position: 'absolute',
            left: '50%',
            top: -4,
            transform: 'translateX(-50%)',
            fontSize: 12,
            fontWeight: 700,
            color: celebrate > 0 ? 'var(--lime)' : 'var(--rose)',
            animation: 'float-up 900ms var(--ease) forwards',
            pointerEvents: 'none',
          }}
        >
          {celebrate > 0 ? `+${celebrate}` : celebrate}
        </span>
      )}
    </span>
  )
}
