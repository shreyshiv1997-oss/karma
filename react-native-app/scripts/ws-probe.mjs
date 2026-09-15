/**
 * WebSocket probe: spends a single-use ticket the same way src/api/realtime.ts
 * does, and asserts the snapshot lands — plus that a spent ticket is refused.
 * Node >= 22 has a global WebSocket client, so no dependencies.
 */
const BASE = (process.argv[2] ?? 'http://127.0.0.1:8000/api/v1').replace(/\/+$/, '')

async function login(identifier) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ identifier, password: 'StrongPass!234' }),
  })
  if (res.status !== 200) throw new Error(`login ${identifier} → ${res.status}`)
  return (await res.json()).access_token
}

async function ticket(token) {
  const res = await fetch(`${BASE}/realtime/ticket`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
  })
  if (res.status !== 200) throw new Error(`ticket → ${res.status}`)
  return res.json()
}

function openSocket(path) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(path)
    const timer = setTimeout(() => {
      ws.close()
      reject(new Error('timed out waiting for frames'))
    }, 8000)
    ws.onmessage = (msg) => {
      clearTimeout(timer)
      ws.close()
      resolve(JSON.parse(String(msg.data)))
    }
    ws.onerror = (e) => {
      clearTimeout(timer)
      reject(new Error(`socket error: ${e?.message ?? 'unknown'}`))
    }
    ws.onclose = (e) => {
      clearTimeout(timer)
      reject(new Error(`socket closed before any frame (code ${e.code})`))
    }
  })
}

let fails = 0
const check = (name, cond, extra = '') => {
  console.log(`  ${cond ? '\u2713' : '\u2717'} ${name}${cond ? '' : ' ' + extra}`)
  if (!cond) fails++
}

try {
  const priyaAuth = await login('priya')
  const priya = priyaAuth
  const rameshLogin = await login('ramesh.electric')
  const ramesh = rameshLogin
  const rameshUserId = (
    await (
      await fetch(`${BASE}/auth/me`, { headers: { Authorization: `Bearer ${ramesh}` } })
    ).json()
  ).id

  // A gig both parties can watch: priya's most recent customer gig.
  const mine = await (
    await fetch(`${BASE}/gigs/mine?role=customer`, { headers: { Authorization: `Bearer ${priya}` } })
  ).json()
  const gigId = mine[0].id
  if (!gigId) throw new Error('no gig to watch')

  // 1. Fresh ticket → snapshot frame on open.
  const t1 = await ticket(priya)
  const origin = BASE.replace(/^http/, 'ws')
  const snap = await openSocket(`${origin}/realtime/gigs/${gigId}?ticket=${encodeURIComponent(t1.ticket)}`)
  check('socket with fresh ticket delivers gig.snapshot', snap?.type === 'gig.snapshot' && snap?.gig_id === gigId, JSON.stringify(snap).slice(0, 120))
  check('snapshot carries the status the Gigs screen adopts', typeof snap?.data?.status === 'string', JSON.stringify(snap?.data ?? {}).slice(0, 120))

  // 2. The same ticket, spent again → refused (HTTP 403 on the upgrade).
  let refused = false
  try {
    const again = await openSocket(`${origin}/realtime/gigs/${gigId}?ticket=${encodeURIComponent(t1.ticket)}`)
    // If a frame arrived, the ticket was (wrongly) reusable.
    refused = false
  } catch (e) {
    refused = true
    console.log(`      (spent ticket refused: ${e.message})`)
  }
  check('spent ticket is not reusable', refused)

  // 3. A stranger who is neither party gets refused even with a fresh ticket.
  // A gig qualifies when its assigned worker is not ramesh.
  const foreignGig = mine.find((g) => g.worker_id != null && g.worker_id !== rameshUserId)
  if (foreignGig) {
    const t3 = await ticket(ramesh)
    let refused3 = false
    try {
      await openSocket(`${origin}/realtime/gigs/${foreignGig.id}?ticket=${encodeURIComponent(t3.ticket)}`)
    } catch {
      refused3 = true
    }
    check('subscription is authorised: neither party can watch a foreign gig', refused3)
  } else {
    console.log('  (skipped authorization check: every gig in the database involves ramesh)')
  }
} catch (err) {
  fails++
  console.error(`\nFATAL: ${err.message}`)
}

console.log(fails === 0 ? '\nAll realtime checks passed.' : `\n${fails} realtime check(s) failed.`)
process.exit(fails === 0 ? 0 : 1)
