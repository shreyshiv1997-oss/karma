import { useCallback, useEffect, useState } from 'react'
import { ApiError, get, patch, post } from '../api/client'
import type { Category, Verification, WorkerProfile as WorkerProfileType } from '../api/types'
import { KarmaRing } from '../components/KarmaRing'
import { TierBadge } from '../components/MatchCard'
import { PhoneVerify } from '../components/PhoneVerify'
import { useAuth } from '../store/auth'

/**
 * Your profile — the portfolio view.
 *
 * One person, additive capabilities. If you are verified you can open a worker
 * profile from here; hiring is a one-tap opt-in. There is no role switch,
 * because there are no roles.
 */

export function Profile() {
  const { user, grant, refreshUser } = useAuth()
  const [worker, setWorker] = useState<WorkerProfileType | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [available, setAvailable] = useState(false)
  // Set when the capability grant asks for a verified contact detail.
  const [needsPhone, setNeedsPhone] = useState(false)

  const isWorker = !!user?.capabilities?.includes('can_work')

  useEffect(() => {
    if (!isWorker) return
    get<WorkerProfileType>('/workers/me/profile')
      .then((data) => {
        setWorker(data)
        setAvailable(data.is_available)
      })
      .catch(() => undefined)
  }, [isWorker])

  useEffect(() => {
    get<Category[]>('/categories').then(setCategories).catch(() => undefined)
  }, [])

  if (!user) return null

  const flash = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(null), 3500)
  }

  const optIntoHiring = async () => {
    setBusy(true)
    setError(null)
    try {
      await grant('can_hire')
      await refreshUser()
      setNeedsPhone(false)
      flash('You can now post gigs.')
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        // The grant exists but needs a proven contact detail first; offer the OTP door.
        setNeedsPhone(true)
      } else {
        setError(err instanceof ApiError ? err.detail : 'Something went wrong.')
      }
    } finally {
      setBusy(false)
    }
  }

  const toggleAvailable = async () => {
    const goingOnline = !available
    if (goingOnline && !window.confirm('Share a fresh precise location once to appear in nearby matching? KARMA does not request location in the background.')) return
    setBusy(true)
    setError(null)
    try {
      let location: Record<string, unknown> = {}
      if (goingOnline) {
        if (!navigator.geolocation) throw new Error('Device location is unavailable in this browser.')
        const position = await new Promise<GeolocationPosition>((resolve, reject) =>
          navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 15_000,
            maximumAge: 0,
          }),
        )
        location = {
          lat: position.coords.latitude,
          lng: position.coords.longitude,
          accuracy_m: position.coords.accuracy,
          location_source: 'device',
          location_consent: true,
        }
      }
      await patch('/workers/me/location', { ...location, is_available: goingOnline })
      setAvailable(goingOnline)
      flash(goingOnline ? 'You are online at the location you just shared.' : 'You are offline. Location will not be requested.')
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      <header className="card" style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
        <div style={{ display: 'flex', gap: 'var(--s4)', alignItems: 'center' }}>
          <KarmaRing value={user.karma} size={72} label={`Karma ${user.karma} of 100`} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 22, letterSpacing: '-0.02em' }}>
              {user.display_name}
            </h1>
            <p style={{ fontSize: 14, color: 'var(--text-muted)' }}>
              @{user.handle}
              {user.city ? ` · ${user.city}` : ''}
            </p>
            {user.verification_tier !== 'none' && (
              <div style={{ marginTop: 6 }}>
                <TierBadge tier={user.verification_tier} />
              </div>
            )}
          </div>
        </div>

        {user.bio && <p style={{ fontSize: 15, lineHeight: 1.55 }}>{user.bio}</p>}

        <div style={{ display: 'flex', gap: 'var(--s5)', flexWrap: 'wrap' }}>
          <Count label="Posts" value={user.posts_count} />
          <Count label="Karma · work" value={user.karma_work} />
          <Count label="Karma · social" value={user.karma_social} />
          <Count label="Streak" value={`${user.streak}d`} />
        </div>
      </header>

      {/* Announce state changes politely; never silently. */}
      {notice && (
        <p role="status" style={{ color: 'var(--lime)', fontWeight: 600, fontSize: 14 }}>
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" style={{ color: 'var(--rose)', fontWeight: 500, fontSize: 14 }}>
          {error}
        </p>
      )}

      {/* Capabilities: additive, never a role. */}
      <section className="card" style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
        <h2 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          What you can do
        </h2>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
          <CapabilityRow
            title="Post and follow"
            detail="Share updates, proof of work, and follow other people."
            granted={user.capabilities.includes('can_post')}
          />
          <CapabilityRow
            title="Hire workers"
            detail="Post gigs and book verified professionals near you."
            granted={user.capabilities.includes('can_hire')}
            action={
              user.capabilities.includes('can_hire') ? undefined : (
                <button type="button" className="btn btn-ghost" onClick={optIntoHiring} disabled={busy} style={{ minHeight: 36, padding: '6px 14px', fontSize: 13.5 }}>
                  {busy ? 'Enabling…' : 'Enable'}
                </button>
              )
            }
          />
          <CapabilityRow
            title="Take work"
            detail={
              user.is_verified && !isWorker
                ? 'Your identity is approved — finish opening your worker profile below.'
                : 'Requires approved identity verification — someone is letting you into their home.'
            }
            granted={isWorker}
            action={
              isWorker ? undefined : (
                <span style={{ fontSize: 12.5, color: user.is_verified ? 'var(--karma-gold)' : 'var(--text-faint)' }}>
                  {user.is_verified ? 'Verified ✓ · finish setup ↓' : 'Needs KYC'}
                </span>
              )
            }
          />
        </ul>

        {/* The verified-contact requirement, met inline instead of as a dead-end error. */}
        {needsPhone && !user.capabilities.includes('can_hire') && (
          <PhoneVerify
            reason="Hiring summons a verified worker to your address — confirm your phone number to enable it."
            onVerified={optIntoHiring}
          />
        )}
      </section>

      {/* The worker dashboard. */}
      {isWorker && worker && (
        <section className="card" style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <h2 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Your work profile
          </h2>

          <div style={{ display: 'flex', gap: 'var(--s5)', flexWrap: 'wrap' }}>
            <Count label="Jobs done" value={worker.total_jobs} />
            <Count label="Rating" value={`★ ${worker.rating.toFixed(1)}`} />
            <Count label="Hourly rate" value={`₹${worker.hourly_rate}`} />
          </div>

          {worker.category && <p style={{ fontSize: 14, color: 'var(--text-muted)' }}>Category: {worker.category}</p>}

          {worker.skills.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {worker.skills.map((skill) => (
                <span key={skill} className="pill" style={{ color: 'var(--text-muted)', background: 'var(--surface-2)', border: 'none' }}>
                  {skill}
                </span>
              ))}
            </div>
          )}

          <button
            type="button"
            className="btn"
            onClick={toggleAvailable}
            disabled={busy}
            aria-pressed={available}
            style={{
              width: '100%',
              background: available ? 'var(--lime)' : 'var(--surface-2)',
              color: available ? '#fff' : 'var(--text)',
              border: `1px solid ${available ? 'var(--lime)' : 'var(--line-strong)'}`,
            }}
          >
            {busy ? 'Updating…' : available ? '● Online — visible to nearby customers' : '○ Go online'}
          </button>

          <p style={{ fontSize: 12.5, color: 'var(--text-faint)', lineHeight: 1.5 }}>
            <span className="num">{worker.proofs?.length ?? 0}</span> proof posts published from
            completed gigs. Each one is tied to a paid transaction and cannot be deleted.
          </p>
        </section>
      )}

      {/* The road to taking work: verify identity → in review → open a worker profile. */}
      {!isWorker && <WorkGate categories={categories} />}
    </div>
  )
}

