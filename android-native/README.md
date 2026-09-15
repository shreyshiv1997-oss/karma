# KARMA Native — a real Android Studio project (Kotlin)

A standalone, native Android app for KARMA, written in **Kotlin**, that talks to the backend
REST API directly. It is separate from the Capacitor WebView shell in `frontend/android` —
this one has no JavaScript at all.

Open this folder in Android Studio and run. That's the whole workflow.

## What it does

- **Login** against `POST /api/v1/auth/login`, storing the JWT pair locally.
- **Home** — the public proof feed (`GET /feed/posts`) with author karma badges.
- **Gigs** — your gigs (`GET /gigs/mine`) with status, urgency and payout.
- **Karma** — the ledger (`GET /karma/ledger`) rendered with a native `KarmaRingView`
  (the same rose→amber→lime→gold ring as the web), plus the work/social split and the
  event-by-event audit trail.

## Deliberately dependency-light

HTTP is `HttpURLConnection`, JSON is `org.json`, async is a single-thread executor + main-thread
handler. The only Gradle artifacts are the standard AndroidX/Material ones Android Studio already
resolves. Nothing exotic to break your build.

## Point it at your backend

Edit `ApiConfig.BASE_URL`:

| Target | Value |
|---|---|
| Android emulator → host | `http://10.0.2.2:8000` |
| Physical phone on Wi-Fi | `http://<your-lan-ip>:8000` |
| Production | `https://api.yourdomain.com` |

Start the backend with `--host 0.0.0.0` so it is reachable off-loopback. A native app makes real
cross-origin calls, so no CORS or reverse proxy is needed (unlike the WebView).

## Run

1. Start the backend and seed it (`python seed.py`, `uvicorn app.main:app --host 0.0.0.0`).
2. Open this folder in Android Studio (it will fetch Gradle 8.2 + AGP 8.2.2).
3. Pick a device (emulator or phone) and press Run.
4. Sign in with a seeded account, e.g. `priya` / `StrongPass!234`.

## Honesty

There is no Android SDK in the environment this was authored in, so `gradlew assembleDebug` has
not been run here. What *is* verified: every layout id, drawable, colour, string, menu and mipmap
referenced from Kotlin or XML resolves to a defined resource, and every XML file parses. The
compile itself is the one step that happens in Android Studio.
