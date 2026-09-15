# KARMA

### *Thou art the work you do.*

---

Two repositories were fed into this project. One was a maximalist Gen-Z social super-app with
135 API endpoints, reels, live streaming, mesh chat and a coin economy. The other was a
restrained, KYC-gated labour marketplace with 48 endpoints and an SOS button.

They are not in here any more. What is in here is the sentence they were both trying to finish.

**तत्वमसि** — *tat tvam asi* — "thou art that." Your identity is the thing worth expressing.

**कर्म** — *karma* — literally "action, deed, work." Your work is the thing worth trusting.

The Upanishads say you are that. The Gita says you are what you do. KARMA is the place where
those stop being two ideas: **the reputation number *is* the identity.**

---

## The one idea everything else serves

Both source projects independently put a `reputation_score` on their `users` table:

```
Tatwamasi   Float,       default 100.0
LabourLink  Numeric(5,2) default 50.00
```

Two teams, two products, one instinct. That coincidence is the load-bearing wall of this
project.

KARMA makes it rigorous. There is one **Karma Ledger** — append-only, never mutated — and
`users.karma` is a cached projection of it. A completed gig, a five-star review, an approved
KYC, a filed dispute, a published proof post: all of them write a row to the same table.

**Nothing writes `users.karma` directly. Not the feed, not the marketplace, not an admin
patch.** The number is always the sum of its history, which makes it auditable, replayable,
and impossible to drift.

That single rule is what makes "zero Frankenstein seams" an architectural fact rather than a
slogan. The social half and the marketplace half cannot disagree about who you are, because
they are reading the same table.

---

## The seam you can actually see

A worker submits completion proof, the customer approves it, and Stripe confirms capture. Only
then do four things happen in one database transaction:

1. A **proof post** is published to your profile and into your followers' feeds.
2. A `GIG_COMPLETED` karma event is appended to the ledger.
3. Your marketplace stats advance.
4. The wallet ledger records your payout and the platform's fee.

Then your customer reviews you, and the *same* review moves your work karma **and** your
blended number.

Neither original could do this. Tatwamasi had no work to prove. Labour Link had no audience to
prove it to. The seam is step 1 — and if the two halves were merely co-located rather than
merged, step 1 could not exist.

The proof post is also **unfakeable by construction**: the API only publishes `kind=proof` for
a gig whose `payment_status` is `paid`, and proof posts cannot be deleted, because they are
evidence tied to a real transaction. That constraint is what stops the feed from becoming
another Instagram.

---

## The design thesis: Sovereign Calm

The two source projects looked nothing alike — neubrutalist violet-pink-cyan maximalism versus
Material 3 corporate blue. Merging them naively gives you a bank wearing a rave outfit.

The resolution is one principle:

> **The interface is calm. The proof is loud.**

Chrome, navigation, controls, prices and anything involving money or safety are restrained,
high-contrast and geometrically strict. Content — the work itself, the faces, the before/after
photographs — is allowed to be vivid and alive. Your eye is never unsure what is *furniture*
and what is *art*.

The one place maximalism survives is **semantically earned**: the karma ring changes hue as you
earn it, walking a gradient from rose through amber and lime to gold. That gradient is not
decoration. It is a data visualisation with an emotional payload.

Every colour token clears **WCAG 2.1 AA** on its intended background. The originals' raw
palette did not — lime `#A3E635` on white is roughly 1.6:1, which is why it was darkened three
steps to `#4D7C0F`. Colour is never the sole carrier of meaning.

---

## Five things worth pointing at

**① The Karma Ring.** Not a badge. An SVG conic ring that fills as you earn, changes hue along
the gradient, pulses when an event lands, and counts up with tabular numerals. Tap it for the
ledger — every point is accounted for.

**② The Proof Slider.** Drag to wipe between before and after. Pointer-driven for mouse, touch
and pen; operable with arrow keys; exposes `aria-valuenow`; collapses under
`prefers-reduced-motion`. It makes a stranger's competence visceral in a way a star rating
never can.

**③ Explainable everything.** Labour Link's best idea — never show a number you cannot justify —
generalised from pricing and matching to the whole product. Every ranked match shows
`reasons[]` verbatim. Every price shows its multipliers, animating in as they activate. Every
karma value opens its ledger. In an app built on trusting strangers, this *is* the product
strategy.

**④ The karma split.** Work karma and social karma are shown separately, with the blend
weights visible (60/40). This is the honest answer to "can I farm social karma to get hired?" —
no, and here is why, in public. The match ranker reads **work** karma, never blended.

**⑤ One button, two verbs.** The `+` opens Share and Post-a-gig side by side, equal weight.
There is no role-selection screen anywhere in KARMA. Labour Link asked you to pick a side at
signup; KARMA refuses to, because capabilities are additive and a person who hires a plumber on
Tuesday can be a verified electrician on Thursday.

---

## Motion, with a budget

- **120 ms** state changes, **220 ms** entrances, **320 ms** maximum. Nothing animates longer
  except deliberate celebration.
- One easing curve: `cubic-bezier(0.32, 0.72, 0, 1)`. Fast out, gentle settle.
- **Only `transform` and `opacity` are animated.** No animating `height`, `width`, `top` or
  `box-shadow` — those trigger layout and paint and drop frames on the low-end Android devices
  this product's workers actually use.
- Skeletons are sized to the final layout so nothing reflows when data arrives, and the shimmer
  **stops after three cycles** so a slow connection does not become a strobe.
