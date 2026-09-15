import { useEffect, useState } from 'react'
import { useAuth } from './store/auth'
import { KarmaRing } from './components/KarmaRing'
import { OfflineBanner } from './components/OfflineBanner'
import { IS_NATIVE } from './api/config'
import { Auth } from './routes/Auth'
import { Feed } from './routes/Feed'
import { Book } from './routes/Book'
import { Gigs } from './routes/Gigs'
import { Karma } from './routes/Karma'
import { Profile } from './routes/Profile'
import { Admin } from './routes/Admin'

/**
 * The app shell: a mobile-first single column that becomes a two-pane layout
 * on desktop. Hash routing keeps deployment to a static host trivial.
 *
 * The header karma pill is live — it is the product's thesis, always one tap
 * from its own audit trail.
 */

type Route = 'feed' | 'book' | 'gigs' | 'karma' | 'profile' | 'admin'

const NAV: { id: Route; label: string; glyph: string }[] = [
  { id: 'feed', label: 'Home', glyph: '⌂' },
  { id: 'book', label: 'Post a gig', glyph: '⟡' },
  { id: 'gigs', label: 'Gigs', glyph: '▤' },
  { id: 'karma', label: 'Karma', glyph: '◐' },
  { id: 'profile', label: 'You', glyph: '◉' },
]

// The trust desk joins the bar only for accounts the backend would let through anyway.
const ADMIN_NAV: { id: Route; label: string; glyph: string } = {
  id: 'admin',
  label: 'Trust',
  glyph: '▣',
}

function navFor(user: { capabilities: string[] } | null) {
  return user?.capabilities.includes('admin') ? [...NAV, ADMIN_NAV] : NAV
}

