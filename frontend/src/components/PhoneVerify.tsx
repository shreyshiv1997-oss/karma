import { useState } from 'react'
import { ApiError, post } from '../api/client'
import type { OtpSendResponse, User } from '../api/types'

/**
 * Prove a phone number by OTP and bind it to the signed-in account.
 *
 * This is the second door to "verified contact": accounts that registered with an
 * email meet the `can_hire` requirement here instead. In development builds the
 * backend returns the code in the response, so the flow stays demoable without an
 * SMS provider; the helper text only ever renders when that field is present.
 */

type Stage = 'enter' | 'code' | 'done'

export function PhoneVerify({
  reason = 'Verify a phone number to continue.',
  onVerified,
}: {
  reason?: string
  onVerified: (user: User) => void | Promise<void>
}) {
  const [stage, setStage] = useState<Stage>('enter')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [devCode, setDevCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const sent = await post<OtpSendResponse>('/auth/otp/send', { phone: phone.trim() })
      setDevCode(sent.dev_otp)
      setStage('code')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not send the code.')
    } finally {
      setBusy(false)
    }
  }

  const verify = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const user = await post<User>('/auth/phone/verify', { phone: phone.trim(), otp: code.trim() })
      setStage('done')
      await onVerified(user)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'That code did not work.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      aria-label="Phone verification"
      style={{
        padding: 'var(--s4)',
        background: 'var(--surface)',
        border: '1px solid var(--violet)',
        borderRadius: 'var(--r-input)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--s3)',
      }}
    >
      <h2 style={{ fontSize: 14, fontWeight: 700 }}>Verify your phone</h2>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>{reason}</p>

      {stage === 'enter' && (
        <form onSubmit={send} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
          <div className="field">
            <label htmlFor="otp-phone">Phone number</label>
            <input
              id="otp-phone"
              inputMode="tel"
              autoComplete="tel"
              placeholder="98765 00001"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              required
              minLength={8}
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={busy} style={{ width: '100%' }}>
            {busy ? 'Sending…' : 'Send code'}
          </button>
        </form>
      )}

      {stage === 'code' && (
        <form onSubmit={verify} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
          <div className="field">
            <label htmlFor="otp-code">Code sent to {phone}</label>
            <input
              id="otp-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="6-digit code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              minLength={4}
              maxLength={8}
            />
          </div>
          {devCode && (
            <p role="note" style={{ fontSize: 12.5, color: 'var(--text-faint)' }}>
              Development build — the code is <code className="num">{devCode}</code>.
            </p>
          )}
          <div style={{ display: 'flex', gap: 'var(--s2)' }}>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setStage('enter')
                setCode('')
                setError(null)
              }}
              disabled={busy}
            >
              Back
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy} style={{ flex: 1 }}>
              {busy ? 'Verifying…' : 'Verify & continue'}
            </button>
          </div>
        </form>
      )}

      {error && (
        <p role="alert" style={{ color: 'var(--rose)', fontSize: 13.5, fontWeight: 500 }}>
          {error}
        </p>
      )}
    </section>
  )
}
