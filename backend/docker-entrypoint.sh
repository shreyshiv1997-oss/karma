#!/bin/sh
# Migrate, then hand over to the server.
#
# `set -e` matters: if the migration fails the container must exit non-zero rather than serve
# traffic against a half-applied schema. Compose will restart it, and the restart loop is the
# signal -- a running API on the wrong schema is much harder to notice.
set -e

echo "[entrypoint] applying migrations (alembic upgrade head)"
alembic upgrade head

# The image's default uvicorn command can be scaled without duplicating it in Compose. Each
# worker owns its local WebSockets and subscribes to the shared Redis event channel.
if [ "${1:-}" = "uvicorn" ] && [ -n "${WEB_CONCURRENCY:-}" ]; then
    case "$WEB_CONCURRENCY" in
        *[!0-9]*|0) echo "[entrypoint] WEB_CONCURRENCY must be a positive integer" >&2; exit 2 ;;
    esac
    set -- "$@" --workers "$WEB_CONCURRENCY"
fi

echo "[entrypoint] starting $*"
exec "$@"
