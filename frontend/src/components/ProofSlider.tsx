import { useCallback, useRef, useState } from 'react'

/**
 * The Proof Slider — the component that justifies the merger.
 *
 * A completed, *paid* gig produces before/after evidence. Dragging the handle
 * wipes between them, making a stranger's competence visceral in a way a star
 * rating never can.
 *
 * It is also unfakeable by construction: the backend only publishes `kind=proof`
 * for a gig whose payment_status is `paid`.
 *
 * Accessibility:
 *   - role="slider" with aria-valuenow/min/max and a readable label
 *   - operable with the arrow keys (10% steps), Home and End
 *   - pointer-driven for mouse, touch and pen via pointer events
 *   - the before/after text labels mean a screen reader user loses nothing
 */

type Props = {
  beforeUrl: string
  afterUrl: string
  beforeLabel?: string
  afterLabel?: string
  height?: number
}

const STEP = 10

export function ProofSlider({
  beforeUrl,
  afterUrl,
  beforeLabel = 'Before',
  afterLabel = 'After',
  height = 240,
}: Props) {
  const [position, setPosition] = useState(50)
  const [dragging, setDragging] = useState(false)
  const frameRef = useRef<HTMLDivElement>(null)

  const applyFromClientX = useCallback((clientX: number) => {
    const rect = frameRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0) return
    const pct = ((clientX - rect.left) / rect.width) * 100
    setPosition(Math.max(0, Math.min(100, pct)))
  }, [])

  const onPointerDown = (event: React.PointerEvent) => {
    // Capture so the drag survives the pointer leaving the element.
    event.currentTarget.setPointerCapture(event.pointerId)
    setDragging(true)
    applyFromClientX(event.clientX)
  }

  const onPointerMove = (event: React.PointerEvent) => {
    if (!dragging) return
    applyFromClientX(event.clientX)
  }

  const endDrag = (event: React.PointerEvent) => {
    setDragging(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    const map: Record<string, number> = {
      ArrowLeft: -STEP,
      ArrowDown: -STEP,
      ArrowRight: STEP,
      ArrowUp: STEP,
      Home: -100,
      End: 100,
    }
    const delta = map[event.key]
    if (delta === undefined) return
    event.preventDefault()
    setPosition((current) =>
      delta === -100 ? 0 : delta === 100 ? 100 : Math.max(0, Math.min(100, current + delta)),
    )
  }

  const showingAfter = Math.round(position)

  return (
    <div
      ref={frameRef}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
      role="slider"
      tabIndex={0}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={showingAfter}
      aria-valuetext={`${showingAfter}% ${afterLabel.toLowerCase()}, ${100 - showingAfter}% ${beforeLabel.toLowerCase()}`}
      aria-label={`Compare ${beforeLabel.toLowerCase()} and ${afterLabel.toLowerCase()}. Use arrow keys to wipe.`}
      style={{
        position: 'relative',
        height,
        borderRadius: 'var(--r-card)',
        overflow: 'hidden',
        border: '1px solid var(--line)',
        background: 'var(--surface-2)',
        cursor: dragging ? 'grabbing' : 'ew-resize',
        touchAction: 'none', // let us own the horizontal gesture
        userSelect: 'none',
      }}
    >
      {/* AFTER is the base layer; BEFORE is clipped from the left. */}
      <img
        src={afterUrl}
        alt={afterLabel}
        draggable={false}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          width: `${position}%`,
          overflow: 'hidden',
        }}
      >
        <img
          src={beforeUrl}
          alt={beforeLabel}
          draggable={false}
          style={{
            position: 'absolute',
            inset: 0,
            width: frameRef.current?.clientWidth ?? '100%',
            maxWidth: 'none',
            height: '100%',
            objectFit: 'cover',
          }}
        />
      </div>

      {/* Labels: always present, so the information is never image-only. */}
      <span style={labelStyle('left')}>{beforeLabel}</span>
      <span style={labelStyle('right')}>{afterLabel}</span>

      {/* The handle. */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: `${position}%`,
          width: 2,
          background: '#fff',
          boxShadow: '0 0 0 1px rgba(11,11,15,0.15)',
          transform: dragging ? 'scaleX(1.5)' : 'none',
          transition: 'transform var(--d-state) var(--ease)',
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            width: 34,
            height: 34,
            transform: 'translate(-50%, -50%)',
            borderRadius: 'var(--r-pill)',
            background: '#fff',
            border: '1px solid var(--line-strong)',
            display: 'grid',
            placeItems: 'center',
            color: 'var(--text-muted)',
            fontSize: 14,
            fontWeight: 700,
            letterSpacing: '-0.06em',
          }}
        >
          ⇔
        </span>
      </div>
    </div>
  )
}

function labelStyle(side: 'left' | 'right'): React.CSSProperties {
  return {
    position: 'absolute',
    bottom: 10,
    [side]: 10,
    padding: '2px 8px',
    borderRadius: 'var(--r-pill)',
    background: 'rgba(11,11,15,0.72)',
    color: '#fff',
    fontSize: 11.5,
    fontWeight: 700,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
    pointerEvents: 'none',
  } as React.CSSProperties
}
