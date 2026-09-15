import { Elements, PaymentElement, useElements, useStripe } from '@stripe/react-stripe-js'
import { loadStripe } from '@stripe/stripe-js'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, get, post } from '../api/client'
import { subscribeToGig } from '../api/realtime'
import type { Gig, GigPayment, Stats } from '../api/types'
import { useAuth } from '../store/auth'

/**
 * Gigs — the state machine made visible.
 *
 * The lifecycle rail shows where the work actually is, and the worker drives
 * their own transitions. The SOS control is deliberately unanimated: red,
 * present, instant. Animation in an emergency would be grotesque.
 *
 * The active gig is watched over a WebSocket, so the other party's transitions
 * arrive as they happen rather than on the next reload. Polling is not used as
 * a fallback timer: if the socket is down the last known state is simply shown.
 */

const RAIL = [
  'assigned',
  'en_route',
  'arrived',
  'in_progress',
  'completion_pending',
  'completed',
] as const

const STATUSES = [
  'searching',
  'assigned',
  'en_route',
  'arrived',
  'in_progress',
  'completion_pending',
  'completed',
  'cancelled',
] as const

type GigStatus = (typeof STATUSES)[number]

/**
 * Narrow an untrusted status string coming off the wire.
 *
 * A cast would satisfy the compiler and then put a nonsense value into state. Ignoring an
 * unknown status is strictly safer: the rail falls back to the last state it trusts.
 */
function asGigStatus(value: unknown): GigStatus | null {
  return typeof value === 'string' && (STATUSES as readonly string[]).includes(value)
    ? (value as GigStatus)
    : null
}

const WORKER_NEXT: Partial<Record<GigStatus, GigStatus>> = {
  assigned: 'en_route',
  en_route: 'arrived',
  arrived: 'in_progress',
  in_progress: 'completion_pending',
}