function CapabilityRow({
  title,
  detail,
  granted,
  action,
}: {
  title: string
  detail: string
  granted: boolean
  action?: React.ReactNode
}) {
  return (
    <li style={{ display: 'flex', gap: 'var(--s3)', alignItems: 'center' }}>
      <span
        aria-hidden="true"
        style={{
          width: 22,
          height: 22,
          borderRadius: 'var(--r-pill)',
          display: 'grid',
          placeItems: 'center',
          fontSize: 12,
          fontWeight: 700,
          flexShrink: 0,
          background: granted ? '#f3f8ec' : 'var(--surface-2)',
          color: granted ? 'var(--lime)' : 'var(--text-faint)',
          border: `1px solid ${granted ? 'var(--lime)' : 'var(--line-strong)'}`,
        }}
      >
        {granted ? '✓' : '·'}
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ fontSize: 14.5, fontWeight: 600, display: 'block' }}>{title}</span>
        <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>{detail}</span>
      </span>
      {action}
      <span className="sr-only">{granted ? 'Enabled' : 'Not enabled'}</span>
    </li>
  )
}

/**
 * The gate between "registered" and "worker", in three honest states.
 *
 * Verified-but-not-yet-working used to land back on the verification form — it
 * looked like the approval had vanished, and worse, worker registration had no UI
 * at all, so the account could never actually reach can_work from the web client.
 */
