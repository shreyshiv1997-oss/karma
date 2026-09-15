#!/usr/bin/env bash
# Runtime smoke test for the production Compose stack.
#
# This is the gate that requires a Docker daemon (this repository's build environments have
# never had one, which is why check_static.py exists). On a Docker host:
#
#     WEB_PORT=8080 bash tools/compose_smoke/smoke.sh
#
# It builds both images, starts Postgres 17 + PostGIS, Redis, SeaweedFS and the production
# API behind the nginx reverse proxy, then proves, through the published port only:
#
#   * readiness through the same-origin /api proxy (the app never learns the API host);
#   * /health reports the production backend selections: PostGIS, Redis, Redis realtime,
#     S3 object storage, Nominatim geocoding;
#   * the PostGIS extension is live and the Alembic chain created all 26 app tables;
#   * auth, owned media upload -> immutable delivery round trip over the proxy
#     (exercising the 6 m nginx body cap and the S3/SeaweedFS path);
#   * the consented geocoding contract (422 without wire consent, 200 with it) against the
#     real provider; and a realtime ticket.
#
# Everything is torn down afterwards, volumes included. Exits non-zero on any failure.
# The host needs outbound HTTPS (Nominatim) and enough memory for the stack (~2 GB).

set -euo pipefail

cd "$(dirname "$0")/../.."   # karma/

WEB_PORT="${WEB_PORT:-8080}"
BASE="http://127.0.0.1:${WEB_PORT}/api/v1"
PROJECT="karma-smoke"
WORK="$(mktemp -d)"
PNG="${WORK}/pixel.png"
FAILED=0
STARTED=0

fail() {
  echo "  ✗  $1"
  FAILED=1
}

pass() {
  echo "  ✓  $1"
}

check() { # label, condition(0=ok), detail
  if [ "$2" -eq 0 ]; then pass "$1"; else fail "$1${3:+ -> $3}"; fi
}

cleanup() {
  if [ "${STARTED}" -eq 1 ]; then
    echo
    echo "tearing down ${PROJECT} (volumes included)"
    ${COMPOSE} down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "${WORK}"
}
trap cleanup EXIT

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose -f docker-compose.yml --project-name ${PROJECT}"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose -f docker-compose.yml -p ${PROJECT}"
else
  echo "no docker compose available; this gate needs a Docker host. Run check_static.py instead." >&2
  exit 2
fi

# 1x1 PNG — the upload contract sniffs bytes, not the filename.
printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC' | base64 -d > "${PNG}"
PNG_SHA="$(sha256sum "${PNG}" | cut -d' ' -f1)"

POSTGRES_USER="karma"
POSTGRES_DB="karma"
rand() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
ENV_FILE="${WORK}/smoke.env"
cat > "${ENV_FILE}" <<EOF
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_DB=${POSTGRES_DB}
POSTGRES_PASSWORD=$(rand)
SECRET_KEY=$(rand)
ALLOWED_ORIGINS=["http://localhost:${WEB_PORT}","http://127.0.0.1:${WEB_PORT}"]
TRUSTED_HOSTS=["localhost","127.0.0.1"]
S3_ACCESS_KEY=smokeaccesskey$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')
S3_SECRET_KEY=$(rand)
GEOCODING_USER_AGENT="KARMA-compose-smoke/1.0 smoke@$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n').example"
STRIPE_SECRET_KEY=sk_test_compose_smoke
STRIPE_PUBLISHABLE_KEY=pk_test_compose_smoke
STRIPE_WEBHOOK_SECRET=whsec_compose_smoke
WEB_PORT=${WEB_PORT}
EOF

echo "building images and starting the stack (this pulls Postgres 17 + PostGIS, Redis, SeaweedFS, node and nginx)"
${COMPOSE} --env-file "${ENV_FILE}" up -d --build
STARTED=1
check "stack started" 0

echo
echo "readiness through the same-origin proxy"
READY=""
for _ in $(seq 1 48); do
  READY="$(curl -sf "${BASE}/health/ready" 2>/dev/null || true)"
  case "${READY}" in
    *'"status":"ready"'*) break ;;
  esac
  sleep 5
done
check "API reports ready (db reachable, realtime subscribed)" $([ -n "${READY}" ] && echo 0 || echo 1) "${READY:-no response after 240 s}"

echo
echo "production backend selections"
HEALTH="$(curl -sf "${BASE}/health" || true)"
echo "  ${HEALTH}"
for field in '"environment":"production"' '"geo_backend":"postgis"' '"cache_backend":"redis"' '"realtime_backend":"redis"' '"object_storage_backend":"s3"' '"geocoding_backend":"OpenStreetMap Nominatim"'; do
  check "health reports ${field%%\"*}" $([ "${HEALTH}" = *"${field}"* ] && echo 0 || echo 1)
