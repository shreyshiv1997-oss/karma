# FIXED: Rate limiting must survive behind reverse proxies (X-Forwarded-For) — a single
# trusted-proxy-aware client-IP resolver, so every limiter keys on the real caller.
"""Network-layer helpers: resolving the *real* client IP behind a reverse proxy.

Why this module exists
----------------------
Every rate limiter in KARMA used ``request.client.host``. Behind any reverse proxy
(nginx, an ALB, Cloudflare, the Docker Compose front end in this very repo) that value is
the *proxy's* address, identical for every user on the planet. The consequences run both
ways and both are severe:

  * **Availability** — all traffic collapses into one bucket. ``RATE_LIMIT_REQUESTS``
    becomes a global cap: one script exhausts it and every other user gets 429.
  * **Security** — the per-IP OTP and registration budgets stop isolating anyone, so the
    abuse controls those budgets exist to provide are simply absent.

The naive fix — trusting ``X-Forwarded-For`` — is worse, because the header is
attacker-controlled: a client can send ``X-Forwarded-For: 1.2.3.4`` and mint a fresh
bucket per request, which defeats rate limiting completely.

The correct resolution is to trust exactly as many hops as you actually operate.
``TRUSTED_PROXY_HOPS`` states that number. Given a chain::

    X-Forwarded-For: <client>, <proxy1>, <proxy2>

the peer address is ``proxy2`` and the header lists everything before it. With
``TRUSTED_PROXY_HOPS = 2`` we skip the 1 appended-but-trusted entry and take ``<client>``.
Anything the client forged sits further left and is never reached.

``TRUSTED_PROXY_HOPS = 0`` (the default) means "no proxy in front of me": the header is
ignored entirely and the peer address is authoritative. That is the fail-closed default —
an un-configured deployment cannot be spoofed, it simply cannot see through a proxy.
"""

from __future__ import annotations

from starlette.requests import HTTPConnection

_UNKNOWN = "unknown"


def _peer(conn: HTTPConnection) -> str:
    client = conn.client
    return client.host if client and client.host else _UNKNOWN


def client_ip(conn: HTTPConnection, trusted_hops: int | None = None) -> str:
    """Return the caller's address, honouring ``TRUSTED_PROXY_HOPS`` forwarded hops.

    ``conn`` is an ``HTTPConnection``, so this works for both ``Request`` and
    ``WebSocket`` scopes.
    """
    if trusted_hops is None:
        from app.core.config import settings

        trusted_hops = settings.TRUSTED_PROXY_HOPS

    peer = _peer(conn)
    if trusted_hops <= 0:
        # No proxy is trusted: the header is attacker-controlled noise.
        return peer

    forwarded = conn.headers.get("x-forwarded-for", "")
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not chain:
        return peer

    # The peer itself is one of the trusted hops and is not present in the header, so the
    # header supplies (trusted_hops - 1) trusted entries from the right.
    index = len(chain) - (trusted_hops - 1) - 1
    if index < 0:
        # The chain is shorter than we were told to expect: the request did not traverse
        # the full proxy path we trust. Fail closed onto the address we can actually
        # verify rather than believing an entry that may be forged.
        return peer
    return chain[index] or peer