- **SOS has no animation.** Red, present, instant. Animation in an emergency would be
  grotesque. It is also the one irreversible action behind a single tap, and that is designed
  rather than accidental.

---

## What was cut, and why

Tatwamasi's breadth was a liability at merge time. "Zero seams" means the merged product must
have *one* reason to exist.

- **NFT collections** — speculative and regulatorily toxic in an app that touches real wages.
- **Live RTMP/HLS/WebRTC streaming and virtual gifts** — an enormous media-server surface for a
  feature orthogonal to labour.
- **`/ai/vibe-roast` and `/ai/daily-horoscope`** — a horoscope in a KYC-gated labour marketplace
  is a seam you can feel.
- **`lazy="selectin"` on five relationships** in the original `User` model — every user fetch
  issued six queries. Replaced with explicit loads at the query site.
- **`status_emoji` defaulting to `"💅"` in the DDL** — a UI opinion baked into a database
  schema.
- **`compute_match_score()`** — retained by Labour Link as "legacy… for clients/tests" with an
  *inverted* (lower-is-better) polarity from its replacement. Two scorers with opposite
  polarities in one codebase is how a future contributor silently books the worst worker.
- **`dev_otp` in the OTP response body** — returned unconditionally by the original. Now
  hard-gated on `ENVIRONMENT`, not on a boolean that could drift.

---

## Running it

### Zero external services (this is the default)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python seed.py                                  # demo data: 6 users, 12 posts, 5 categories
PYTHONPATH=. uvicorn app.main:app --port 8000    # http://localhost:8000/docs
```

Choose your client. The Flutter app and the React Native app are both first-class mobile
experiences:

```bash
cd flutter_app
flutter pub get
flutter run --dart-define=API_ORIGIN=http://localhost:8000
```

```bash
cd react-native-app
npm install
npx expo start                                  # Expo Go / emulator; EXPO_PUBLIC_API_ORIGIN=… for a device
```

For the existing browser client:

```bash
cd frontend
npm install
npm run dev                                      # http://localhost:5173
```

On the Android emulator the Flutter app takes `API_ORIGIN=http://10.0.2.2:8000` and the RN
app reaches the host by default; a physical device needs the backend's LAN or deployed HTTPS
origin — `EXPO_PUBLIC_API_ORIGIN` (or `extra.apiOrigin` in `app.json`) for the RN client,
`--dart-define=API_ORIGIN=…` for Flutter. SQLite, haversine geo and an in-memory cache keep the
backend free of required external services in development. The RN client's own build and
verification notes live in [`react-native-app/README.md`](react-native-app/README.md).

**Demo accounts** (password `StrongPass!234` for all three):

| Handle | What it shows you |
|---|---|
| `priya` | A customer who has hired and reviewed. Post a gig from here. |
| `ramesh.electric` | A gold-verified electrician with proof history and a wallet balance. |
| `karma.admin` | The protected trust console: analytics, KYC, SOS incidents and disputes. |

Administrators see a shield action in the Flutter header. The responsive console works on
Android, iOS and Flutter web, but every read and mutation is still enforced by the backend's
out-of-band `admin` capability. It exposes proof-health analytics, masked-document decisions,
enriched emergency context, and final incident/dispute case transitions. There is deliberately
no public “become admin” flow.

The React client carries the same trust desk at `#/admin`: a "Trust" tab renders only for
accounts holding the capability, and exposes the pending-KYC queue with approve/reject and an
optional reviewer note, dispute and SOS triage with the backend's transition table, and the
proof-rate analytics — so a web deployment no longer needs curl to run a review.

### Production path

```bash
cd backend
PYTHONPATH=. python -m alembic upgrade head      # the schema, not init_db()

cd ..
docker compose up --build                        # http://localhost:8080
```

Before you rely on that command, prove the stack: `bash tools/compose_smoke/smoke.sh` builds
the images, boots everything, walks the API through the same-origin proxy (readiness, the
PostGIS/Redis/S3/Nominatim backend selections, the 26-table schema, an owned media round
trip, the geocoding consent contract) and tears the stack down again. On machines without a
Docker daemon, `cd backend && .venv/bin/python ../tools/compose_smoke/check_static.py` runs
every check that does not need one, including the production settings guard. See
`tools/compose_smoke/README.md`.

Compose needs `SECRET_KEY`, `POSTGRES_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`,
`ALLOWED_ORIGINS`, `TRUSTED_HOSTS`, `GEOCODING_USER_AGENT`, `STRIPE_SECRET_KEY`,
`STRIPE_PUBLISHABLE_KEY`, and `STRIPE_WEBHOOK_SECRET` — every one is declared with `:?` so
Compose refuses to start rather than booting an app that then refuses to start. `WEB_PORT`
overrides the
published port (default 8080) and is the only port in the stack that is exposed; the API is
reached through the web container's reverse proxy, which is what makes the frontend's
same-origin `/api/v1` calls work without CORS.

The dev path calls `init_db()` and lets SQLAlchemy create the tables. Production runs
Alembic, because `create_all` will happily leave an existing schema half-updated and never
tell you. The baseline is `alembic/versions/50dc766b719f`; Bitchat revision `4e7b1c9d2a10`, secured
payments revision `9f3c2a7d1b40`, and media/location revision `c4a1d8e6f250` bring the canonical
head to 26 tables. The chain is reversible to `base`, and `tests/test_alembic.py` regenerates a
migration against a fully upgraded database and asserts it proposes *nothing*. That check is what
stops the models and migrations from drifting apart in silence.

