# KARMA for Flutter

A production-oriented Flutter client for the existing KARMA FastAPI backend. It carries the complete product loop on Android, iOS and web: authenticate, publish, compare proof of work, post a gig, inspect transparent pricing, select an explainable match, secure and release payment, track work live, communicate through encrypted ephemeral Bitchat, review it, and audit every Karma point.

## Why this client exists

The existing web client proved the KARMA concept. This client makes mobile a first-class product rather than a web page inside a shell. It adds native-feeling navigation and haptics, encrypted credential storage, resilient token refresh, pull-to-refresh, cached feed fallback, live gig sockets, phone OTP onboarding, trusted contacts, KYC and worker onboarding, Stripe PaymentSheet with delayed capture, a real Bluetooth/internet Bitchat transport, plus a capability-gated trust-and-safety console for administrators.

## Run

```bash
cd karma/flutter_app
flutter pub get
flutter run \
  --dart-define=API_ORIGIN=http://localhost:8000
```

API defaults by target are intentionally not guessed. Pass the backend origin explicitly:

- Android emulator: `--dart-define=API_ORIGIN=http://10.0.2.2:8000`
- iOS simulator / Flutter web: `--dart-define=API_ORIGIN=http://localhost:8000`
- physical device: use your machine's LAN address or an HTTPS deployment

`API_ORIGIN` is normalized and `/api/v1` is appended by the client. For a release build:

```bash
flutter build appbundle \
  --release \
  --dart-define=API_ORIGIN=https://api.karma.example.com
```

Demo accounts (after running `backend/seed.py`):

| Account | Password | Best for |
|---|---|---|
| `priya` | `StrongPass!234` | hiring, reviews and customer flow |
| `ramesh.electric` | `StrongPass!234` | worker lifecycle, proof and wallet |
| `karma.admin` | `StrongPass!234` | analytics, KYC review, safety incidents and disputes |

## Architecture

```
lib/
├── core/       theme, secure storage, HTTP, realtime and Bitchat crypto/BLE/vault
├── data/       typed API models and one repository contract
├── features/   auth, feed, booking, gigs, Bitchat, karma, profile, admin, shell
└── shared/     accessible design-system widgets
```

- `ApiClient` is the only HTTP boundary. It adds bearer auth, serializes concurrent refreshes, retries JSON and multipart uploads once, resolves same-origin media paths, shapes FastAPI errors, and never stores tokens in preferences.
- `SecureTokenStore` persists tokens with Keychain/Keystore-backed `flutter_secure_storage`.
- `KarmaRepository` mirrors the existing Pydantic contracts and owns a small, user-scoped cached-feed fallback. Authenticated writes are never queued or faked offline.
- `SessionController` is the single source of truth for auth and current-user state.
- Gig sockets use the backend's single-use 30-second ticket. Long-lived JWTs never appear in a WebSocket URL.
- Widgets stay feature-local unless they are genuine product primitives (`KarmaRing`, `ProofComparison`, `KarmaCard`, empty/error states).

## Photos are uploads; locations require consent

Post composition, gig requests, and before/after proof use the system camera/photo picker. The
app keeps selected bytes local for preview, then sends one authenticated multipart upload with an
explicit purpose. The API detects JPEG/PNG/WebP signatures, enforces its byte limit, and returns
an owned immutable object URL. Arbitrary image URL fields no longer exist in the Flutter UI.
Camera and photo-library permission prompts happen only after the user chooses their source.

The booking screen has no seeded city centre. Typing an address does not set coordinates. The
user must either:

1. accept a disclosure and request a one-time foreground device fix, optionally reverse-geocoded
   for a label; or
2. accept the address-search disclosure and choose one attributed provider result.

The selected source, accuracy, and provider remain visible before matching. Editing its private
service label does not pretend to move the selected point. Worker availability follows the same
rule: going online requires a fresh disclosed device fix; going offline does not request location.
KARMA does not request background location permission. If the backend disables address lookup,
search reports that honestly; a real device fix still works and keeps its coordinate label when
reverse lookup is unavailable. It never falls back to a city centre. Browser/device location also
requires a secure HTTPS context outside localhost.

## Payments stay inside PaymentSheet

After a customer chooses a worker, the booking flow requests one manual-capture PaymentIntent
and immediately opens Stripe's native PaymentSheet. The app receives a client secret and
publishable key; it never receives a secret key, PaymentMethod payload, PAN, or CVC. A
PaymentSheet success is followed by a backend `/sync`, so the UI enables work only after the
server independently retrieves an authorized intent from Stripe.

The worker's final action is **Submit completion proof**, not “get paid.” The gig moves to
`completion_pending`, where the customer can inspect the proof, open a dispute, or explicitly
approve and release. Release captures the fixed amount server-side. Reopening, duplicate taps,
webhook retries, and a dropped response all reconcile against the same PaymentIntent.