const LABELS: Record<string, string> = {
  searching: 'Searching',
  assigned: 'Assigned',
  en_route: 'On the way',
  arrived: 'Arrived',
  in_progress: 'Working',
  completion_pending: 'Awaiting approval',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

export function Gigs() {
  const { user } = useAuth()
  const [role, setRole] = useState<'customer' | 'worker'>('customer')
  const [gigs, setGigs] = useState<Gig[] | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [checkout, setCheckout] = useState<GigPayment | null>(null)
  const [sosSent, setSosSent] = useState(false)
  const [linkState, setLinkState] = useState<'connecting' | 'live' | 'closed'>('closed')

  const isWorker = !!user?.capabilities?.includes('can_work')

  const load = () => {
    get<Gig[]>(`/gigs/mine?role=${role}`)
      .then(setGigs)
      .catch((err: Error) => setError(err.message))
    get<Stats>('/gigs/stats/summary')
      .then(setStats)
      .catch(() => undefined)
  }

  useEffect(load, [role])

  const active = gigs?.find((g) => !['completed', 'cancelled'].includes(g.status))
  const activeId = active?.id ?? null

  // Keep the latest updater in a ref so the subscription effect does not have to
  // re-subscribe every time the list changes.
  const setGigsRef = useRef(setGigs)
  setGigsRef.current = setGigs

  useEffect(() => {
    if (activeId === null) {
      setLinkState('closed')
      return
    }

    const subscription = subscribeToGig(activeId, {
      onStateChange: setLinkState,
      onSnapshot: (event) => {
        // Adopt the server's view on connect: it may have moved while we were away.
        const status = asGigStatus(event.data.status)
        const payment = typeof event.data.payment_status === 'string' ? event.data.payment_status : undefined
        if (!status) return
        setGigsRef.current((current) =>
          current?.map((g) =>
            g.id === activeId
              ? { ...g, status, payment_status: payment ?? g.payment_status }
              : g,
          ) ?? null,
        )
      },
      onEvent: (event) => {
        const status = asGigStatus(event.data.status)
        if (!status) return
        setGigsRef.current((current) =>
          current?.map((g) =>
            g.id === event.gig_id
              ? {
                  ...g,
                  status,
                  payment_status:
                    (typeof event.data.payment_status === 'string'
                      ? event.data.payment_status
                      : undefined) ?? g.payment_status,
                }
              : g,
          ) ?? null,
        )
        // A completed gig publishes proof and moves karma, so the surrounding
        // numbers need refreshing -- the push tells us *that* it happened, not
        // every consequence of it.
        if (status === 'completed' || event.type === 'gig.reviewed') load()
      },
    })

    return subscription.close
  }, [activeId])

  const advance = async (gig: Gig) => {
    const next = WORKER_NEXT[gig.status]
    if (!next) return
    setBusyId(gig.id)
    setError(null)
    try {
      const updated = await post<Gig>(`/gigs/${gig.id}/status`, { status: next })
      setGigs((current) => current?.map((g) => (g.id === gig.id ? updated : g)) ?? null)
      if (next === 'completion_pending') load()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not update the gig.')
    } finally {
      setBusyId(null)
    }
  }

  const securePayment = async (gig: Gig) => {
    setBusyId(gig.id)
    setError(null)
    try {
      const payment = await post<GigPayment>(`/payments/gigs/${gig.id}/intent`)
      if (isSecuredPayment(payment.status)) {
        load()
      } else if (payment.client_secret && payment.publishable_key) {
        setCheckout(payment)
      } else {
        setError('Stripe payment setup is incomplete. Please try again.')
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not secure the payment.')
    } finally {
      setBusyId(null)
    }
  }

  const releasePayment = async (gig: Gig) => {
    if (
      !window.confirm(
        `Approve the completed work and capture ₹${Number(gig.total).toLocaleString('en-IN')}?`,
      )
    ) {
      return
    }
    setBusyId(gig.id)
    setError(null)
    try {
      await post<GigPayment>(`/payments/gigs/${gig.id}/release`)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not release the payment.')
    } finally {
      setBusyId(null)
    }
  }

  const paymentConfirmed = async () => {
    setCheckout(null)
    load()
  }

  const sos = async (gig: Gig | null) => {
    setError(null)
    try {
      await post('/safety/emergency', { gig_id: gig?.id ?? null })
      setSosSent(true)
      window.setTimeout(() => setSosSent(false), 4000)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not send the signal.')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)', flexWrap: 'wrap' }}>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 24, letterSpacing: '-0.02em', flex: 1 }}>
          Gigs
        </h1>
        {isWorker && (
          <div role="group" aria-label="View as" style={{ display: 'flex', gap: 4, background: 'var(--surface-2)', padding: 3, borderRadius: 'var(--r-input)' }}>
            {(['customer', 'worker'] as const).map((r) => (
              <button
                key={r}
                type="button"
                aria-pressed={role === r}
                onClick={() => setRole(r)}
                style={{
                  minHeight: 32,
                  padding: '4px 12px',
                  border: 'none',
                  borderRadius: 6,
                  background: role === r ? 'var(--surface)' : 'transparent',
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: 'pointer',
                }}
              >
                {r === 'customer' ? 'Hiring' : 'Working'}
              </button>
            ))}
          </div>
        )}
      </header>

      {stats && (
        <div className="card" style={{ padding: 'var(--s4)', display: 'flex', gap: 'var(--s5)', flexWrap: 'wrap' }}>
          <Stat label="Completed" value={stats.gigs_completed} />
          <Stat label="Wallet" value={`₹${stats.wallet_balance.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} />
          <Stat label="Lifetime earned" value={`₹${stats.lifetime_earned.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} />
        </div>
      )}

      {error && (
        <p role="alert" style={{ color: 'var(--rose)', fontWeight: 500 }}>
          {error}
        </p>
      )}

      {sosSent && (
        <p role="status" style={{ color: 'var(--lime)', fontWeight: 600 }}>
          Emergency signal sent to your trusted contacts and the safety team.
        </p>
      )}

      {checkout?.client_secret && checkout.publishable_key && (
        <StripePaymentPanel
          payment={checkout}
          onConfirmed={paymentConfirmed}
          onClose={() => setCheckout(null)}
        />
      )}

      {/* The active gig gets the live view. */}
      {role === 'worker' && active && (
        <section className="card" style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--s3)', flexWrap: 'wrap' }}>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 17, flex: 1 }}>{active.title}</h2>
            <LiveLink state={linkState} />
          </div>
          <LifecycleRail status={active.status} />
          <div style={{ display: 'flex', gap: 'var(--s2)' }}>
            <button
              type="button"
              className="btn btn-primary"
              style={{ flex: 1 }}
              onClick={() => advance(active)}
              disabled={
                busyId === active.id ||
                !WORKER_NEXT[active.status] ||
                (active.status === 'assigned' && !isSecuredPayment(active.payment_status))
              }
            >
              {busyId === active.id
                ? 'Updating…'
                : active.status === 'assigned' && !isSecuredPayment(active.payment_status)
                  ? 'Waiting for secured payment'
                  : nextLabel(active.status)}
            </button>
            {/* SOS: no animation, no confirmation. Friction is the enemy here. */}
            <button
              type="button"
              className="btn btn-danger"
              style={{ minWidth: 64, minHeight: 48, fontWeight: 700 }}
              onClick={() => sos(active)}
            >
              ⚠ SOS
            </button>
          </div>
        </section>
      )}

      {gigs === null && !error && (
        <div className="skeleton" style={{ height: 120, borderRadius: 'var(--r-card)' }} />
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
        {gigs?.map((gig) => (
          <article key={gig.id} className="card" style={{ padding: 'var(--s4)' }}>
            <div style={{ display: 'flex', gap: 'var(--s3)', alignItems: 'baseline', flexWrap: 'wrap' }}>
              <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 16, flex: 1 }}>{gig.title}</h3>
              <StatusPill status={gig.status} />
            </div>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>
              {gig.address_label || 'Location unavailable'} · gig #{gig.id} ·{' '}
              <span className="num">₹{Number(gig.total).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
              {' · '}
              <PaymentLabel status={gig.payment_status} />
            </p>

            {role === 'worker' && WORKER_NEXT[gig.status] && (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ marginTop: 'var(--s3)', width: '100%' }}
                onClick={() => advance(gig)}
                disabled={
                  busyId === gig.id ||
                  (gig.status === 'assigned' && !isSecuredPayment(gig.payment_status))
                }
              >
                {gig.status === 'assigned' && !isSecuredPayment(gig.payment_status)
                  ? 'Waiting for secured payment'
                  : nextLabel(gig.status)}
              </button>
            )}

            {role === 'worker' && gig.status === 'completion_pending' && (
              <p role="status" style={{ marginTop: 'var(--s3)', color: 'var(--gold)', fontSize: 13 }}>
                Proof submitted · waiting for customer approval
              </p>
            )}

            {role === 'customer' &&
              gig.status === 'assigned' &&
              !isSecuredPayment(gig.payment_status) && (
                <button
                  type="button"
                  className="btn btn-primary"
                  style={{ marginTop: 'var(--s3)', width: '100%' }}
                  onClick={() => securePayment(gig)}
                  disabled={busyId === gig.id}
                >
                  {busyId === gig.id
                    ? 'Preparing Stripe…'
                    : `Secure ₹${Number(gig.total).toLocaleString('en-IN')}`}
                </button>
              )}

            {role === 'customer' && gig.status === 'completion_pending' && (
              <button
                type="button"
                className="btn btn-primary"
                style={{ marginTop: 'var(--s3)', width: '100%' }}
                onClick={() => releasePayment(gig)}
                disabled={busyId === gig.id}
              >
                {busyId === gig.id ? 'Releasing…' : 'Approve work & release payment'}
              </button>
            )}

            {role === 'customer' && gig.status === 'completed' && (
              <ReviewForm gigId={gig.id} />
            )}
          </article>
        ))}

        {gigs?.length === 0 && (
          <p style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 'var(--s7) 0' }}>
            No gigs yet.{' '}
            <a href="#/book" style={{ color: 'var(--violet)', fontWeight: 600 }}>
              Post one
            </a>
            .
          </p>
        )}
      </div>
    </div>
  )
}