The same baseline runs `CREATE EXTENSION IF NOT EXISTS postgis`, guarded on the dialect so
SQLite ignores it. That guard is load-bearing: `PostgisGeo` calls `ST_DWithin`, and those
functions do not exist until the extension is created. Without it the schema migrates
cleanly, the API boots, health checks pass — and the first `/matching/find` request fails
with `function st_dwithin does not exist`, on the one deployment that exercises that code
path.

PostgreSQL 17 + PostGIS, Redis, and SeaweedFS's S3 endpoint. The application code does not
change — `GeoPort` switches from haversine to `ST_DWithin`, `CachePort` from a dict to Redis,
`RealtimePort` from local-only delivery to Redis-backed cross-worker fanout, and
`ObjectStoragePort` from local files to private S3-compatible objects. `GeocoderPort` is disabled
in zero-service development and uses the configured Nominatim-compatible endpoint in production.
Integration details stay behind
those ports rather than leaking into routes.

**Not verified:** there is no Docker daemon in the environment this was built in, so the
images have never been built or run. What *is* checked: every path each Dockerfile copies
exists, `docker-compose.yml` parses, the entrypoint passes `sh -n`, and the dialect guard was
confirmed against the real `postgresql+asyncpg` URL. The container runtime itself is
unexercised, and that gap is stated rather than papered over.

### Media objects and consented location

Media is an owned object, not an arbitrary URL. `POST /api/v1/media/uploads` accepts one
multipart JPEG, PNG, or WebP (5 MB by default), detects the file from its bytes, hashes it, and
records its owner and purpose (`post`, `gig`, `proof_before`, or `proof_after`). Reads verify the
stored length and SHA-256 digest before returning evidence. Feed, request,
and completion routes reject remote links, another user's objects, duplicate references, and
purpose swaps. Objects are immutable and served through a same-origin, content-type-pinned URL;
clients never receive storage credentials or internal bucket names. Uploads are user-rate-limited
through the same Redis correctness boundary. Development writes to ignored `UPLOAD_DIR`; production
fails closed unless S3-compatible storage is selected, verifies/creates the private bucket before
readiness, and stores only object metadata in PostgreSQL. Compose uses maintained SeaweedFS rather
than the now-archived MinIO Community server; managed AWS S3 and compatible providers use the same
adapter.

Location has two explicit paths—neither invents coordinates:

- **Use current location** shows KARMA's disclosure first, then asks the operating system for a
  one-time foreground fix. Reverse lookup is separately represented as a consented API call.
- **Search address** leaves the text as text until the user agrees to send it to the configured
  geocoder and chooses one attributed result. Typing by itself never moves the matching point.

`POST /locations/geocode` and `/locations/reverse` require literal `consent: true` in the wire
contract. Provider requests are globally rate-windowed through Redis, successful responses are
cached under hashed request keys, and every result carries provider attribution. Gigs persist
`device`/`geocoded` provenance, accuracy where available, and the selected provider. Workers must
share a fresh consented device fix each time they go online; going offline requests no location.
Android/iOS descriptions match those behaviors and background location permission is not requested.
With `GEOCODING_PROVIDER=disabled`, address search returns an explicit unavailable response; a
consented device fix can still be used with a coordinate label if reverse lookup is unavailable.
There is no city-centre fallback. Provider, object-store, and geocoder choices are reported by the
health/capabilities endpoints.

### Stripe-secured payments

Development defaults to a deterministic simulator, so the zero-service journey still exercises
`requires_capture → capture → release` without moving money. Production cannot use that mode:
`ENVIRONMENT=production` refuses to boot unless `PAYMENT_PROVIDER=stripe` and matching `sk_`,
`pk_`, and `whsec_` values are present.

The real flow keeps card data entirely inside Stripe PaymentSheet:

1. After a worker is assigned, `POST /payments/gigs/{id}/intent` creates one fixed-price
   PaymentIntent with `capture_method=manual`. The Flutter app receives only its client secret
   and the publishable key.
2. PaymentSheet confirms the card. The app then calls `/sync`; the backend retrieves Stripe
   server-side and permits travel only when the intent is actually `requires_capture` (or was
   already captured).
3. The worker submits proof into `completion_pending`. This cannot publish proof, award Karma,
   or write money to the wallet.
4. The customer approves and `/release` captures with a deterministic idempotency key. Only a
   provider-confirmed `succeeded` intent can complete the gig and append payout/fee ledger rows.
5. Signed webhooks reconcile dropped client responses and dashboard operations. Event receipts,
   row locks, provider amount/currency checks, and unique ledger references make retries safe.

This is a manual card authorization and delayed capture, not a claim that KARMA is a regulated
escrow institution. Configure Stripe's capture window and operational policy to fit the duration
of gigs offered in production.

For local Stripe test mode, install the Stripe CLI and run the listener first:

```bash
stripe login
stripe listen \
  --events payment_intent.amount_capturable_updated,payment_intent.succeeded,payment_intent.payment_failed,payment_intent.canceled,refund.created,refund.updated \
  --forward-to localhost:8000/api/v1/payments/webhooks/stripe
# Copy the printed whsec_ value.
```

Then start the API in another terminal with keys from the same Stripe test account:

```bash
cd backend
PAYMENT_PROVIDER=stripe \
STRIPE_SECRET_KEY=sk_test_... \
STRIPE_PUBLISHABLE_KEY=pk_test_... \
STRIPE_WEBHOOK_SECRET=whsec_... \
PYTHONPATH=. uvicorn app.main:app --port 8000
```

