import { useState } from 'react'
import { useAuth } from '../store/auth'
import { ApiError, post } from '../api/client'
import type { OtpSendResponse } from '../api/types'
import { KarmaRing } from '../components/KarmaRing'

/**
 * One form, two entry doors (email or phone) — and crucially, no question
 * asking "are you a customer or a worker?". Capabilities are additive and
 * granted later, so the population is never split at the door.
 *
 * The phone door has two beats: the backend refuses to register a number nobody
 * proved, so a phone identifier first sends an OTP and only then creates the
 * account. Email registrations stay one step.
 */

type Mode = 'login' | 'register'

/** True when the identifier can only be a phone number (mirrors the backend's normaliser). */
const looksLikePhone = (identifier: string) =>
  !identifier.includes('@') && identifier.replace(/\D/g, '').length >= 8

export function Auth() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  const [identifier, setIdentifier] = useState('priya')
  const [password, setPassword] = useState('StrongPass!234')
  const [handle, setHandle] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Phone registrations: the OTP beat. The dev code is only ever shown in dev builds.
  const [otpSent, setOtpSent] = useState(false)
  const [otp, setOtp] = useState('')
  const [devCode, setDevCode] = useState<string | null>(null)

  const phoneRegistration = mode === 'register' && looksLikePhone(identifier)

  const resetOtp = () => {
    setOtpSent(false)
    setOtp('')
    setDevCode(null)
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') {
        await login(identifier.trim(), password)
      } else if (phoneRegistration) {
        if (!otpSent) {
          const sent = await post<OtpSendResponse>('/auth/otp/send', { phone: identifier.trim() })
          setDevCode(sent.dev_otp)
          setOtpSent(true)
        } else {
          // Proof first, account second: /auth/otp/verify flags the number as proven,
          // and registration consumes that flag exactly once.
          await post('/auth/otp/verify', { phone: identifier.trim(), otp: otp.trim() })
          await register({
            handle: handle.trim(),
            display_name: displayName.trim(),
            phone: identifier.trim(),
            password,
            city: 'Indore',
          })
        }
      } else {
        await register({
          handle: handle.trim(),
          display_name: displayName.trim(),
          // An '@' means email; otherwise treat it as a phone number.
          ...(identifier.includes('@')
            ? { email: identifier.trim() }
            : { phone: identifier.trim() }),
          password,
          city: 'Indore',
        })
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main
      style={{
        minHeight: '100dvh',
        display: 'grid',
        placeItems: 'center',
        padding: 'var(--s5)',
        background: 'var(--ink)',
      }}
    >
      <div style={{ width: '100%', maxWidth: 400 }}>
        {/* The wordmark. The gradient here is earned: it is the karma gradient. */}
        <header style={{ textAlign: 'center', marginBottom: 'var(--s6)' }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 'var(--s3)' }}>
            <KarmaRing value={88} size={56} label="KARMA" />
          </div>
          <h1
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 34,
              fontWeight: 700,
              letterSpacing: '-0.03em',
              color: '#fff',
              lineHeight: 1.1,
            }}
          >
            KARMA
          </h1>
          <p style={{ color: '#a5a29a', fontSize: 14.5, marginTop: 6 }}>
            Thou art the work you do.
          </p>
        </header>

        <form
          onSubmit={submit}
          className="card"
          style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}
        >
          <div
            role="tablist"
            aria-label="Sign in or create an account"
            style={{ display: 'flex', gap: 4, background: 'var(--surface-2)', padding: 4, borderRadius: 'var(--r-input)' }}
          >
            {(['login', 'register'] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => {
                  setMode(m)
                  setError(null)
                  resetOtp()
                }}
                style={{
                  flex: 1,
                  minHeight: 38,
                  border: 'none',
                  borderRadius: 6,
                  background: mode === m ? 'var(--surface)' : 'transparent',
                  fontWeight: 600,
                  fontSize: 14,
                  cursor: 'pointer',
                  color: mode === m ? 'var(--text)' : 'var(--text-muted)',
                  transition: 'background-color var(--d-state) var(--ease)',
                }}
              >
                {m === 'login' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </div>

          {mode === 'register' && (
            <>
              <div className="field">
                <label htmlFor="handle">Handle</label>
                <input
                  id="handle"
                  value={handle}
                  onChange={(e) => setHandle(e.target.value)}
                  placeholder="yourname"
                  pattern="[a-z0-9_.]{3,30}"
                  title="3–30 characters: lowercase letters, numbers, dot or underscore"
                  required
                  autoComplete="username"
                />
              </div>
              <div className="field">
                <label htmlFor="name">Name</label>
                <input
                  id="name"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Priya Malviya"
                  required
                  autoComplete="name"
                />
              </div>
            </>
          )}

          <div className="field">
            <label htmlFor="identifier">{mode === 'login' ? 'Handle, email or phone' : 'Email or phone'}</label>
            <input
              id="identifier"
              value={identifier}
              onChange={(e) => {
                setIdentifier(e.target.value)
                // A new number means the code already sent no longer proves anything.
                resetOtp()
              }}
              placeholder="priya  ·  priya@example.com  ·  9876500001"
              required
              autoComplete="username"
            />
          </div>

          {phoneRegistration && otpSent && (
            <div className="field">
              <label htmlFor="reg-otp">Code sent to {identifier.trim()}</label>
              <input
                id="reg-otp"
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="6-digit code"
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
                required
                minLength={4}
                maxLength={8}
              />
              {devCode && (
                <p role="note" style={{ fontSize: 12.5, color: 'var(--text-faint)' }}>
                  Development build — the code is <code className="num">{devCode}</code>.
                </p>
              )}
            </div>
          )}

          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </div>

          {error && (
            <p role="alert" style={{ color: 'var(--rose)', fontSize: 14, fontWeight: 500 }}>
              {error}
            </p>
          )}

          <button type="submit" className="btn btn-primary" disabled={busy} style={{ width: '100%' }}>
            {busy
              ? 'Working…'
              : mode === 'login'
                ? 'Sign in'
                : phoneRegistration
                  ? otpSent
                    ? 'Verify & create account'
                    : 'Send verification code'
                  : 'Create account'}
          </button>

          <p style={{ fontSize: 12.5, color: 'var(--text-faint)', textAlign: 'center', lineHeight: 1.5 }}>
            Demo: <code>priya</code> / <code>StrongPass!234</code>
            <br />
            Worker: <code>ramesh.electric</code> / <code>StrongPass!234</code>
          </p>
        </form>
      </div>
    </main>
  )
}
