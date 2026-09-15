# Production Compose stack — the two gates

The production deployment is `docker compose up --build` against PostgreSQL 17 + PostGIS,
Redis, SeaweedFS (S3) and the nginx reverse proxy. Proving it splits into two gates because
the environments where this repository is built have **no Docker daemon**:

| Gate | Needs | What it proves |
|---|---|---|
| `check_static.py` | only the backend virtualenv | the compose wiring, both build contexts, the nginx proxy contract and the production settings guard — every check a container-less environment *can* execute |
| `smoke.sh` | a Docker host + outbound HTTPS | the images build, the five containers start together, the API is ready **through the same-origin proxy**, `/health` reports PostGIS + Redis + Redis realtime + S3 + Nominatim, the PostGIS extension is live, all 26 Alembic tables exist, auth works, an owned media object round-trips through proxy → API → SeaweedFS, the geocoding consent contract answers 422/200 against the real provider, and a realtime ticket is issued |

## Static gate (run here, on every CI box, anywhere)

```bash
cd backend
.venv/bin/python ../tools/compose_smoke/check_static.py
```

Non-zero exit on any failure. It also *executes* the production settings guard: each
documented misconfiguration (default secret, wildcard origins/hosts, missing Redis, local
object storage, missing S3/Stripe credentials, disabled or unidentified geocoder, simulated
payments) is constructed for real and must refuse, while one complete environment must pass.

## Runtime gate (run on any Docker-capable machine)

```bash
WEB_PORT=8080 bash tools/compose_smoke/smoke.sh
```

Requirements: Docker with the compose plugin, ~2 GB of memory, outbound HTTPS (the API
contacts Nominatim with the `GEOCODING_USER_AGENT` the smoke test generates). All secrets are
generated at runtime — the Stripe keys are format-valid `sk_test_`/`pk_test_`/`whsec_` dummies
because the smoke never touches the payment path. The stack (volumes included) is torn down
when the script exits, including on failure; the last line of output says how to read the
logs if it did not pass.

## What remains unprovable without the runtime gate

Everything the runtime gate covers. Nothing else: the PostGIS SQL contract itself has its own
separate live harness (`backend/tools/postgis`), and the in-process suite covers every route.