function currentRoute(user: { capabilities: string[] } | null): Route {
  const hash = window.location.hash.replace(/^#\/?/, '').split('?')[0]
  return (navFor(user).find((n) => n.id === hash)?.id ?? 'feed') as Route
}

export function App() {
  const { user, ready, load, logout } = useAuth()
  const [route, setRoute] = useState<Route>(() => currentRoute(null))

  useEffect(() => {
    void load()
    // Native-only: chrome, splash and the hardware back button. The module is imported
    // lazily so the web bundle never ships Capacitor plugins; in a browser tab IS_NATIVE is
    // false and nothing extra is fetched.
    if (IS_NATIVE) void import('./native').then((m) => m.initNativeShell())
  }, [load])

  useEffect(() => {
    const onHash = () => setRoute(currentRoute(user))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [user])

  // The first route resolves before /me returns: re-resolve once the user is known, or an
  // admin who reloaded on #/admin would be parked on the feed while their tab exists.
  useEffect(() => {
    setRoute(currentRoute(user))
  }, [user])

  // Hold the native splash until the first real paint, then let it go.
  useEffect(() => {
    if (ready && IS_NATIVE) void import('./native').then((m) => m.hideSplash())
  }, [ready])

  if (!ready) {
    return (
      <main style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center' }}>
        <KarmaRing value={50} size={56} label="Loading" />
      </main>
    )
  }

  if (!user) return <Auth />

  return (
    <div
      style={{
        minHeight: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        maxWidth: 1080,
        margin: '0 auto',
        width: '100%',
      }}
    >
      <a
        href="#main"
        className="sr-only"
        style={{ position: 'absolute' }}
        onFocus={(e) => {
          e.currentTarget.style.position = 'static'
          e.currentTarget.style.padding = '12px'
        }}
        onBlur={(e) => {
          e.currentTarget.style.position = 'absolute'
        }}
      >
        Skip to content
      </a>

      <OfflineBanner />

      {/* ── Header ────────────────────────────────────────────── */}
      <header
        style={{
          position: 'sticky',
          top: 0,
          // Respect the notch / status-bar inset in standalone PWA and native shells.
          paddingTop: 'env(safe-area-inset-top, 0px)',
          zIndex: 10,
          background: 'rgba(250,250,248,0.92)',
          backdropFilter: 'blur(8px)',
          borderBottom: '1px solid var(--line)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--s3)',
            padding: '10px var(--s4)',
            maxWidth: 'var(--max-w)',
            margin: '0 auto',
            width: '100%',
          }}
        >
          <h1
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 19,
              fontWeight: 700,
              letterSpacing: '-0.02em',
              flex: 1,
            }}
          >
            KARMA
          </h1>

          {/* Live karma — tap for the ledger. */}
          <a
            href="#/karma"
            aria-label={`Your karma is ${user.karma} of 100. View your ledger.`}
            style={{ display: 'flex', alignItems: 'center', gap: 6, textDecoration: 'none' }}
          >
            <KarmaRing value={user.karma} size={34} />
          </a>

          <button
            type="button"
            onClick={logout}
            aria-label="Sign out"
            style={{
              minHeight: 36,
              minWidth: 36,
              border: '1px solid var(--line-strong)',
              borderRadius: 'var(--r-input)',
              background: 'var(--surface)',
              cursor: 'pointer',
              fontSize: 14,
            }}
          >
            ⎋
          </button>
        </div>
      </header>

      {/* ── Main ───────────────────────────────────────────────── */}
      <main
        id="main"
        tabIndex={-1}
        style={{
          flex: 1,
          width: '100%',
          maxWidth: 'var(--max-w)',
          margin: '0 auto',
          padding: 'var(--s4) var(--s4) calc(var(--nav-h) + var(--s5))',
        }}
      >
        {route === 'feed' && <Feed />}
        {route === 'book' && <Book />}
        {route === 'gigs' && <Gigs />}
        {route === 'karma' && <Karma />}
        {route === 'profile' && <Profile />}
        {route === 'admin' && <Admin />}
      </main>

      {/* ── Bottom navigation. The ✚ is the dual-intent surface: ──
          one button, two verbs, no role selection, no wall. */}
      <nav
        aria-label="Primary"
        style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          zIndex: 10,
          background: 'rgba(250,250,248,0.96)',
          backdropFilter: 'blur(8px)',
          borderTop: '1px solid var(--line)',
          paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        }}
      >
        <ul
          style={{
            listStyle: 'none',
            margin: 0,
            padding: '6px var(--s2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-around',
            maxWidth: 'var(--max-w)',
            marginInline: 'auto',
          }}
        >
          {navFor(user).map((item) => {
            const isActive = route === item.id
            const isCreate = item.id === 'book'
            return (
              <li key={item.id} style={{ flex: isCreate ? '0 0 auto' : 1 }}>
                <a
                  href={`#/${item.id}`}
                  aria-current={isActive ? 'page' : undefined}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 2,
                    minHeight: 48,
                    minWidth: 48,
                    padding: isCreate ? 0 : '6px 4px',
                    borderRadius: 'var(--r-input)',
                    textDecoration: 'none',
                    color: isActive ? 'var(--violet)' : 'var(--text-muted)',
                    fontSize: 11,
                    fontWeight: isActive ? 700 : 500,
                  }}
                >
                  {isCreate ? (
                    <span
                      aria-hidden="true"
                      style={{
                        width: 46,
                        height: 46,
                        borderRadius: 'var(--r-pill)',
                        background: isActive ? 'var(--violet-ink)' : 'var(--violet)',
                        color: '#fff',
                        display: 'grid',
                        placeItems: 'center',
                        fontSize: 22,
                        fontWeight: 300,
                        lineHeight: 1,
                      }}
                    >
                      +
                    </span>
                  ) : (
                    <span aria-hidden="true" style={{ fontSize: 20, lineHeight: 1.2 }}>
                      {item.glyph}
                    </span>
                  )}
                  {!isCreate && <span>{item.label}</span>}
                  {isCreate && <span className="sr-only">{item.label}</span>}
                </a>
              </li>
            )
          })}
        </ul>
      </nav>
    </div>
  )
}