function StripePaymentPanel({
  payment,
  onConfirmed,
  onClose,
}: {
  payment: GigPayment
  onConfirmed: () => Promise<void>
  onClose: () => void
}) {
  const stripe = useMemo(
    () => loadStripe(payment.publishable_key as string),
    [payment.publishable_key],
  )
  return (
    <section
      className="card"
      aria-labelledby="stripe-payment-title"
      style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
        <div style={{ flex: 1 }}>
          <h2 id="stripe-payment-title" style={{ fontFamily: 'var(--font-display)', fontSize: 18 }}>
            Secure payment
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
            ₹{Number(payment.amount).toLocaleString('en-IN')} · captured only after work approval
          </p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close payment form">
          Close
        </button>
      </div>
      <Elements
        stripe={stripe}
        options={{
          clientSecret: payment.client_secret as string,
          appearance: { theme: 'stripe' },
        }}
      >
        <StripePaymentForm gigId={payment.gig_id} onConfirmed={onConfirmed} />
      </Elements>
    </section>
  )
}

function StripePaymentForm({
  gigId,
  onConfirmed,
}: {
  gigId: number
  onConfirmed: () => Promise<void>
}) {
  const stripe = useStripe()
  const elements = useElements()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!stripe || !elements || busy) return
    setBusy(true)
    setError(null)
    try {
      const result = await stripe.confirmPayment({
        elements,
        confirmParams: { return_url: window.location.href },
        redirect: 'if_required',
      })
      if (result.error) {
        setError(result.error.message ?? 'Stripe could not authorize this payment.')
        return
      }
      const payment = await post<GigPayment>(`/payments/gigs/${gigId}/sync`)
      if (!isSecuredPayment(payment.status)) {
        setError(payment.failure_message ?? 'Stripe is still processing. Please retry shortly.')
        return
      }
      await onConfirmed()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not confirm the payment.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
      <PaymentElement options={{ layout: 'tabs' }} />
      {error && <p role="alert" style={{ color: 'var(--rose)', fontSize: 13 }}>{error}</p>}
      <button type="submit" className="btn btn-primary" disabled={!stripe || busy}>
        {busy ? 'Authorizing…' : 'Secure payment'}
      </button>
      <p style={{ color: 'var(--text-faint)', fontSize: 11.5 }}>
        Card details go directly to Stripe and never pass through KARMA.
      </p>
    </form>
  )
}

