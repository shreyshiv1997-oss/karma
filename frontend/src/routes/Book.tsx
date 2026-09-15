import { useEffect, useState } from 'react'
import { ApiError, get, post } from '../api/client'
import type { Candidate, Category, FareBreakdown, GeocodedPlace, Gig } from '../api/types'
import { MatchCard } from '../components/MatchCard'
import { FareBreakdownView } from '../components/FareBreakdown'
import { PhoneVerify } from '../components/PhoneVerify'
import { useAuth, canHire } from '../store/auth'

/**
 * The booking flow — Labour Link's four-step wizard, kept almost intact, with
 * the estimate updating live and every multiplier animating in as it activates.
 *
 * Step 3 is the fusion: ranked matches carrying their reasons *and* their
 * social proof.
 */

const STEPS = ['What', 'When & where', 'Who', 'Payment'] as const

type SelectedLocation = {
  lat: number
  lng: number
  source: 'device' | 'geocoded'
  accuracy?: number
  provider?: string
  attribution?: string
  labelAttribution?: string
}

export function Book() {
  const { user, grant, refreshUser } = useAuth()
  const [step, setStep] = useState(0)
  const [categories, setCategories] = useState<Category[]>([])
  const [category, setCategory] = useState<Category | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [hours, setHours] = useState(2)
  const [urgency, setUrgency] = useState<'standard' | 'urgent'>('standard')
  const [address, setAddress] = useState('')
  const [location, setLocation] = useState<SelectedLocation | null>(null)
  const [locationResults, setLocationResults] = useState<GeocodedPlace[]>([])
  const [fare, setFare] = useState<FareBreakdown | null>(null)
  const [gig, setGig] = useState<Gig | null>(null)
  const [matches, setMatches] = useState<Candidate[] | null>(null)
  const [bookedWith, setBookedWith] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Pricing: the transparent estimate, or the poster's own number (fee on top).
  const [pricing, setPricing] = useState<'estimate' | 'custom'>('estimate')
  const [customPrice, setCustomPrice] = useState('')
  // The hire capability gate: an email-registered account proves a phone here.
  const [needsPhone, setNeedsPhone] = useState(false)

  const customAmount = Number.parseFloat(customPrice)
  // Mirrors the backend's Field(gt=0, le=1_000_000), so the button can't submit what the
  // API is guaranteed to refuse.
  const customValid =
    pricing === 'custom' &&
    Number.isFinite(customAmount) &&
    customAmount > 0 &&
    customAmount <= 1_000_000

  useEffect(() => {
    get<Category[]>('/categories').then(setCategories).catch(() => undefined)
  }, [])

  // The estimate recomputes live as the inputs change — never on submit.
  useEffect(() => {
    if (!category || !location) {
      setFare(null)
      return
    }
    if (pricing === 'custom' && !customValid) {
      // A half-typed price must not flash a stale computed estimate.
      setFare(null)
      return
    }
    let cancelled = false
    post<FareBreakdown>('/gigs/estimate', {
      category_id: category.id,
      lat: location.lat,
      lng: location.lng,
      estimated_hours: hours,
      urgency,
      ...(customValid ? { custom_price: customAmount } : {}),
    })
      .then((data) => !cancelled && setFare(data))
      .catch(() => {
        // A failed estimate must not leave the *previous* inputs' breakdown on screen —
        // a stale card would confidently price a different job than the one shown.
        if (!cancelled) setFare(null)
      })
    return () => {
      cancelled = true
    }
  }, [category, hours, urgency, location, pricing, customValid, customAmount])

  const canBook = canHire(user)

  const searchAddress = async () => {
    if (address.trim().length < 3) {
      setError('Type at least 3 characters before searching.')
      return
    }
    if (!window.confirm('Send this typed address to KARMA’s configured geocoding provider? Only the result you select will be saved with the gig.')) return
    setBusy(true)
    setError(null)
    try {
      const places = await post<GeocodedPlace[]>('/locations/geocode', {
        query: address.trim(),
        consent: true,
        limit: 5,
      })
      setLocationResults(places)
      if (places.length === 0) setError('No matching address was found.')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Address lookup is unavailable.')
    } finally {
      setBusy(false)
    }
  }

  const useCurrentLocation = async () => {
    if (!navigator.geolocation) {
      setError('This browser does not provide device location.')
      return
    }
    if (!window.confirm('Request your precise location once? KARMA uses it for nearby matching and sends it to the configured geocoder for an address label. It is not requested in the background.')) return
    setBusy(true)
    setError(null)
    try {
      const position = await new Promise<GeolocationPosition>((resolve, reject) =>
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 15_000,
          maximumAge: 0,
        }),
      )
      const point: SelectedLocation = {
        lat: position.coords.latitude,
        lng: position.coords.longitude,
        source: 'device',
        accuracy: position.coords.accuracy,
      }
      setLocation(point)
      setLocationResults([])
      try {
        const place = await post<GeocodedPlace | null>('/locations/reverse', {
          lat: point.lat,
          lng: point.lng,
          consent: true,
        })
        setAddress(place?.label ?? `${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}`)
        if (place) {
          setLocation({ ...point, labelAttribution: `${place.provider} · ${place.attribution}` })
        }
      } catch {
        setAddress(`${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}`)
      }
    } catch {
      setError('Location was unavailable or permission was not granted.')
    } finally {
      setBusy(false)
    }
  }

  const selectAddress = (place: GeocodedPlace) => {
    setAddress(place.label)
    setLocation({
      lat: place.lat,
      lng: place.lng,
      source: 'geocoded',
      provider: place.provider,
      attribution: place.attribution,
    })
    setLocationResults([])
  }

  const createGig = async () => {
    if (!category || !location || !address.trim()) {
      setError('Search and select an address, or consent to a one-time device location.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (!canBook) {
        await grant('can_hire')
        await refreshUser()
      }
      const created = await post<Gig>('/gigs', {
        category_id: category.id,
        title,
        description,
        lat: location.lat,
        lng: location.lng,
        address_label: address,
        location_source: location.source,
        location_accuracy_m: location.accuracy,
        geocoder: location.provider,
        location_consent: true,
        estimated_hours: hours,
        urgency,
        // A poster-set price travels with the gig and is never recomputed afterwards.
        ...(customValid ? { custom_price: customAmount } : {}),
      })
      setGig(created)
      const found = await post<Candidate[]>('/matching/find', { gig_id: created.id })
      setMatches(found)
      setStep(2)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403 && !canBook) {
        // The only refusal before a gig exists is the verified-contact rule: hiring
        // summons a stranger to an address, so the account proves a phone first.
        setNeedsPhone(true)
      } else {
        setError(err instanceof ApiError ? err.detail : 'Could not post the gig.')
      }
    } finally {
      setBusy(false)
    }
  }

  const book = async (candidate: Candidate) => {
    if (!gig) return
    setBusy(true)
    setError(null)
    try {
      const assigned = await post<Gig>(`/gigs/${gig.id}/assign?worker_id=${candidate.user_id}`, {})
      setGig(assigned)
      setBookedWith(candidate.user_id)
      setStep(3)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not book that worker.')
    } finally {
      setBusy(false)
    }
  }

  const progress = ((step + 1) / STEPS.length) * 100

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      <header>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 24, letterSpacing: '-0.02em' }}>
          Post a gig
        </h1>
        <div
          role="progressbar"
          aria-valuenow={step + 1}
          aria-valuemin={1}
          aria-valuemax={STEPS.length}
          aria-label={`Step ${step + 1} of ${STEPS.length}: ${STEPS[step]}`}
          style={{ height: 4, background: 'var(--line)', borderRadius: 'var(--r-pill)', marginTop: 'var(--s3)', overflow: 'hidden' }}
        >
          <div
            style={{
              height: '100%',
              width: `${progress}%`,
              background: 'var(--violet)',
              transition: 'width var(--d-enter) var(--ease)',
            }}
          />
        </div>
        <p style={{ fontSize: 13, color: 'var(--text-faint)', marginTop: 6 }}>
          Step {step + 1} of {STEPS.length} · {STEPS[step]}
        </p>
      </header>

      {error && (
        <p role="alert" style={{ color: 'var(--rose)', fontWeight: 500 }}>
          {error}
        </p>
      )}

      {/* ── STEP 1: what ─────────────────────────────────────────── */}
      {step === 0 && (
        <section className="card" style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <div>
            <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 'var(--s3)' }}>What do you need done?</h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(104px, 1fr))', gap: 'var(--s2)' }}>
              {categories.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  aria-pressed={category?.id === c.id}
                  onClick={() => setCategory(c)}
                  style={{
                    minHeight: 72,
                    padding: 'var(--s3)',
                    borderRadius: 'var(--r-input)',
                    border: `1px solid ${category?.id === c.id ? 'var(--violet)' : 'var(--line-strong)'}`,
                    background: category?.id === c.id ? '#f5f0ff' : 'var(--surface)',
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 4,
                    transition: 'border-color var(--d-state) var(--ease)',
                  }}
                >
                  <span aria-hidden="true" style={{ fontSize: 22 }}>{c.emoji}</span>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{c.name}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <label htmlFor="title">Title</label>
            <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Rewire 3-room flat" />
          </div>

          <div className="field">
            <label htmlFor="desc">Details</label>
            <textarea
              id="desc"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Old aluminium wiring, needs full replacement"
            />
          </div>

          <button
            type="button"
            className="btn btn-primary"
            disabled={!category || title.trim().length < 3}
            onClick={() => setStep(1)}
            style={{ width: '100%' }}
          >
            Continue
          </button>
        </section>
      )}

      {/* ── STEP 2: when & where ─────────────────────────────────── */}
      {step === 1 && (
        <section className="card" style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <div className="field">
            <label htmlFor="address">Service address or landmark</label>
            <input
              id="address"
              value={address}
              maxLength={200}
              onChange={(e) => {
                setAddress(e.target.value)
                setLocationResults([])
              }}
              placeholder="Type, then choose Search address"
            />
          </div>
          <div style={{ display: 'flex', gap: 'var(--s2)' }}>
            <button type="button" className="btn btn-ghost" style={{ flex: 1 }} onClick={searchAddress} disabled={busy}>
              Search address
            </button>
            <button type="button" className="btn btn-ghost" style={{ flex: 1 }} onClick={useCurrentLocation} disabled={busy}>
              Use current
            </button>
          </div>
          {locationResults.length > 0 && (
            <div role="listbox" aria-label="Address results" style={{ display: 'grid', gap: 6 }}>
              {locationResults.map((place) => (
                <button key={place.place_id} type="button" className="btn btn-ghost" onClick={() => selectAddress(place)} style={{ textAlign: 'left', height: 'auto', padding: 10 }}>
                  <span>{place.label}</span>
                  <small style={{ display: 'block', color: 'var(--text-faint)' }}>{place.provider} · {place.attribution}</small>
                </button>
              ))}
            </div>
          )}
          <p style={{ color: location ? 'var(--text-faint)' : 'var(--gold)', fontSize: 12, lineHeight: 1.45 }}>
            {location
              ? location.source === 'device'
                ? `One-time device fix selected${location.accuracy ? ` · ±${Math.round(location.accuracy)} m` : ''}${location.labelAttribution ? ` · label by ${location.labelAttribution}` : ''}. Editing the label does not move it.`
                : `Using the result you selected from ${location.provider} · ${location.attribution}. Editing the label does not move it.`
              : 'Typing alone does not assign coordinates. Select a search result or explicitly share current location.'}
          </p>

          <div className="field">
            <label htmlFor="hours">Estimated hours</label>
            <input
              id="hours"
              type="range"
              min={1}
              max={12}
              step={0.5}
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
              aria-valuetext={`${hours} hours`}
            />
            <output htmlFor="hours" className="num" style={{ fontSize: 14, color: 'var(--text-muted)' }}>
              {hours} {hours === 1 ? 'hour' : 'hours'}
            </output>
          </div>

          <fieldset style={{ border: 'none', padding: 0 }}>
            <legend style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 'var(--s2)' }}>
              Urgency
            </legend>
            <div style={{ display: 'flex', gap: 'var(--s2)' }}>
              {(['standard', 'urgent'] as const).map((u) => (
                <button
                  key={u}
                  type="button"
                  aria-pressed={urgency === u}
                  onClick={() => setUrgency(u)}
                  className="btn"
                  style={{
                    flex: 1,
                    background: urgency === u ? 'var(--ink)' : 'var(--surface)',
                    color: urgency === u ? '#fff' : 'var(--text)',
                    border: `1px solid ${urgency === u ? 'var(--ink)' : 'var(--line-strong)'}`,
                  }}
                >
                  {u === 'standard' ? 'Standard' : 'Urgent · today'}
                </button>
              ))}
            </div>
          </fieldset>

          {/* Who sets the price: the fare engine, or the poster. */}
          <fieldset style={{ border: 'none', padding: 0 }}>
            <legend style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 'var(--s2)' }}>
              Pricing
            </legend>
            <div style={{ display: 'flex', gap: 'var(--s2)' }}>
              {(
                [
                  { id: 'estimate', label: 'Transparent estimate' },
                  { id: 'custom', label: 'Set my own price' },
                ] as const
              ).map((option) => (
                <button
                  key={option.id}
                  type="button"
                  aria-pressed={pricing === option.id}
                  onClick={() => setPricing(option.id)}
                  className="btn"
                  style={{
                    flex: 1,
                    background: pricing === option.id ? 'var(--ink)' : 'var(--surface)',
                    color: pricing === option.id ? '#fff' : 'var(--text)',
                    border: `1px solid ${pricing === option.id ? 'var(--ink)' : 'var(--line-strong)'}`,
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>
            {pricing === 'custom' && (
              <div className="field" style={{ marginTop: 'var(--s3)' }}>
                <label htmlFor="custom-price">Your price for the work (₹)</label>
                <input
                  id="custom-price"
                  inputMode="decimal"
                  placeholder="e.g. 1500"
                  value={customPrice}
                  onChange={(e) =>
                    // One decimal point, paise to two places, and never beyond the backend's cap.
                    setCustomPrice(
                      e.target.value
                        .replace(/[^0-9.]/g, '')
                        .replace(/(\..*)\./g, '$1')
                        .replace(/^(\d{0,7})(\.\d{0,2})?.*$/, '$1$2'),
                    )
                  }
                />
                {customAmount > 1_000_000 ? (
                  <p role="alert" style={{ fontSize: 12.5, color: 'var(--rose)', lineHeight: 1.5 }}>
                    Prices are capped at ₹10,00,000 per gig.
                  </p>
                ) : (
                  <p style={{ fontSize: 12.5, color: 'var(--text-faint)', lineHeight: 1.5 }}>
                    You name what the work is worth — no multipliers apply. The 15% platform fee
                    is added on top and shown before you post.
                  </p>
                )}
              </div>
            )}
          </fieldset>

          {/* Live, transparent pricing. */}
          {fare && (
            <div style={{ padding: 'var(--s4)', background: 'var(--surface-2)', borderRadius: 'var(--r-input)' }}>
              <h2 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 'var(--s3)' }}>
                {pricing === 'custom' ? 'Your price · all-in' : 'Estimated price'}
              </h2>
              <FareBreakdownView fare={fare} />
            </div>
          )}

          {/* A verified phone is what unlocks hiring; prove it without leaving the flow. */}
          {needsPhone && (
            <PhoneVerify
              reason="Posting a gig summons a verified worker to your address — confirm your phone number first."
              onVerified={async () => {
                await refreshUser()
                setNeedsPhone(false)
                await createGig()
              }}
            />
          )}

          <div style={{ display: 'flex', gap: 'var(--s2)' }}>
            <button type="button" className="btn btn-ghost" onClick={() => setStep(0)}>Back</button>
            <button
              type="button"
              className="btn btn-primary"
              style={{ flex: 1 }}
              onClick={createGig}
              disabled={busy || !location || (pricing === 'custom' && !customValid)}
            >
              {busy ? 'Finding workers…' : 'Find workers'}
            </button>
          </div>
        </section>
      )}

      {/* ── STEP 3: who ──────────────────────────────────────────── */}
      {step === 2 && (
        <section style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s3)' }}>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 18 }}>
            {matches?.length ?? 0} worker{matches?.length === 1 ? '' : 's'} near you
          </h2>
          {matches === null && <div className="skeleton" style={{ height: 160, borderRadius: 'var(--r-card)' }} />}
          {matches?.map((candidate) => (
            <MatchCard
              key={candidate.user_id}
              candidate={candidate}
              onBook={book}
              busy={busy}
              booked={bookedWith === candidate.user_id}
            />
          ))}
          {matches?.length === 0 && (
            <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 'var(--s6) 0' }}>
              No verified workers within 5 km right now. Try a different category or time.
            </p>
          )}
        </section>
      )}

      {/* ── STEP 4: review ───────────────────────────────────────── */}
      {step === 3 && gig && (
        <section className="card" style={{ padding: 'var(--s5)', display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <div style={{ textAlign: 'center', padding: 'var(--s4) 0' }}>
            <div aria-hidden="true" style={{ fontSize: 40, color: 'var(--lime)' }}>✓</div>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 22, marginTop: 'var(--s2)' }}>
              Gig booked · payment required
            </h2>
            <p style={{ color: 'var(--text-muted)', fontSize: 14.5, marginTop: 4 }}>
              Secure the fixed price under <strong>Gigs</strong>. The worker cannot travel until Stripe confirms authorization.
            </p>
          </div>
          <FareBreakdownView fare={gig.fare_breakdown} emphasis="total" />
          <a href="#/gigs" className="btn btn-primary" style={{ width: '100%' }}>
            Secure payment & track
          </a>
        </section>
      )}
    </div>
  )
}
