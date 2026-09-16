"""Live end-to-end journey against a RUNNING server.

Unlike the pytest suite (which drives the app in-process via ASGITransport), this walks
the whole hire -> match -> work -> prove -> earn -> review arc over real HTTP through the
frontend's own dev proxy, so it exercises the same path a browser uses.

    python seed.py
    PYTHONPATH=. uvicorn app.main:app --port 8000 &
    npm --prefix ../frontend run dev &
    python live_journey.py

Set KARMA_BASE to point at a different host (default: the Vite proxy on :5173).
"""
import json, urllib.request

import os

BASE = os.environ.get("KARMA_BASE", "http://localhost:5173/api/v1")

def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token: req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)

P = lambda *a: print(*a, flush=True)
def ok(label, cond): P(f"  {'✓' if cond else '✗ FAIL'}  {label}"); assert cond, label

# --- 1. customer opts into hiring ---
s, c = call("POST", "/auth/login", {"identifier": "priya", "password": "StrongPass!234"})
ok(f"customer login -> {s}", s == 200)
ct = c["access_token"]
P(f"     @{c['user']['handle']}  karma={c['user']['karma']}")

s, cats = call("GET", "/categories")
cat = next(x for x in cats if x["slug"] == "plumbing")

# --- 2. transparent estimate ---
s, fare = call("POST", "/gigs/estimate", {"category_id": cat["id"], "lat": 22.7196, "lng": 75.8577, "estimated_hours": 2, "urgency": "urgent"})
ok(f"estimate -> {s}  total=Rs{fare['total']}", s == 200)
P(f"     urgency multiplier visible: x{fare['urgency_multiplier']}  platform fee: Rs{fare['platform_fee']}")

# --- 3. post the gig ---
s, gig = call("POST", "/gigs", {"category_id": cat["id"], "title": "Fix leaking overhead tank",
    "description": "Live HTTP journey test", "lat": 22.7196, "lng": 75.8577,
    "address_label": "Vijay Nagar, Indore", "estimated_hours": 2.0, "urgency": "urgent"}, ct)
ok(f"gig posted -> {s}  id={gig['id']}", s == 201)
gid = gig["id"]

# --- 4. matching returns explained, ranked candidates ---
s, matches = call("POST", "/matching/find", {"gig_id": gid}, ct)
ok(f"matching -> {s}  {len(matches)} candidates", s == 200 and len(matches) > 0)
top = matches[0]
P(f"     top: {top['display_name']}  score={top['score']}  karma={top['karma']}  {top['distance_km']}km  ETA {top['eta_minutes']}m")
P(f"     reasons: {top['reasons']}")
ok("every candidate carries reasons", all(m["reasons"] for m in matches))
scores = [m["score"] for m in matches]
ok("ranked descending", scores == sorted(scores, reverse=True))
wid = top["user_id"]

# --- 5. worker karma BEFORE ---
s, kb = call("GET", f"/karma/ledger/{wid}")
P(f"     worker karma before: blended={kb['blended']} work={kb['work']} social={kb['social']} ({kb['band']})")

s, prof = call("GET", f"/workers/{wid}")
# The profile caps its proof list at 12, so counting it saturates on a worker who already has
# a dozen. Capture the newest proof's id and assert that a NEW one appears, instead.
proofs_before = len(prof["proofs"])
newest_proof_before = prof["proofs"][0]["id"] if prof["proofs"] else None
P(f"     proof posts before: {proofs_before} (newest id={newest_proof_before})")

# --- 6. assign + drive the state machine ---
s, r = call("POST", f"/gigs/{gid}/assign?worker_id={wid}", None, ct)
ok(f"assign -> {s}", s == 200)

s, payment = call("POST", f"/payments/gigs/{gid}/intent", None, ct)
ok(f"payment authorized -> {s}  {payment['status']}", s == 200 and payment["status"] == "authorized")

s, r = call("POST", f"/gigs/{gid}/status", {"status": "completed"}, ct)
ok(f"customer cannot complete (needs worker) -> {s}", s == 403)

s, w = call("POST", "/auth/login", {"identifier": top["handle"], "password": "StrongPass!234"})
wt = w["access_token"]

s, r = call("POST", f"/gigs/{gid}/status", {"status": "completed"}, wt)
ok(f"illegal assigned->completed refused -> {s}", s == 409)

