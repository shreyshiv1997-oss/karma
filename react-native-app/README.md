# KARMA — React Native Client

The third face of KARMA, next to the [Flutter client](../flutter_app/) and the
[React PWA/Capacitor client](../frontend/). One codebase per face, one set of
backend contracts — the RN client speaks the same canonical FastAPI API, with
the same token discipline, the same single-use WebSocket tickets, and the same
Sovereign Calm design language.

**Stack:** Expo SDK 57 · React Native 0.86 · React 19 · TypeScript (strict) ·
React Navigation 7 · react-native-svg · expo-secure-store · expo-location ·
@stripe/stripe-react-native.

---

## What is in here

The complete loop, ported from the web client and aligned with the Flutter one:

| Screen / flow | What it does |
|---|---|
| **Auth** | One form, two entry doors (email or phone), no role question. Tokens land in Keychain/Keystore-backed secure storage, are restored and validated by `/auth/me`, and refresh is **single-flight** — the web client's known concurrent-401 gap is closed here. |
| **Feed** | One feed, four kinds of content, keyset pagination (`before_id`), pull-to-refresh, and the dual-intent `PostCard`: for `kind=proof` it carries the before/after **Proof Slider**, the review, the paid amount, the author's karma ring and a Hire button. |
| **✚ Create sheet** | One button, two verbs — *Share a post* and *Post a gig* side by side, equal weight. No role-selection screen anywhere. |
| **Post a gig** | Labour Link's four-step wizard (What → When & where → Who → Payment) as a modal, with the estimate recomputing live and every multiplier shown as it activates. Both location paths are consent-gated with the same disclosure copy: a one-time foreground device fix (no background location, ever) and a typed-address geocode that only moves the point when you pick an attributed result. |
| **Matches** | Ranked workers with `reasons[]` shown verbatim, tier badge, distance/ETA, match score and their karma ring. |
| **Gigs** | The state machine made visible: lifecycle rail, worker-driven transitions, the customer's *Secure payment* and *Approve work & release payment*, and the post-completion review that moves both the work half and the blended number. The active gig is watched over the WebSocket (30-second single-use ticket, authorised subscription, quiet degradation — last known state when the socket is down). **SOS is red, present, instant — no animation.** |
| **Karma** | The ring at the top of the blend: work 60% / social 40%, the band, and the full append-only ledger with per-domain colour. |
| **You** | Identity with the live ring, additive capabilities (hiring is a one-tap opt-in; work needs approved KYC), the worker dashboard (go online with a fresh consented fix), verification submission, and trusted contacts for the SOS. |
| **Payments** | The secured flow exactly as the backend defines it: `intent` → (Stripe PaymentSheet for real deployments; the deterministic simulator needs no card in development) → `sync` → `release` after the customer approves. Card data never leaves Stripe's UI. |

## Running it

### 1. The backend, zero external services

```bash
cd ../backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python seed.py                                  # 6 users, 12 posts, 5 categories
PYTHONPATH=. uvicorn app.main:app --port 8000
```

### 2. The app

```bash
cd ../react-native-app
npm install
npx expo start
```

Then open the QR code in **Expo Go** on your phone (or press `a` for a local
Android emulator / `i` for the iOS simulator).

| Where the app runs | Backend it reaches by default |
|---|---|
| Android emulator | `http://10.0.2.2:8000` (aliases the host) |
| iOS simulator | `http://127.0.0.1:8000` (the host) |
| Physical device | **Set the origin** — see below |

### Pointing a physical device (or production) at an API

Precedence, decided in `src/api/config.ts` — the one place that answers
"where does the API live?":

1. `EXPO_PUBLIC_API_ORIGIN` (Expo inlines `EXPO_PUBLIC_*` at bundle time):
   ```bash
   EXPO_PUBLIC_API_ORIGIN=http://192.168.1.20:8000 npx expo start
   ```