function WorkGate({ categories }: { categories: Category[] }) {
  const { refreshUser } = useAuth()
  const [verifications, setVerifications] = useState<Verification[] | null>(null)

  const load = useCallback(() => {
    get<Verification[]>('/verification/me')
      .then(setVerifications)
      .catch(() => setVerifications([]))
  }, [])

  useEffect(load, [load])

  if (verifications === null) {
    return <div className="skeleton" style={{ height: 180, borderRadius: 'var(--r-card)' }} />
  }

  const pending = verifications.find((v) => v.status === 'pending')
  const approved = verifications.some((v) => v.status === 'approved')
  // Newest first: index 0 is the latest decision. Only nag about a rejection when it is
  // the most recent outcome — an older rejection under a fresh pending review is noise.
  const latestRejected = !pending && !approved && verifications[0]?.status === 'rejected'

  if (pending) {
    return (
      <section className="card" style={{ padding: 'var(--s5)' }}>
        <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 17 }}>Verification in review</h2>
        <p style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 6, lineHeight: 1.55 }}>
          Your document is with the review team — only its last four digits are stored, never
          the full number. Approval raises your karma and unlocks taking work.
        </p>
        <p style={{ fontSize: 12.5, color: 'var(--text-faint)', marginTop: 'var(--s3)' }}>
          Submitted{' '}
          {new Date(pending.created_at).toLocaleDateString('en-IN', {
            day: 'numeric',
            month: 'short',
            year: 'numeric',
          })}
          {' '}· {DOC_LABEL[pending.document_type]} · waiting on an operator
        </p>
      </section>
    )
  }

  if (approved) {
    // The approval landed; the only thing between this account and can_work is the
    // worker profile itself. This card is that missing step.
    return <WorkerRegisterCard categories={categories} onDone={refreshUser} />
  }

  return (
    <>
      {latestRejected && (
        <p role="note" style={{ color: 'var(--rose)', fontSize: 13.5, fontWeight: 500 }}>
          Your last submission was not approved — double-check the document details and try again.
        </p>
      )}
      <VerificationCard categories={categories} onSubmitted={load} />
    </>
  )
}

