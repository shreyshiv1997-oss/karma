import { useOnline } from '../hooks/useOnline'

/**
 * A calm, single-line notice when the network is gone. It never blocks — the cached shell and
 * the last-read data stay usable; this just stops the app from pretending everything is fine.
 */
export function OfflineBanner() {
  const online = useOnline()
  if (online) return null

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        top: 'calc(env(safe-area-inset-top, 0px) + 56px)',
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 30,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 14px',
        borderRadius: 'var(--r-pill)',
        background: 'var(--karma-gold)',
        color: '#fff',
        fontSize: 13,
        fontWeight: 600,
        boxShadow: 'var(--wash)',
        maxWidth: 'calc(100vw - 32px)',
        whiteSpace: 'nowrap',
      }}
    >
      <span aria-hidden="true">⚠</span>
      You're offline — showing what you last loaded
    </div>
  )
}