function ReviewForm({ gigId }: { gigId: number }) {
  const [rating, setRating] = useState(5)
  const [comment, setComment] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (done) {
    return (
      <p role="status" style={{ marginTop: 'var(--s3)', color: 'var(--lime)', fontWeight: 600, fontSize: 14 }}>
        Review posted — their karma just moved.
      </p>
    )
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await post(`/gigs/${gigId}/review`, { rating, comment })
      setDone(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not post the review.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} style={{ marginTop: 'var(--s3)', display: 'flex', flexDirection: 'column', gap: 'var(--s2)' }}>
      <fieldset style={{ border: 'none', padding: 0 }}>
        <legend style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)' }}>Rate this work</legend>
        <div role="radiogroup" aria-label="Rating" style={{ display: 'flex', gap: 2 }}>
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              role="radio"
              aria-checked={rating === n}
              aria-label={`${n} star${n === 1 ? '' : 's'}`}
              onClick={() => setRating(n)}
              style={{
                background: 'none',
                border: 'none',
                fontSize: 26,
                cursor: 'pointer',
                color: n <= rating ? 'var(--karma-gold)' : 'var(--line-strong)',
                lineHeight: 1,
                padding: '4px 2px',
              }}
            >
              ★
            </button>
          ))}
        </div>
      </fieldset>
      <input
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="What went well?"
        aria-label="Review comment"
        style={{ minHeight: 40, padding: '8px 12px', border: '1px solid var(--line-strong)', borderRadius: 'var(--r-input)' }}
      />
      {error && (
        <p role="alert" style={{ color: 'var(--rose)', fontSize: 13 }}>
          {error}
        </p>
      )}
      <button type="submit" className="btn btn-ghost" disabled={busy} style={{ width: '100%' }}>
        {busy ? 'Posting…' : 'Post review'}
      </button>
    </form>
  )
}