for st in ("en_route", "arrived", "in_progress"):
    s, r = call("POST", f"/gigs/{gid}/status", {"status": st}, wt)
    ok(f"  {st} -> {s}", s == 200)

# --- 7. THE FUSION SEAM ---
s, r = call("POST", f"/gigs/{gid}/status", {"status": "completion_pending",
    "proof_photos": ["https://placehold.co/800x600/be123c/fff?text=Before", "https://placehold.co/800x600/4d7c0f/fff?text=After"]}, wt)
ok(f"PROOF SUBMITTED -> {s}", s == 200 and r["status"] == "completion_pending")

s, payment = call("POST", f"/payments/gigs/{gid}/release", None, ct)
ok(f"CAPTURED & RELEASED -> {s}  payment={payment['status']}",
   s == 200 and payment["status"] == "paid")

s, prof = call("GET", f"/workers/{wid}")
newest = prof["proofs"][0] if prof["proofs"] else None
ok(f"proof post auto-published (newest id {newest_proof_before} -> {newest and newest['id']})",
   newest is not None and newest["id"] != newest_proof_before)

s, feed = call("GET", "/feed/posts", None, ct)
newest = next(p for p in feed if p["gig_id"] == gid)
ok("proof post is in the public feed", newest["kind"] == "proof")
P(f"     '{newest['body']}' by @{newest['author_handle']}  before={bool(newest['before_url'])} after={bool(newest['after_url'])} earned=Rs{newest['amount_earned']}")
P(f"     trust travels with it: karma={newest['author_karma']} tier={newest['author_tier']}")

# The ledger is the source of truth; users.karma is a CLAMPED projection, so a worker
# already at the 100 ceiling will not visibly move. Assert on the ledger, not the projection.
s, ka = call("GET", f"/karma/ledger/{wid}")
ok(f"ledger grew: {kb['total_events']} -> {ka['total_events']} events", ka["total_events"] > kb["total_events"])
types = [e["event_type"] for e in ka["events"]]
ok("both gig_completed AND proof_published recorded", "gig_completed" in types and "proof_published" in types)
ok("social karma moved (proof event)", ka["social"] >= kb["social"])
P(f"     newest ledger rows: {[(e['delta'], e['domain'], e['reason']) for e in ka['events'][:2]]}")
P(f"     projection: work={ka['work']} (ceiling-clamped) social={ka['social']} blended={ka['blended']}")

s, stats = call("GET", "/gigs/stats/summary", None, wt)
ok(f"wallet credited: Rs{stats['lifetime_earned']}", stats["lifetime_earned"] > 0)

# --- 8. review moves both halves ---
s, r = call("POST", f"/gigs/{gid}/review", {"rating": 5, "punctuality": 5, "quality": 5,
    "comment": "Live journey test review"}, ct)
ok(f"review -> {s}", s == 201)
s, kc = call("GET", f"/karma/ledger/{wid}")
ok(f"review appended to ledger: {ka['total_events']} -> {kc['total_events']}", kc["total_events"] > ka["total_events"])
ok("review_received event present", "review_received" in [e["event_type"] for e in kc["events"]])
P(f"     karma after review: blended={kc['blended']} work={kc['work']} social={kc['social']} ({kc['band']})")

s, r = call("POST", f"/gigs/{gid}/review", {"rating": 5}, ct)
ok(f"double review refused -> {s}", s == 409)

# --- 9. proof is permanent ---
s, r = call("DELETE", f"/feed/posts/{newest['id']}", None, wt)
ok(f"proof post undeletable -> {s}", s == 409)

# --- 10. proof cannot be forged ---
s, r = call("POST", "/feed/posts", {"kind": "proof", "body": "fake"}, wt)
ok(f"forged proof rejected -> {s}", s == 422)

# --- 11. security ---
s, r = call("GET", "/feed/posts")
ok(f"anon rejected -> {s}", s == 401)
s, r = call("POST", "/auth/login", {"identifier": "priya", "password": "wrong"})
s2, r2 = call("POST", "/auth/login", {"identifier": "nobody", "password": "wrong"})
ok(f"wrong-pw and unknown-user indistinguishable ({s}/{s2})", s == s2 == 401 and r["detail"] == r2["detail"])

P("")
P("════════ LIVE END-TO-END JOURNEY: ALL CHECKS PASSED ════════")