Local backend development defaults to a visible simulated authorization; it uses the same API
state machine but never opens PaymentSheet or claims a real charge. Production backend settings
reject that mode. To exercise real test-mode cards, configure the API's `PAYMENT_PROVIDER` and
three Stripe keys and forward signed events with Stripe CLI as described in the root README.
No Stripe secret is compiled into Flutter.

Native integration requirements are committed with the app: Android uses API 21+, AppCompat,
`FlutterFragmentActivity`, the `karma://stripe-redirect` intent filter, and Stripe's R8 rules;
iOS targets 15 and registers the same URL scheme. Rebuild rather than hot-reload after changing
native Stripe setup.

## Bitchat is a transport, not a label

Open any assigned, en-route, arrived or in-progress gig and choose **Bitchat**. The screen makes
the selected route and its degraded state visible:

- **Server** sends opaque, signed ciphertext through the authenticated relay.
- **Mesh** keeps an expiring store-and-forward packet on the device and exchanges baseline-ATT
  fragments over a dedicated BLE GATT service. It does not silently substitute internet chat.
- **Hybrid** queues both paths; recipients deduplicate the same message id.

The cryptographic boundary is client-owned. Each installation creates an Ed25519 identity and
24 signed, one-time X25519 prekeys in Keychain/Keystore. Every recipient device gets a separate
ephemeral X25519 exchange, HKDF-SHA256 key and AES-256-GCM envelope. The signature covers room,
sender, recipient, one-time key, timer and hop budget. The FastAPI service can verify routing
authenticity but never receives a private key, message key or plaintext.

Local transcripts are separately AES-GCM encrypted; their vault key is not stored beside their
ciphertext. Both local records and relay envelopes are physically removed on expiry. The panic
control asks for destructive confirmation, starts the safety signal, immediately disables the
conversation, revokes the device identity and erases local transcripts, keys, cached claims and
queued BLE packets without waiting for the network.

Mesh packets are fragmented into 20-byte ATT writes, bounded to three hops, deduplicated and
pruned by their authenticated expiry. Claimed prekeys are never recycled: the server retains a
consumed tombstone because a recipient can reconnect before it has downloaded and destroyed the
matching private key. Claim routing metadata is anonymized after the longest legal seven-day TTL.

### Platform behavior

- Android declares the legacy and Android 12+ scan/connect/advertise permissions; BLE hardware
  remains optional so server transport still works on devices without it.
- iOS declares central/peripheral use and background modes. The operating system still controls
  background radio time and may suspend advertising; hybrid mode is the resilient default.
- Flutter web cannot advertise as a Bluetooth peripheral, so the UI reports mesh unavailable
  instead of pretending Web Bluetooth is a relay. Server transport remains available.
- Offline sending requires a previously opened gig session and a prefetched peer prekey. That is
  an honest cryptographic constraint, not an offline-success animation.

Real-device BLE interoperability, permission denial, radio-off behavior and iOS/Android
background suspension must be exercised on release hardware; a simulator or protocol unit test
cannot prove those operating-system behaviors. Until the phones are in hand,
`backend/scripts/live_media_and_bitchat_journey.py` proves everything the relay can prove
without radios: the upload contract, wire-level consent, signed device keys, atomic one-time
prekey claims, a genuinely encrypted round trip driven by independent client crypto, physical
expiry and the panic wipe.

## Product and accessibility details

- **Sovereign Calm** design tokens are implemented in `AppTheme`: high-contrast ink/paper surfaces, restrained violet actions, semantic safety and trust colors, 48dp minimum controls, and no decorative shadows.
- **Proof comparison** supports drag, taps and keyboard arrow keys with a semantic value announcement.
- **Karma Ring** is a real custom-painted data visualization with a semantic label, not a decorative badge.
- Every list has loading, empty, error and retry states. Feed cache is marked as last saved rather than presented as live data.
- SOS is deliberately immediate and unanimated. Destructive removal and sign-out ask for confirmation.
- Large text and tablets are supported through flexible layouts and a centered 720dp content rail.

## Verification

`universal_ble`'s bidirectional peripheral API requires Dart 3.11.4 or newer. Run on a machine
with a matching Flutter SDK:

```bash
flutter pub get
flutter analyze
flutter test
flutter build web --release \
  --dart-define=API_ORIGIN=https://api.karma.example.com
flutter build appbundle --release \
  --dart-define=API_ORIGIN=https://api.karma.example.com
```

Run a Stripe test-mode PaymentSheet authorization, cancellation, completion approval, and
release on both Android and iOS, including an app background/return during 3DS. Exercise camera,
photo-library, approximate/precise location, denied, permanently-denied, service-off, oversized
upload, and geocoder-outage paths. Then test two physical phones in server, mesh and hybrid modes
with internet on/off, Bluetooth on/off, permission allowed/denied, foreground/background and
10-second/7-day expiry boundaries.
Web must visibly degrade to server-only operation. Panic must be checked once online and once
offline, confirming local key/transcript deletion in both cases.

The repository intentionally does not commit generated build output or secrets.
