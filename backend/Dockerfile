# KARMA API.
#
# Referenced by ../docker-compose.yml as `build: ./backend`. This file did not exist for most
# of the project's life, which meant the documented production command -- `docker compose up
# --build` -- could not run at all: Compose fails with "failed to read dockerfile" before it
# starts a single container. Nothing in the test suite could catch that, because the tests
# drive the app in-process and never build an image.
FROM python:3.13-slim

# No .pyc files on disk (the root filesystem is read_only in compose) and unbuffered logs so
# `docker compose logs -f` shows output as it happens rather than when the buffer flushes.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, on their own layer, so a code edit does not reinstall the world.
# requirements.txt is copied alone to keep that cache honest.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The application. Tests and the dev seed script are deliberately not copied: the image runs
# the API, and shipping the fixtures that create demo accounts into a production image would
# be a gift to anyone who finds the endpoint.
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Migrate, then serve. The migration runs on every start because compose has no separate
# one-shot migration service, and `upgrade head` is idempotent -- on an already-current
# schema it does nothing. Running it here rather than in the image build is the point: the
# schema is a property of the *database*, and the database is not present at build time.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Unprivileged. compose sets no `user:`, so without this the API would run as root next to a
# database whose password it holds in an environment variable.
RUN useradd --create-home --uid 10001 karma
USER karma

EXPOSE 8000

# The web container's reverse proxy appends each client's real address to
# X-Forwarded-For, and the application resolves that header itself: TRUSTED_PROXY_HOPS
# (set in docker-compose.yml) tells it exactly how many trusted hops to read through,
# so entries further left -- attacker-controlled -- are never used as a budget key.
#
# Do NOT re-add uvicorn's `--proxy-headers` here. With `--forwarded-allow-ips *` it
# rewrites request.client to the *leftmost* XFF entry before the application ever
# sees it; combined with TRUSTED_PROXY_HOPS=0 that made every per-IP budget
# (OTP send, register, login spray, the global limiter) key on an address the
# caller chose per request, which rotated and defeated the limit entirely.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
