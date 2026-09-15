# FIXED: Rate limiting must survive behind reverse proxies (X-Forwarded-For) — the
# limiter now keys on the trusted-proxy-resolved client IP, not the TCP peer.
"""HTTP hardening: security headers and a fixed-window rate limiter.

Both middlewares come from Tatwamasi, which had the more complete HTTP layer of the two.
Two corrections:
  * Rate-limit keys are namespaced by scope, so one global bucket cannot be exhausted by
    an unrelated endpoint.
  * CORS ``allow_credentials`` is derived from an explicit setting rather than the
    expression ``"*" not in ALLOWED_ORIGINS``, which silently changed security posture
    based on the contents of a config string.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.net import client_ip
from app.core.ports import build_cache

_cache = build_cache()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(self), microphone=(self), geolocation=(self)"
        )
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window limiter. Falls back to in-process counting without Redis."""

    def __init__(self, app, max_requests: int, window: int) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Behind a proxy ``request.client.host`` is the proxy for every user alive, which
        # turns a per-IP budget into a single global one. ``client_ip`` resolves the real
        # caller through exactly ``TRUSTED_PROXY_HOPS`` forwarded hops and ignores the
        # header entirely when no proxy is trusted, so it can never be spoofed.
        client = client_ip(request)
        scope = request.url.path.split("/")[3] if request.url.path.count("/") >= 3 else "root"
        key = f"karma:rl:{scope}:{client}"

        hits = await _cache.incr_window(key, self.window)
        if hits > self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(self.window)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.max_requests - hits))
        return response