Run Flutter on Android/iOS and complete PaymentSheet with a Stripe test card such as
`4242 4242 4242 4242`, any future expiry, and any CVC. For production, create a Dashboard
webhook endpoint at
`https://<public-api-origin>/api/v1/payments/webhooks/stripe`, subscribe to the same event set,
and place that endpoint's own signing secret in `STRIPE_WEBHOOK_SECRET`. Do not reuse a CLI
signing secret in production and never put `STRIPE_SECRET_KEY` in Flutter or frontend builds.

### Tests

```bash
cd backend
PYTHONPATH=. python -m pytest -q
```

```
330 passed, 2 skipped    latest local run (media/location + payments + Bitchat + Redis coverage,
                         plus test_review_fixes.py for the review-round regressions)
342 passed, 2 skipped    after test_custom_price_and_phone.py: poster-set gig pricing and
                         the post-registration phone-OTP door to `can_hire`
```

The default suite includes API journeys, pricing, geospatial contract checks, security, ETL,
migrations, realtime, trust, loophole regressions, protected admin operations, owned object
uploads, geocoder consent/provenance, Stripe-style signed webhook/idempotent release/refund races,
and Bitchat's signed one-time-key lifecycle,
authorization, expiry and panic path. `test_admin.py` exercises
analytics, KYC decisions, enriched SOS queues, dispute triage, final case transitions, and
access control.

PostGIS also has a separate **live** gate. It starts disposable PostgreSQL 18.3 + PostGIS 3.6.2,
exposes the real engine over PostgreSQL's wire protocol, then calls `PostgisGeo.workers_within`
through the application's SQLAlchemy + asyncpg path:

```bash
cd backend/tools/postgis
npm ci
npm test
```

The run executes the production geography casts, `ST_DWithin` and `ST_Distance`, and checks the
three-decimal distances, output keys, proof counts, radius boundary, category, availability,
approval, suspension and live `can_work` capability. The last run returned eligible workers
`[1, 2, 9]` at `0.302`, `0.997` and `4.873` km and rejected all seven deliberately ineligible
rows. It is opt-in so the default test suite keeps its zero-external-service promise. See
`backend/tools/postgis/README.md` for the equivalent native-PostgreSQL command.

Three live journeys do the same for the contracts the in-process suite simulates. With a seeded
server running:

```bash
KARMA_BASE=http://localhost:8000/api/v1 PYTHONPATH=. python scripts/live_media_and_bitchat_journey.py
```