function LifecycleRail({ status }: { status: string }) {
  const currentIndex = RAIL.indexOf(status as (typeof RAIL)[number])
  return (
    <ol
      aria-label="Gig progress"
      style={{ display: 'flex', alignItems: 'center', gap: 0, listStyle: 'none', padding: 0, margin: 0 }}
    >
      {RAIL.map((stage, index) => {
        const done = index <= currentIndex
        const isCurrent = index === currentIndex
        return (
          <li
            key={stage}
            style={{ display: 'flex', alignItems: 'center', flex: index === RAIL.length - 1 ? '0 0 auto' : 1 }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <span
                aria-hidden="true"
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: 'var(--r-pill)',
                  background: done ? 'var(--lime)' : 'var(--line)',
                  border: isCurrent ? '3px solid #d9ecc0' : 'none',
                  transition: 'background-color var(--d-state) var(--ease)',
                }}
              />
              <span style={{ fontSize: 10.5, color: done ? 'var(--text)' : 'var(--text-faint)', fontWeight: isCurrent ? 700 : 500, whiteSpace: 'nowrap' }}>
                {LABELS[stage]}
              </span>
            </div>
            {index < RAIL.length - 1 && (
              <span
                aria-hidden="true"
                style={{
                  flex: 1,
                  height: 2,
                  background: index < currentIndex ? 'var(--lime)' : 'var(--line)',
                  marginBottom: 16,
                  minWidth: 8,
                  transition: 'background-color var(--d-state) var(--ease)',
                }}
              />
            )}
          </li>
        )
      })}
    </ol>
  )
}

function isSecuredPayment(status: string): boolean {
  return status === 'authorized' || status === 'captured' || status === 'paid'
}

function PaymentLabel({ status }: { status: string }) {
  const label: Record<string, string> = {
    requires_payment: 'payment required',
    requires_action: 'action required',
    processing: 'processing payment',
    authorized: 'payment secured',
    captured: 'payment captured',
    paid: 'paid',
    cancelled: 'payment cancelled',
    refunded: 'refunded',
  }
  const secured = isSecuredPayment(status)
  return (
    <span style={{ color: secured ? 'var(--lime)' : 'var(--gold)', fontWeight: 600 }}>
      {label[status] ?? status}
    </span>
  )
}

function nextLabel(status: string): string {
  const map: Record<string, string> = {
    assigned: 'Mark as on the way',
    en_route: 'Mark as arrived',
    arrived: 'Start work',
    in_progress: 'Submit completion proof',
  }
  return map[status] ?? 'Awaiting customer approval'
}

function StatusPill({ status }: { status: string }) {
  const done = status === 'completed'
  const cancelled = status === 'cancelled'
  return (
    <span
      className="pill"
      style={{
        color: done ? 'var(--lime)' : cancelled ? 'var(--text-faint)' : 'var(--cyan)',
        background: done ? '#f3f8ec' : cancelled ? 'var(--surface-2)' : '#eef7fa',
        border: 'none',
      }}
    >
      {LABELS[status] ?? status}
    </span>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div style={{ fontSize: 11.5, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </div>
      <div className="num" style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 700 }}>
        {value}
      </div>
    </div>
  )
}

/**
 * Shows whether this gig is being pushed to or is showing its last known state.
 *
 * Announced politely rather than decoratively: the label is real text, and `aria-live`
 * is left off on purpose — a connection blip is not worth interrupting a screen reader
 * over. The dot is `aria-hidden` so the words carry the meaning.
 */
function LiveLink({ state }: { state: 'connecting' | 'live' | 'closed' }) {
  const label =
    state === 'live' ? 'Live' : state === 'connecting' ? 'Connecting…' : 'Updates paused'
  const colour =
    state === 'live' ? 'var(--lime)' : state === 'connecting' ? 'var(--cyan)' : 'var(--text-faint)'

  return (
    <span
      title={
        state === 'live'
          ? 'Changes to this gig arrive as they happen.'
          : 'Showing the last known state. Reload to refresh.'
      }
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11.5, fontWeight: 600, color: colour }}
    >
      <span
        aria-hidden="true"
        style={{ width: 7, height: 7, borderRadius: 'var(--r-pill)', background: colour }}
      />
      {label}
    </span>
  )
}
