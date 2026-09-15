/**
 * Live API smoke test for the React Native client.
 *
 * Walks the RN client's exact call sequence against a seeded backend and
 * asserts the shape of every response a screen reads. Self-contained Node
 * (global fetch, Node >= 18) — no build step, no test runner:
 *
 *   node scripts/smoke-live.mjs [BASE]
 *
 * Defaults to http://127.0.0.1:8000/api/v1. Exits non-zero on any failure,
 * so it can gate a deployment the same way the backend's live journeys do.
 */
const BASE = (process.argv[2] ?? 'http://127.0.0.1:8000/api/v1').replace(/\/+$/, '')

let pass = 0
let fail = 0
const ok = (name, cond, extra = '') => {
  if (cond) {
    pass++
    console.log(`  \u2713 ${name}`)
  } else {
    fail++
    console.log(`  \u2717 ${name} ${extra}`)
  }
}

async function call(token, method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let data = null
  try {
    data = await res.json()
  } catch {}
  return { status: res.status, data }
}

async function login(identifier) {
  const { status, data } = await call(null, 'POST', '/auth/login', {
    identifier,
    password: 'StrongPass!234',
  })
  if (status !== 200) throw new Error(`login ${identifier} \u2192 ${status} ${JSON.stringify(data)}`)
  return data
}