`live_media_and_bitchat_journey.py` re-implements the Flutter crypto boundary in independent
code (Ed25519 identities, signed one-time X25519 prekeys, HKDF-SHA256, AES-256-GCM) and walks
owned upload → immutable delivery → consented geocoding → gig provenance, then Bitchat device
registration, atomic prekey claims, an encrypted round trip over the wire, tamper rejection,
the 10-second physical expiry and panic with its non-recyclable device tombstone.
`live_socket_journey.py` covers the realtime ticket and WebSocket upgrade path the same way.
`live_session_and_ledger_journey.py` covers what only a booted server can answer: that a logout is
refused by the running dependency and not merely by an expired signature, that a dismissal returns
the karma to exactly the reading the accusation disturbed (with the reversal guarded by the
migrated schema's index, not just by the ledger service), and that the feed's `before_id` cursor
still lands on the same rows while posts arrive above it. It logs in about six times a run against
a server that allows ten a minute per address, so tokens are memoised and a spent budget is waited
out rather than reported as a failure.
All three exit non-zero on any failed check, so they can gate a deployment.

Nothing in the request path sits below 88%. That number is only honest because of
`.coveragerc`: SQLAlchemy's async driver switches greenlets on every `await`, and
coverage.py's C tracer does not follow them, so without `concurrency = greenlet` the tool
reported `gigs.py` at 32.5% when the journey test actually covers 89.8% of it. The tell was
that the figure was byte-identical whether one test file or all thirteen ran.

Measure it yourself:

```bash
PYTHONPATH=. python -m pytest --cov --cov-report=term-missing
```

The one that matters is `test_api_flow.py::test_full_journey_hire_work_prove_earn_review` — a
single test that hires, matches, works, proves, earns and reviews. If the two halves were
merely co-located, that test could not exist.

Its companions assert the invariants that make it a fusion rather than an integration:

- completing a gig publishes a proof post **and** writes a karma event, in one transaction;
- a review moves **both** the work half and the blended number;
- a `proof` post without a paid gig is rejected at the schema layer (422);
- proof posts cannot be deleted (409);
- a dispute lowers karma, so a marketplace event changes the person socially;
- social karma **cannot** inflate work karma — farming the feed does not buy you a higher
  hiring rank;
- a refresh token presented as an access token is rejected;
- wrong password and unknown user are indistinguishable.

---

## The shape of it

```
karma/
├── backend/
│   ├── app/
│   │   ├── core/          config · db · security · deps · ports · middleware
│   │   ├── models/        one canonical schema (23 tables, not 40)
│   │   ├── services/      karma ★ · realtime · Bitchat expiry · matching · fare · otp
│   │   ├── schemas/       Pydantic v2 contracts, including strict ciphertext envelopes
│   │   └── routers/       auth · karma · feed · gigs · Bitchat · matching · trust · realtime
│   ├── etl/               identity ★ · karma · runner      the two-databases-in migration
│   ├── alembic/           six revisions, head b7f3d1c4a9e8; reversible to base
│   ├── scripts/           check_alembic · live_socket_journey · live_media_and_bitchat_journey
│   │                      · live_session_and_ledger_journey
│   ├── tests/             332 tests, weighted toward integration and security
│   └── seed.py
├── flutter_app/                 first-class Android, iOS and web client
│   ├── lib/
│   │   ├── core/                theme · secure tokens · HTTP · sockets · Bitchat crypto/BLE
│   │   ├── data/                typed backend contracts · repository · scoped feed cache
│   │   ├── features/            Auth · Feed · Booking · Gigs/Bitchat · Karma · Profile/Safety
│   │   └── shared/              KarmaRing ★ · ProofComparison ★ · accessible primitives
│   ├── android/                 reproducible native Android host
│   ├── web/                     installable Flutter web shell
│   └── test/                    model, formatting and widget tests
├── react-native-app/            first-class Android and iOS client (Expo SDK 57, RN 0.86)
│   ├── src/
│   │   ├── api/                 client (single-flight refresh) · realtime tickets · payments
│   │   ├── auth/                secure-storage session · additive capabilities
│   │   ├── components/          KarmaRing ★ · ProofSlider ★ · MatchCard · FareBreakdown
│   │   └── screens/             Auth · Feed · Book (4 steps) · Gigs (live) · Karma · Profile
│   └── __tests__/               HTTP boundary · state machine · formatting · gradient
├── frontend/                    existing React web/PWA and Capacitor client
├── tools/
│   └── compose_smoke/           static gate (anywhere) · runtime gate (Docker host)
└── docker-compose.yml
```

`★` marks the fusion core and the two components that carry the thesis.

### Ports, not dependencies

| Concern | Interface | Development | Production |
|---|---|---|---|
| Geospatial | `GeoPort` | SQLite + haversine (bounding-box prefilted) | PostGIS `ST_DWithin` |
| Cache / OTP / rate limit | `CachePort` | in-process dict | Redis |
| Object storage | `ObjectStoragePort` | local disk | S3 / SeaweedFS |

Both source projects hard-required Redis and neither could boot without it. The fallback is a
deliberate improvement over both.

---

## The migration

Two databases in, one out. `python -m etl.runner --tatwamasi <db> --labourlink <db>`.

**It defaults to a dry run.** Nothing is written until you pass `--commit`, and the dry run
executes the identical code path against a throwaway in-memory database — so the report you
read is the report the real run would have produced. The run ends with either
`COMMITTED to <target>` or `DRY RUN: nothing was written`, never silence.

The report separates two things that are easy to conflate. `committed` describes the
*transaction*; a dry run commits too, to memory. `persisted` answers the question the
operator is actually asking — did anything reach a real database. Before that split the dry
run printed `"committed": true`, which is the kind of true-but-misleading line an operator
reads at 2am and believes.

**It is atomic.** Every stage shares one transaction. An unresolved foreign key rolls the
whole migration back and exits 1; it does not leave a half-populated database that looks like
a successful one. That property is worth being precise about, because the first version of
this tool printed "ABORTED — nothing should be promoted" while having already committed every
batch to disk. A message like that has to be true, so now it is.

**Sources are opened read-only.** Rollback is "point the API back at the old database", not a
restore from backup.

**Identities are resolved by four ordered rules**, not by a guess:

1. The phone number is authoritative. Same phone, two systems, one person.
2. A shared email merges *only* if the phones do not conflict.
3. A handle collision never merges — the second account gets a suffix instead.
4. Conflicting phones on one email go to a **review queue**. A wrong merge is far worse than
   a duplicate, because it cannot be undone by the person it happened to.

Every remapped id is preserved in `users.external_ids` as `{"labourlink": 3, "tatwamasi": 2}`.
Nothing downstream depends on a legacy integer surviving.

**Karma is reconciled, not invented.** `0.6 × work + 0.4 × social`. Labour Link's
`reputation_score` becomes the work half; Tatwamasi's becomes the social half, scaled by 0.5
because a 100.0 default there means "no opinions yet", not "flawless". A missing side
contributes a neutral 50, never a zero — so migrating never *punishes* anyone. Each half is
written as its own `migration_backfill` ledger row carrying the delta from neutral, which
matters more than it sounds: writing the projection alone would be overwritten the next time
the ledger is recomputed, silently flattening every migrated user to 50. That bug was real and
it is why the tests assert on ledger rows and not just on the cached number.

A merged user also inherits the password they can actually sign in with — if the canonical
account has no usable hash and the incoming row does, the real one is adopted. Otherwise a
merge would have locked people out of accounts they owned in both systems.

---

## Live updates

The gig lifecycle is pushed, not polled. `POST /realtime/ticket` exchanges the caller's
access token for a **single-use, 30-second ticket**; `GET /realtime/gigs/{id}` (upgrade)
spends it.

The split exists because browsers cannot attach an `Authorization` header to a WebSocket
handshake. The obvious alternative — `?token=<jwt>` — puts a long-lived credential into proxy
logs, browser history and `Referer` headers. A 30-second single-use ticket is worthless if it
leaks.

**Subscription is authorised.** Labour Link accepted any connection for any job id, so any
client could enumerate ids and read someone else's hiring activity in real time. Here you must
be the customer or the assigned worker, and a refusal is an HTTP 403 on the handshake — no
unauthenticated socket is ever held open.

**Events publish after the commit, not during the request.** This is the part that is easy to
get wrong and expensive to notice: broadcasting from inside the handler means a client can be
told a gig is `completed` and then watch the transaction roll back. Routes queue an event on
the session; the session dependency publishes it only once the commit has returned, and drops
the queue on rollback. Nothing happened, so nothing is announced.

**Production fanout crosses processes through Redis Pub/Sub.** Every API worker keeps only the
sockets physically attached to it and subscribes to the deployment-namespaced
`REALTIME_REDIS_CHANNEL`. A committed event is wrapped with a random process id, published once,
and delivered to each worker's local sockets; the origin worker ignores its Redis echo because
it already delivered locally. Malformed and oversized bus messages are discarded, dead sockets
are pruned concurrently, and a Redis interruption reconnects with bounded backoff.

Pub/Sub is deliberately ephemeral rather than pretending to be an event log. A disconnected
client gets an authoritative database snapshot when it reconnects, then resumes live events.
The application pings and subscribes before startup succeeds, `/health/ready` reports a lost
subscription, and Compose runs two Uvicorn workers by default (`WEB_CONCURRENCY` is tunable).
Redis Pub/Sub ignores logical database numbers, so deployments sharing one Redis server must use
different channel names.

One consequence worth stating plainly: the `4401`/`4403` close codes in the source never reach
a real client, because Starlette turns a close-before-accept into an HTTP 403 on the upgrade.
The unit tests assert on the close code because Starlette's `TestClient` skips the HTTP layer;
`scripts/live_socket_journey.py` asserts on the 403 a browser actually receives.

---

## The app, carried

`flutter_app/` is KARMA's first-class mobile client, not a WebView. One Dart codebase targets
Android, iOS and web and speaks the same canonical FastAPI contracts as the existing React
client. It carries the complete loop: phone/email auth, social posts and comments, the
before/after proof wipe, transparent gig pricing, explainable worker matches, native Stripe
PaymentSheet authorization and customer-controlled release, live lifecycle updates, reviews,
the auditable Karma split, KYC, worker onboarding and trusted contacts.

The native boundary is deliberate. Tokens live in Keychain/Keystore-backed secure storage;
concurrent 401s share one refresh; haptics mark earned moments; pull-to-refresh and a
user-scoped feed cache make weak networks honest rather than surprising. Gig sockets still
exchange the JWT for a 30-second, single-use ticket before opening, so long-lived credentials
never reach a URL.

Bitchat is the intentional exception to “writes are never queued offline”: its data *is* an
end-to-end-encrypted, expiring store-and-forward packet. Active gigs expose explicit server,
BLE mesh and hybrid modes. Devices own Ed25519 identities and signed one-time X25519 prekeys;
each recipient envelope uses ephemeral X25519, HKDF-SHA256 and AES-256-GCM. The relay sees
routing metadata and authenticated ciphertext, never plaintext or message keys. Local
transcripts have a separate encrypted vault, visible burn timers map to physical expiry, and a
confirmed panic starts the safety alert while immediately erasing device keys and queued data.
Full protocol and degraded-platform behavior are documented in
[`flutter_app/README.md`](flutter_app/README.md).

`API_ORIGIN` is injected with `--dart-define`, normalized once by `ApiClient`, and used to
derive both HTTP and WebSocket endpoints. Android and Flutter web launch assets carry the
Karma Ring mark. Full build, architecture and verification instructions live in
[`flutter_app/README.md`](flutter_app/README.md).

`react-native-app/` is KARMA's first-class Android and iOS client on Expo SDK 57 / React
Native 0.86 — the same complete loop (auth, feed, booking, live gigs, secured payments,
Karma split, KYC, safety contacts) with tokens in Keychain/Keystore-backed storage,
single-flight refresh, the single-use WebSocket ticket contract and the Sovereign Calm
design language. The origin is decided in `src/api/config.ts` alone
(`EXPO_PUBLIC_API_ORIGIN` or `extra.apiOrigin`, with emulator defaults), and the WebSocket
base derives from it. Bitchat is intentionally out of scope for this client — no first-class
iOS BLE peripheral in React Native — and the same honest degradation applies as on Flutter
web: server transport only.

The React PWA/Capacitor client remains available under `frontend/` for existing web
deployments; all three clients share backend contracts rather than duplicating business
rules. Three marketplace freedoms live here too:

- **Poster-set pricing.** Posting a gig offers "Transparent estimate" *or* "Set my own
  price". A poster-set number is stored with the platform fee computed on top and marked
  `pricing_mode: "custom"` in the fare breakdown; assignment recomputes estimated fares
  from the worker's tier and distance, but a price the poster set themselves is never
  re-priced. `POST /gigs/estimate` honours the same `custom_price` so what the UI previews
  is what the gig stores.
- **The second door to `can_hire`.** Hiring requires a verified contact detail. Accounts
  that registered with an email are no longer stuck at a 403: the booking flow and the
  profile's "Hire workers" capability now surface an inline phone-OTP card that exchanges
  the code through `POST /auth/phone/verify`, binds the proven number to the account, and
  then grants the capability. The `PHONE_VERIFIED` ledger row records *which* number was
  proven, and `has_verified_contact` compares it against the account's current number; the
  endpoint sets a number where there was none but refuses quiet swaps — changing numbers
  is a support review, and the +5 karma stays a one-time credit.
- **The trust desk, on the web.** Described with the demo accounts above.

---

## Security, briefly

- **Argon2id** (t=3, m=64 MiB, p=4). Legacy bcrypt hashes verify, then are **transparently
  rehashed on next login** — a migrated user never re-enters a password.
- JWTs carry `iss`, `aud`, `jti`, a `type` claim that is enforced (so a refresh token can never
  authenticate an API call) and `ver`, the account's session epoch.
- **A logout is a server-side fact.** `POST /auth/logout` puts the `jti` it was called with into a
  denylist on the cache port, written with *that token's own remaining TTL* — a revocation can
  neither outlive the token it revokes nor accumulate for as long as the service runs.
  `POST /auth/logout-all` advances `users.token_version`, which invalidates every token minted
  before the bump in one write and needs no table at all. `get_current_user` enforces both, and
  all three clients revoke the pair as part of signing out rather than only deleting it. Signing
  out on a phone leaves a laptop alone — the right default for a daily sign-out and the wrong one
  for a stolen phone, hence two endpoints rather than a checkbox.
  `POST /auth/logout` accepts **either** credential, and needs no live access token: a refresh
  token is self-authenticating for `/auth/refresh`, so it has to be good enough to revoke as well,
  otherwise the device that most needs to sign out — one whose access token expired an hour ago —
  is the one the endpoint refuses, and it answers a 401 by carrying on with thirteen days of
  refresh token left. For the same reason the sign-out call is the one request that does *not* go
  through the clients' transparent 401→refresh→retry: refreshing in order to log out mints the
  pair the request exists to invalidate.
  Note what each mechanism costs: the epoch is a column, so it survives anything, while the
  denylist lives in the cache — it survives a restart only where Redis is configured, which is
  why production refuses to boot without it, and why restarting a development server quietly
  resurrects revoked-but-still-unexpired access tokens for up to an hour.
- **An exoneration gives the karma back.** Filing a dispute (−15) or an SOS (−25) bites
  immediately, because an allegation has to cost something before anyone can investigate it; an
  admin moving that case to `dismissed` appends the exact negation of what was taken. The delta is
  copied from the row being reversed rather than looked up in `KARMA_DELTAS`, so a penalty and its
  reversal cannot drift apart when the table is retuned, and a partial unique index makes
  "reversed at most once" a database fact rather than a promise. `resolved` deliberately pays
  nothing back — settling a real concern is not the accusation falling away.
  Because filing costs the *other* party immediately and freezes their payout, one party may hold
  exactly one open case per gig: `OPEN_DISPUTE_STATUSES` is shared by the filing guard and the
  payment freeze so the two cannot disagree, and the serialiser is the `SELECT … FOR UPDATE` on the
  gig row that the release path already takes. Without it, restating one grievance was free and
  repeatable — five 201s took a verified worker from work 100 to 33 on a live server — while each
  dismissal only handed back one of those penalties. A dismissed party may file again, and the
  other side's case is separate: the limit is "one open", never "one ever".
- **No role enum.** Additive capabilities checked by dependency: `can_post`, `can_hire`,
  `can_work`. Taking work requires approved KYC and cannot be self-granted.
- Document numbers are **masked to their last four characters** on the way in. The full number
  is never stored.
- Rate-limit keys are namespaced per scope. Per-IP budgets are deliberately generous, because
  behind carrier-grade NAT a whole apartment block shares one address and a tight limit locks
  out legitimate neighbours. The right production answer is a challenge, not a smaller number.
- `/auth/login` is budgeted twice: per address on every attempt, and per account on **failures
  only** — so a siege of one account is throttled without letting the attacker lock that person
  out of their own login.
- Identity verification credits karma **once per identity**, not once per submission: the tier and
  badge may only ever rise (a second, weaker document cannot silently demote a worker whose tier
  feeds the fare multiplier), and one Aadhaar approved three times still pays once.
- `assigned` is not an editable gig status. Only `/gigs/{id}/assign` enters it, because that is
  where the worker, the recomputed fare and the payment authorization are decided together.
- The night-fare window is judged in `FARE_TIMEZONE`, never in whichever offset a client
  serialised its start time with — the same instant must cost the same from every timezone.
- Karma is public; the prose in its ledger is not. `GET /karma/ledger/{user_id}` returns the
  deltas, domains and event types anyone needs to audit the number, and keeps the free-text
  reasons for their owner, because those reasons quote gig titles, disputes and safety reports.
- SOS is keyed on **user id**, not client IP — so an attacker cannot rotate IPs to bypass it.
- Redis makes rate windows and single-use WebSocket tickets atomic across workers, while its
  Pub/Sub channel carries only validated lifecycle envelopes—not JWTs or message plaintext.
- Bitchat private keys and plaintext remain on clients. Signed ciphertext is authorized to the
  two gig parties, one-time prekeys are never recycled, and both relay and local copies expire.
- Settings **fail closed**: the process refuses to boot in production with a default secret,
  wildcard origin, local/ephemeral upload storage, unidentified geocoder, simulated payment
  provider, or incomplete S3/Stripe credentials.
- The browser only ever talks to one origin; `/api` is proxied. No CORS preflight, no exposed
  API host.

---

## What is honestly not done

Stated plainly, because an unverified claim is worse than an admitted gap:

- **The Flutter native artifacts still need toolchain verification.** This environment could
  clone Flutter source but could not reach the engine artifact host, so `flutter analyze`,
  widget tests and the final Android/iOS compiles could not execute here. The project uses the
  current stable Gradle template and includes deterministic commands in `flutter_app/README.md`;
  run those gates in Flutter-enabled CI before release. The existing React build remains the
  verified web deployment path.
- **The React Native client's native artifacts need the same toolchain verification.**
  Verified in this environment: `tsc --noEmit` strict, the 21-test jest suite (HTTP boundary,
  single-flight refresh, gig state machine, gradient boundaries, en-IN formatting), and a full
  `expo export --platform android` that compiles the entire module graph to a Hermes bundle.
  Not verified: the final APK/IPA compile, which runs where the Android SDK or Xcode lives
  (`npx expo prebuild` then the standard Gradle/Xcode build, or `eas build`). Bitchat, SMS-OTP
  UI and media-upload attachment are deliberately not in this client; the gaps are listed in
  `react-native-app/README.md`.
- **The container stack still has not been started together.** The environments where this
  repository is built have no Docker daemon (verified: no `docker`, `dockerd`, `podman` or
  socket), so the production Compose images and their PostgreSQL 17 container have not run
  side by side. The gap is now bounded by two gates in `tools/compose_smoke/`:
  `check_static.py` — which *ran here* and passes — verifies the compose wiring, both build
  contexts (every COPY source, unprivileged users, the entrypoint, the single Alembic head),
  the nginx same-origin proxy contract, and executes the production settings guard (each
  documented misconfiguration is constructed and must refuse to boot); `smoke.sh` is the
  one-command runtime proof for a Docker host — build, boot all five containers, readiness
  through the proxy, `/health` reporting PostGIS + Redis + S3 + Nominatim, the PostGIS
  extension and 26-table schema live, a media upload round trip through SeaweedFS, and the
  consented-geocoding contract against the real provider. PostGIS SQL itself has a separate
  live harness (`backend/tools/postgis`) that already ran PostgreSQL 18.3 + PostGIS 3.6.2
  through SQLAlchemy and asyncpg.
- **Bitchat radio interoperability is not proven by this environment.** The authenticated
  relay, migrations, expiry and panic behavior run in the backend suite, and all Dart sources
  pass a grammar parser. Beyond the suite, `scripts/live_media_and_bitchat_journey.py` walks
  the upload contract and the signed relay against a booted server using an independent
  client-side crypto implementation — a genuine encrypted round trip, tamper rejection,
  physical expiry and the panic wipe — so the hardware matrix is left to prove exactly the
  radio-level behaviors no software test can: actual BLE central/peripheral exchange,
  permission denial, radio-off recovery and iOS/Android background suspension, per
  `flutter_app/README.md`. Flutter web honestly reports mesh unavailable because browsers
  cannot advertise as a BLE peripheral.
- **Rotation leaves the spent refresh token alive.** `POST /auth/refresh` mints a new pair and
  deliberately does not revoke the one it just spent, so a refresh token that was captured *and*
  already rotated keeps working until `REFRESH_TOKEN_EXPIRE_DAYS` runs out. A sign-out can no
  longer be the thing that strands one — the clients hand over the token they hold, at send time,
  without refreshing first — but a pair rotated on *another* device is still invisible to this
  one's logout button, and only `logout-all` reaches it. Making
  rotation single-use is the fix, and the web client has to go first: `frontend/src/api/client.ts`
  refreshes without a single-flight guard, so revoking on use would let two parallel 401s leave the
  loser holding a dead token and bounce a live user back to the sign-in screen. The Flutter client
  already serialises its refreshes (`Completer` in `ApiClient._refresh`). Until the web one does the
  same, the session epoch behind `logout-all` is what an account genuinely under attack gets — and
  it does work, on every device, immediately.
- **Neither client offers "sign out everywhere".** `POST /auth/logout-all` is a tested endpoint
  with no button; the sign-out each client has ends one device. Deciding when a person is allowed to
  end every session — and what that costs them — is a product decision, not a call left unwired.
- **The social graph is schema, not behaviour.** `follows` exists and `followers_count` /
  `following_count` / `shares_count` / `streak` are stored, typed in every client and rendered,
  but no endpoint writes them — so follower counts are permanently zero, and the claim that a
  completed gig publishes "to the worker's profile **and their followers' feeds**" currently
  holds only for the profile. `KarmaEventType.STREAK_DAY` has no producer for the same reason.
  A feed is not filtered by who you follow yet; it is the whole network, newest first.
- **Exoneration has exactly one trigger: an admin marking a case `dismissed`.** Nothing reverses a
  penalty on appeal from the person who took it — there is no appeal surface at all — and nothing
  reverses a case that was closed as `resolved` and then found to have been wrong (both statuses are
  terminal, so the console cannot even change its mind without a new row in the table).
  `KarmaEventType.POST_REPORTED_UPHELD` (−10) is in the delta table with no code anywhere that writes
  it, so that penalty is currently both unenforced and unreversible, for the same reason
  `STREAK_DAY` is unearned: an event type somebody decided the value of before deciding the rule.

---

## Read the rest

- [`docs/01-analysis.md`](../docs/01-analysis.md) — both repositories measured, feature matrix,
  migration plan, 12-item risk assessment, technical-debt inventory.
- [`docs/02-design-manifesto.md`](../docs/02-design-manifesto.md) — colour, type, motion,
  wireframes, accessibility.
- [`docs/03-roadmap.md`](../docs/03-roadmap.md) — execution plan with gates, integration
  points, testing strategy.

Every number in those documents came from executing code against the source repositories, not
from reading their READMEs. The commands are listed in §5 of the analysis so any claim can be
re-verified.