2. `extra.apiOrigin` in `app.json` — bake it in for a prebuilt bundle:
   ```bash
   # app.json: "extra": { "apiOrigin": "https://api.karma.example.com" }
   npx expo export --platform android --platform ios
   ```
3. Platform defaults (`10.0.2.2` / `127.0.0.1`), for development only.

The WebSocket base is derived from the same decision (`http`→`ws`,
`https`→`wss`), so there is no second setting to drift.

### Demo accounts (password `StrongPass!234` for all three)

| Handle | What it shows you |
|---|---|
| `priya` | A customer who has hired and reviewed. Post a gig from here. |
| `ramesh.electric` | A gold-verified electrician with proof history and a wallet balance. |
| `karma.admin` | The protected trust console (backend-enforced). |

The seeded `priya → ramesh.electric` journey — post a gig, match, secure the
(simulated) payment, drive the gig to `completion_pending`, approve and
release, review — exercises the whole seam, with proof posts and karma events
landing in the feed and the ledger as it happens.

## Tests

```bash
npm run typecheck   # tsc --noEmit, strict
npm test            # jest (jest-expo)
```

The suite covers the four behaviours the rest of the app stands on — bearer
attachment, one transparent refresh, single-flight refresh under concurrent
401s, and a sign-out that revokes the token held *at send time* without
refreshing first — plus the karma gradient's boundaries, the en-IN money and
relative-time formatting, and the gig state machine's legal transitions.

## Live verification (against a seeded backend)

Two self-contained Node scripts (Node ≥ 18, no dependencies) walk the client's
exact call sequence against a running, seeded API — the same role as the
backend's `scripts/live_*_journey.py`, for the mobile contract:

```bash
# in ../backend
python seed.py
PYTHONPATH=. uvicorn app.main:app --port 8000
# in ../react-native-app
node scripts/smoke-live.mjs          # 51 checks: auth, feed, gig, payment, review, seam, safety
node scripts/ws-probe.mjs            # ticket → socket → snapshot; spent tickets and strangers refused
```

Both exit non-zero on any failure, so they can gate a deployment. The last
verified run: **51/51** smoke checks and **all realtime checks** passed,
including the seam (release → completion → proof post → `gig_completed` ledger
event in one journey).

## Native build

Expo Go (above) needs no native toolchain. For a release build:

```bash
npx expo prebuild        # generates android/ and ios/ host projects
# or, with EAS:
eas build -p android --profile production
```

The Android host uses the standard Expo SDK 57 template; the `karma` URL
scheme (app.json) is the redirect target the Stripe sheet uses.

## What is honestly not in this client

Stated plainly, in the spirit of the repo:

- **Bitchat is not ported.** The BLE mesh (Ed25519 identities, signed
  one-time X25519 prekeys, AES-256-GCM envelopes, the encrypted vault and
  panic wipe) lives in `flutter_app/` and `backend/`. RN has no first-class
  BLE peripheral API on iOS, so the same "honest degradation" applies here as
  on Flutter web: server transport only.
- **OTP over SMS** is wired to the same endpoints (`/auth/otp/send`,
  `/auth/otp/verify`) but the UI ships the password path; the dev OTP echo is
  backend-gated on `ENVIRONMENT` and does not appear in the response
  otherwise.
- **Media uploads** (gig photos, proof photos) require the backend's owned
  object pipeline (`POST /media/uploads`) and a `react-native-image-picker`
  integration; the client renders served media and the before/after slider,
  but does not yet attach files.
- **The native artifacts need toolchain verification.** This project was
  built in an environment without an Android SDK or Xcode. What *is*
  verified: `tsc --noEmit` strict, the full jest suite, and a complete Metro
  export (`expo export --platform android`) producing a Hermes bundle —
  i.e. the entire module graph resolves and compiles. The final APK/IPA
  compile happens where the toolchain lives, exactly as documented for the
  Flutter client.