try {
  console.log('\u2014 auth \u2014')
  const priyaAuth = await login('priya')
  ok('login returns user + token pair', priyaAuth.user?.id === 1 && !!priyaAuth.access_token && !!priyaAuth.refresh_token)
  const priya = priyaAuth.access_token
  let r = await call(priya, 'GET', '/auth/me')
  ok('GET /auth/me \u2192 UserOut fields the Profile screen reads',
    r.status === 200 &&
    Array.isArray(r.data.capabilities) &&
    typeof r.data.karma === 'number' &&
    typeof r.data.karma_work === 'number' &&
    typeof r.data.karma_social === 'number' &&
    typeof r.data.posts_count === 'number' &&
    typeof r.data.streak === 'number',
    JSON.stringify(r.data).slice(0, 200))

  const rameshAuth = await login('ramesh.electric')
  const ramesh = rameshAuth.access_token
  ok('ramesh has can_work', rameshAuth.user.capabilities.includes('can_work'))

  console.log('\u2014 feed \u2014')
  r = await call(priya, 'GET', '/feed/posts?limit=20')
  ok('GET /feed/posts \u2192 Post fields the PostCard reads',
    r.status === 200 && Array.isArray(r.data) && r.data.length > 0 &&
    ['id', 'kind', 'body', 'likes_count', 'comments_count', 'created_at', 'author_name', 'author_handle', 'author_karma', 'before_url'].every((k) => k in r.data[0]),
    JSON.stringify(r.data[0] ?? {}).slice(0, 200))
  const proofPosts = r.data.filter((p) => p.kind === 'proof')
  ok('seed contains proof posts (slider + evidence strip)', proofPosts.length > 0)

  r = await call(priya, 'GET', '/feed/posts?limit=20&kind=proof')
  ok('kind=proof filter', r.status === 200 && r.data.every((p) => p.kind === 'proof'))

  const lastId = r.data.length ? r.data[r.data.length - 1].id : r.data[0]?.id
  r = await call(priya, 'GET', `/feed/posts?limit=20&before_id=${lastId}`)
  ok('keyset before_id returns older posts only', r.status === 200 && r.data.every((p) => p.id < lastId))

  console.log('\u2014 categories & fare \u2014')
  r = await call(priya, 'GET', '/categories')
  const categories = r.data
  ok('GET /categories \u2192 Category fields the wizard reads',
    r.status === 200 && categories.length > 0 &&
    ['id', 'name', 'emoji', 'base_fare', 'per_hour_rate'].every((k) => k in categories[0]),
    JSON.stringify(categories[0] ?? {}).slice(0, 200))
  // Pin the gig to ramesh's own category so the matching step is deterministic
  // and the journey is re-runnable no matter what the earlier runs left behind.
  r = await call(ramesh, 'GET', '/workers/me/profile')
  const rameshCategoryName = r.data?.category
  const cat =
    categories.find((c) => c.name === rameshCategoryName) ??
    categories.find((c) => c.name.toLowerCase().includes('electric')) ??
    categories[0]

  r = await call(priya, 'POST', '/gigs/estimate', {
    category_id: cat.id,
    lat: 22.7176,
    lng: 75.8506,
    estimated_hours: 2,
    urgency: 'standard',
  })
  ok('POST /gigs/estimate \u2192 FareBreakdown the view renders',
    r.status === 200 &&
    ['base_fare', 'distance_fare', 'time_fare', 'subtotal', 'skill_multiplier', 'urgency_multiplier', 'night_multiplier', 'platform_fee', 'total'].every((k) => typeof r.data[k] === 'number'),
    JSON.stringify(r.data).slice(0, 200))

  console.log('\u2014 location consent contract \u2014')
  r = await call(priya, 'POST', '/locations/geocode', { query: 'Indore', limit: 5 })
  ok('geocode without consent is refused (422)', r.status === 422, `got ${r.status}`)
  // Zero-service dev runs with GEOCODING_PROVIDER=disabled, in which case the
  // documented answer is an explicit 503 "not configured" — the app renders that
  // as "Address lookup is unavailable". A configured provider returns 200 + a list.
  // Either way it is explicit, never a crash; the bug would be a bare 500.
  r = await call(priya, 'POST', '/locations/geocode', { query: 'Indore', consent: true, limit: 5 })
  const geocodeExplicit =
    (r.status === 200 && Array.isArray(r.data)) ||
    (r.status === 503 && typeof r.data?.detail === 'string' && r.data.detail.length > 0)
  ok('geocode with consent: explicit answer (list, or "not configured"), never a crash', geocodeExplicit, `got ${r.status} ${JSON.stringify(r.data).slice(0, 120)}`)

  console.log('\u2014 gig creation & matching \u2014')
  // can_hire is self-service but not self-asserted: it needs a verified contact.
  // The seed already grants it to priya, so the honest check is "priya can hire".
  // If an account lacked it, the endpoint would correctly 403 until verified.
  r = await call(priya, 'GET', '/auth/me')
  const canHireAlready = r.data.capabilities?.includes('can_hire')
  if (!canHireAlready) {
    await call(priya, 'POST', '/auth/capability/can_hire')
  }
  const meAfter = (await call(priya, 'GET', '/auth/me')).data
  ok('priya holds can_hire (seeded, or granted)', meAfter.capabilities?.includes('can_hire'), JSON.stringify(meAfter.capabilities))

  // The same call the app makes when a worker taps "Go online": a fresh,
  // consented, device-sourced fix. Re-runs start from whatever state the last
  // run left, so availability is always re-established here.
  r = await call(ramesh, 'PATCH', '/workers/me/location', {
    lat: 22.7176,
    lng: 75.8506,
    accuracy_m: 12,
    location_source: 'device',
    location_consent: true,
    is_available: true,
  })
  ok('worker goes online with a consented device fix', r.status === 200, `got ${r.status} ${JSON.stringify(r.data).slice(0, 160)}`)

  r = await call(priya, 'POST', '/gigs', {
    category_id: cat.id,
    title: 'Smoke test wiring job',
    description: 'React Native client smoke',
    lat: 22.7176,
    lng: 75.8506,
    address_label: 'Indore (smoke)',
    location_source: 'provided',
    estimated_hours: 2,
    urgency: 'standard',
  })
  ok('POST /gigs \u2192 GigOut with fare_breakdown + total',
    r.status === 201 && r.data.status === 'searching' && typeof r.data.total === 'number' && r.data.fare_breakdown?.total != null,
    `got ${r.status} ${JSON.stringify(r.data).slice(0, 200)}`)
  const gig = r.data

  r = await call(priya, 'POST', '/matching/find', { gig_id: gig.id })
  ok('POST /matching/find \u2192 Candidate list with reasons[]',
    r.status === 200 && Array.isArray(r.data) &&
    (r.data.length === 0 || ['user_id', 'display_name', 'rating', 'distance_km', 'eta_minutes', 'score', 'karma', 'reasons', 'verification_tier', 'proof_count'].every((k) => k in r.data[0])),
    `got ${r.status} ${JSON.stringify(r.data).slice(0, 200)}`)
  ok('the online worker in the gig\'s category is ranked', r.data.some((c) => c.user_id === rameshAuth.user.id), JSON.stringify(r.data.map((c) => c.user_id)))
  const candidates = r.data

  console.log('\u2014 assignment & secured payment (simulator) \u2014')
  const worker = rameshAuth.user.id
  r = await call(priya, 'POST', `/gigs/${gig.id}/assign?worker_id=${worker}`, {})
  ok('POST /gigs/{id}/assign \u2192 assigned with worker set',
    r.status === 200 && r.data.status === 'assigned' && r.data.worker_id === worker,
    `got ${r.status} ${JSON.stringify(r.data).slice(0, 200)}`)

  r = await call(priya, 'POST', `/payments/gigs/${gig.id}/intent`)
  ok('POST /payments/gigs/{id}/intent (simulated) \u2192 secured without a card',
    r.status === 200 && r.data.provider === 'simulated' && ['authorized', 'captured', 'paid'].includes(r.data.status),
    `got ${r.status} ${JSON.stringify(r.data).slice(0, 200)}`)
  ok('intent carries amount/payout/fee the UI may show',
    typeof r.data.amount === 'number' && typeof r.data.worker_payout === 'number' && typeof r.data.platform_fee === 'number')

  r = await call(priya, 'GET', `/payments/gigs/${gig.id}`)
  ok('GET /payments/gigs/{id} \u2192 GigPayment fields', r.status === 200 && r.data.status !== undefined)

  console.log('\u2014 realtime ticket \u2014')
  r = await call(priya, 'POST', '/realtime/ticket')
  ok('POST /realtime/ticket \u2192 single-use ticket + ws path',
    r.status === 200 && typeof r.data.ticket === 'string' && r.data.expires_in === 30 && typeof r.data.ws_path === 'string',
    JSON.stringify(r.data).slice(0, 120))
  const ticket = r.data?.ticket
  r = await call(ramesh, 'POST', '/realtime/ticket')
  ok('the other party gets their own ticket', r.status === 200 && r.data.ticket !== ticket)

  console.log('\u2014 worker lifecycle \u2014')
  const workerToken = ramesh
  for (const next of ['en_route', 'arrived', 'in_progress', 'completion_pending']) {
    r = await call(workerToken, 'POST', `/gigs/${gig.id}/status`, { status: next })
    ok(`worker \u2192 ${next}`, r.status === 200 && r.data.status === next, `got ${r.status} ${JSON.stringify(r.data).slice(0, 160)}`)
  }

  console.log('\u2014 release, completion, proof, review \u2014')
  r = await call(priya, 'POST', `/payments/gigs/${gig.id}/release`)
  ok('POST /payments/gigs/{id}/release \u2192 captured', r.status === 200 && ['captured', 'paid'].includes(r.data.status), `got ${r.status} ${JSON.stringify(r.data).slice(0, 200)}`)

  r = await call(priya, 'GET', `/gigs/${gig.id}`)
  ok('gig completed after release', r.status === 200 && r.data.status === 'completed', `got ${r.status} ${r.data?.status}`)

  r = await call(priya, 'GET', `/gigs/${gig.id}/reviews`)
  ok('GET reviews before posting \u2192 200 array', r.status === 200 && Array.isArray(r.data))

  r = await call(priya, 'POST', `/gigs/${gig.id}/review`, { rating: 5, comment: 'RN smoke review' })
  ok('POST review \u2192 201', r.status === 201 && r.data.rating === 5, `got ${r.status} ${JSON.stringify(r.data).slice(0, 160)}`)

  console.log('\u2014 the seam: proof post + karma event \u2014')
  r = await call(ramesh, 'GET', '/feed/posts?limit=50&kind=proof')
  const allProof = r.data
  ok('a proof post was published for the paid gig', allProof.length > proofPosts.length, `before=${proofPosts.length} after=${allProof.length}`)
  const maxBefore = Math.max(0, ...proofPosts.map((p) => p.id))
  const fresh = allProof.find((p) => p.id > maxBefore)
  // The smoke gig carried no photos, so before/after are null (the slider only
  // renders when both exist) — but the transaction evidence is always present:
  // a number earned and the gig it is tied to. That is what "unfakeable" means.
  ok('proof post carries the transaction evidence (amount + gig, paid by construction)',
    !!fresh && typeof fresh.amount_earned === 'number' && fresh.gig_id === gig.id,
    fresh ? JSON.stringify(fresh).slice(0, 200) : 'none')
  ok('seeded proof posts carry before/after for the slider',
    proofPosts.some((p) => typeof p.before_url === 'string' && typeof p.after_url === 'string'))

  r = await call(ramesh, 'GET', '/karma/ledger')
  ok('GET /karma/ledger \u2192 split + band + events',
    r.status === 200 && typeof r.data.blended === 'number' && typeof r.data.work === 'number' && typeof r.data.social === 'number' && r.data.band !== undefined && Array.isArray(r.data.events),
    JSON.stringify({ b: r.data.blended, w: r.data.work, s: r.data.social, band: r.data.band }).slice(0, 120))
  const types = r.data.events.map((e) => String(e.event_type).toUpperCase())
  ok('ledger contains GIG_COMPLETED from this gig', types.some((t) => t.includes('GIG_COMPLETED')), types.slice(-6).join(','))

  console.log('\u2014 gig lists & stats \u2014')
  r = await call(priya, 'GET', '/gigs/mine?role=customer')
  ok('GET /gigs/mine?role=customer', r.status === 200 && r.data.some((g) => g.id === gig.id))
  r = await call(workerToken, 'GET', '/gigs/mine?role=worker')
  ok('GET /gigs/mine?role=worker', r.status === 200 && r.data.some((g) => g.id === gig.id))
  r = await call(ramesh, 'GET', '/gigs/stats/summary')
  ok('GET /gigs/stats/summary \u2192 Stats fields', r.status === 200 && ['gigs_total', 'gigs_completed', 'wallet_balance', 'lifetime_earned'].every((k) => typeof r.data[k] === 'number'), JSON.stringify(r.data).slice(0, 120))

  console.log('\u2014 worker profile & safety \u2014')
  r = await call(ramesh, 'GET', '/workers/me/profile')
  ok('GET /workers/me/profile \u2192 MyWorkerProfile fields',
    r.status === 200 && ['category', 'hourly_rate', 'rating', 'total_jobs', 'is_available', 'verification_tier', 'skills'].every((k) => k in r.data),
    JSON.stringify(r.data).slice(0, 200))
  r = await call(ramesh, 'PATCH', '/workers/me/location', { is_available: false })
  ok('PATCH /workers/me/location offline (no coords)', r.status === 200, `got ${r.status} ${JSON.stringify(r.data).slice(0, 120)}`)
  r = await call(ramesh, 'GET', '/safety/trusted-contacts')
  ok('GET trusted contacts \u2192 200 array', r.status === 200 && Array.isArray(r.data))
  r = await call(ramesh, 'POST', '/safety/trusted-contacts', { name: 'Smoke Contact', phone: '9999999999', relationship: 'test' })
  ok('POST trusted contact \u2192 201', r.status === 201 && r.data.id > 0, `got ${r.status} ${JSON.stringify(r.data).slice(0, 120)}`)
  if (r.status === 201) {
    r = await call(ramesh, 'DELETE', `/safety/trusted-contacts/${r.data.id}`)
    ok('DELETE trusted contact', r.status === 200, `got ${r.status}`)
  }

  console.log('\u2014 verification & sos \u2014')
  r = await call(ramesh, 'GET', '/verification/me')
  ok('GET /verification/me \u2192 list', r.status === 200 && Array.isArray(r.data), `got ${r.status}`)
  // 201 on a fresh submission; 409 "already with the review team" on re-runs
  // while the earlier submission is undecided. Both are the documented contract.
  r = await call(ramesh, 'POST', '/verification/submit', { document_type: 'pan', document_ref: 'ABC1234567' })
  ok('POST /verification/submit \u2192 201 (or 409 while one is already pending)', [201, 409].includes(r.status), `got ${r.status} ${JSON.stringify(r.data).slice(0, 120)}`)
  r = await call(ramesh, 'POST', '/safety/emergency', { gig_id: null })
  ok('POST /safety/emergency \u2192 201', r.status === 201, `got ${r.status} ${JSON.stringify(r.data).slice(0, 120)}`)

  console.log('\u2014 refresh & logout contract \u2014')
  r = await call(null, 'POST', '/auth/refresh', { refresh_token: priyaAuth.refresh_token })
  ok('POST /auth/refresh \u2192 new pair', r.status === 200 && r.data.access_token && r.data.refresh_token)
  const newPriya = r.data?.access_token
  const newRefresh = r.data?.refresh_token
  r = await call(newPriya, 'GET', '/auth/me')
  ok('refreshed access token authenticates', r.status === 200)
  // signOut() sends BOTH halves: the bearer in the header, the refresh in the body \u2014
  // logout revokes exactly what is presented.
  r = await call(newPriya, 'POST', '/auth/logout', { refresh_token: newRefresh })
  ok('POST /auth/logout (bearer + refresh) \u2192 200', r.status === 200, `got ${r.status} ${JSON.stringify(r.data).slice(0, 120)}`)
  r = await call(newPriya, 'GET', '/auth/me')
  ok('revoked access token is rejected (401)', r.status === 401, `got ${r.status}`)
  r = await call(null, 'POST', '/auth/refresh', { refresh_token: newRefresh })
  ok('revoked refresh token cannot mint a new pair (401)', r.status === 401, `got ${r.status}`)
} catch (err) {
  console.error(`\nFATAL: ${err.message}`)
  fail++
}

console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