done

echo
echo "database"
POSTGIS_VERSION="$( ${COMPOSE} --env-file "${ENV_FILE}" exec -T db psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "SELECT extversion FROM pg_extension WHERE extname='postgis'" 2>/dev/null || true)"
check "PostGIS extension is live" $([ -n "${POSTGIS_VERSION}" ] && echo 0 || echo 1) "extversion=${POSTGIS_VERSION:-missing}"
TABLES="$( ${COMPOSE} --env-file "${ENV_FILE}" exec -T db psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name NOT IN ('alembic_version','spatial_ref_sys')" 2>/dev/null || true)"
check "Alembic chain created all 26 app tables" $([ "${TABLES}" = "26" ] && echo 0 || echo 1) "tables=${TABLES:-?} (excluding alembic_version and PostGIS's spatial_ref_sys)"

echo
echo "auth and owned media over the proxy"
HANDLE="smoke$(head -c 5 /dev/urandom | od -An -tx1 | tr -d ' \n')"
REG="$(curl -sf -X POST "${BASE}/auth/register" -H 'Content-Type: application/json' -d "{\"handle\":\"${HANDLE}\",\"display_name\":\"Smoke\",\"email\":\"${HANDLE}@example.com\",\"password\":\"SmokePass!234\",\"city\":\"Indore\"}" || true)"
TOKEN="$(printf '%s' "${REG}" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')"
check "register returns a token" $([ -n "${TOKEN}" ] && echo 0 || echo 1)
UP="$(curl -sf -X POST "${BASE}/media/uploads" -H "Authorization: Bearer ${TOKEN}" -F purpose=post -F "file=@${PNG};type=image/png" || true)"
MEDIA_REF="$(printf '%s' "${UP}" | sed -n 's/.*"url":"\([^"]*\)".*/\1/p')"
check "upload returns an owned object reference" $([ -n "${MEDIA_REF}" ] && echo 0 || echo 1)
DOWN="${WORK}/downloaded.png"
HDRS="$(curl -s -D - -o "${DOWN}" "${BASE%/api/v1}${MEDIA_REF}" | tr -d '\r' || true)"
GOT_SHA="$(sha256sum "${DOWN}" 2>/dev/null | cut -d' ' -f1 || true)"
check "object round-trips through proxy and S3" $([ "${GOT_SHA}" = "${PNG_SHA}" ] && echo 0 || echo 1)
check "immutable delivery headers survive the proxy" $([ "${HDRS}" = *"public, max-age=31536000, immutable"* ] && [ "${HDRS}" = *"nosniff"* ] && echo 0 || echo 1)

echo
echo "consented geocoding against the real provider"
CAPS="$(curl -sf "${BASE}/locations/capabilities" -H "Authorization: Bearer ${TOKEN}" || true)"
check "capabilities report the provider" $([ "${CAPS}" = *'"enabled":true'* ] && [ "${CAPS}" = *'"consent_required":true'* ] && echo 0 || echo 1)
NO_CONSENT="$(curl -s -o /dev/null -w '%{http_code}' -X POST "${BASE}/locations/geocode" -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' -d '{"query":"Vijay Nagar Indore"}')"
check "geocode without wire consent -> 422" $([ "${NO_CONSENT}" = "422" ] && echo 0 || echo 1) "${NO_CONSENT}"
WITH_CONSENT="$(curl -s -o "${WORK}/geocode.json" -w '%{http_code}' -X POST "${BASE}/locations/geocode" -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' -d '{"query":"Vijay Nagar Indore","consent":true,"limit":5}')"
check "consented geocode returns attributed results" $([ "${WITH_CONSENT}" = "200" ] && [ "$(head -c 1 "${WORK}/geocode.json")" = "[" ] && [ "$(grep -c '"attribution"' "${WORK}/geocode.json" || true)" -ge 1 ] && echo 0 || echo 1) "${WITH_CONSENT}"

echo
echo "realtime"
TICKET="$(curl -sf -X POST "${BASE}/realtime/ticket" -H "Authorization: Bearer ${TOKEN}" || true)"
check "single-use ticket issued" $([ "${TICKET}" = *'"ticket":'* ] && echo 0 || echo 1)

echo
if [ "${FAILED}" -ne 0 ]; then
  echo "runtime smoke: FAILED (stack logs: ${COMPOSE} logs)"
  exit 1
fi
echo "runtime smoke: all checks passed — the production stack booted and served end to end"