function VerificationCard({
  categories,
  onSubmitted,
}: {
  categories: Category[]
  onSubmitted: () => void
}) {
  const [documentType, setDocumentType] = useState<Verification['document_type']>('aadhaar')
  const [documentRef, setDocumentRef] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await post('/verification/submit', { document_type: documentType, document_ref: documentRef })
      // The parent reloads /verification/me and swaps this form for the in-review card.
      onSubmitted()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not submit.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
      <h2 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Want to take work?
      </h2>
      <p style={{ fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.55 }}>
        Verify your identity first. It is the reason customers can trust a stranger in their
        home — and it is worth up to 20 karma.
      </p>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
        <div className="field">
          <label htmlFor="doctype">Document</label>
          <select
            id="doctype"
            value={documentType}
            onChange={(e) => setDocumentType(e.target.value as Verification['document_type'])}
          >
            <option value="aadhaar">Aadhaar — Gold tier</option>
            <option value="pan">PAN — Silver tier</option>
            <option value="govt_id">Other government ID — Bronze tier</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="docref">Document number</label>
          <input
            id="docref"
            value={documentRef}
            onChange={(e) => setDocumentRef(e.target.value)}
            placeholder="1234 5678 9012"
            required
            minLength={4}
          />
        </div>
        {categories.length > 0 && (
          <p style={{ fontSize: 12.5, color: 'var(--text-faint)' }}>
            {categories.length} service categories available once approved.
          </p>
        )}
        {error && (
          <p role="alert" style={{ color: 'var(--rose)', fontSize: 13.5 }}>
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-ghost" disabled={busy} style={{ width: '100%' }}>
          {busy ? 'Submitting…' : 'Submit for review'}
        </button>
      </form>
    </section>
  )
}

const DOC_LABEL: Record<Verification['document_type'], string> = {
  aadhaar: 'Aadhaar',
  pan: 'PAN',
  govt_id: 'Government ID',
}

/** The missing step: an approved account opens its worker profile and gains can_work. */
function WorkerRegisterCard({
  categories,
  onDone,
}: {
  categories: Category[]
  onDone: () => void | Promise<void>
}) {
  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [rate, setRate] = useState('350')
  const [bio, setBio] = useState('')
  const [skills, setSkills] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (categoryId === null) {
      setError('Choose the category you want to work in.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await post('/workers/register', {
        category_id: categoryId,
        hourly_rate: Number.parseFloat(rate) || 350,
        bio: bio.trim(),
        skills: skills
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
          .slice(0, 20),
      })
      // can_work lands on the refreshed user, this gate disappears, and the dashboard
      // section above fetches the brand-new profile.
      await onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not open your worker profile.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="card"
      style={{
        padding: 'var(--s5)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--s3)',
        borderColor: 'var(--lime)',
      }}
    >
      <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 17 }}>
        Identity approved ✓ — open your worker profile
      </h2>
      <p style={{ fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.55 }}>
        One last step. Pick the work you want to be found for; customers within 5 km will see
        you with your verification tier attached.
      </p>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
        <div className="field">
          <label htmlFor="worker-category">Category</label>
          <select
            id="worker-category"
            value={categoryId ?? ''}
            onChange={(e) => setCategoryId(Number(e.target.value) || null)}
            required
          >
            <option value="" disabled>
              Choose a category
            </option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.emoji} {c.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="worker-rate">Hourly rate (₹)</label>
          <input
            id="worker-rate"
            inputMode="decimal"
            value={rate}
            onChange={(e) => setRate(e.target.value.replace(/[^0-9.]/g, '').slice(0, 7))}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="worker-bio">Bio (optional)</label>
          <textarea
            id="worker-bio"
            rows={2}
            maxLength={2000}
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            placeholder="10 years rewiring homes across Jabalpur"
          />
        </div>
        <div className="field">
          <label htmlFor="worker-skills">Skills, comma separated (optional)</label>
          <input
            id="worker-skills"
            value={skills}
            onChange={(e) => setSkills(e.target.value)}
            placeholder="wiring, MCB, inverters"
          />
        </div>
        {error && (
          <p role="alert" style={{ color: 'var(--rose)', fontSize: 13.5 }}>
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary" disabled={busy} style={{ width: '100%' }}>
          {busy ? 'Opening your profile…' : 'Start taking work'}
        </button>
      </form>
    </section>
  )
}

function Count({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div style={{ fontSize: 11.5, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </div>
      <div className="num" style={{ fontFamily: 'var(--font-display)', fontSize: 19, fontWeight: 700 }}>
        {value}
      </div>
    </div>
  )
}
