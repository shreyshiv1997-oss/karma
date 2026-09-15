# FIXED: All production settings fail closed — CORS credentials are never enabled
# alongside a wildcard origin, in any environment.
"""KARMA — the merged application.

Assembly order matters: middleware added later wraps middleware added earlier, so the
security-header middleware is added first and therefore runs outermost on the way out.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.db import SessionLocal, engine, init_db
from app.core.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app.routers import (
    auth,
    bitchat,
    feed,
    gigs,
    health,
    karma,
    locations,
    matching,
    media,
    payments,
    realtime,
    trust,
)
from app.services.bitchat import cleanup_forever
from app.services.geocoding import geocoder
from app.services.realtime import realtime as realtime_hub
from app.services.storage import object_storage


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    expiry_task: asyncio.Task[None] | None = None
    try:
        # Required infrastructure is checked before readiness. S3 creates/verifies its bucket;
        # Redis subscribes every worker to the shared event bus.
        await object_storage.start()
        await realtime_hub.start()
        expiry_task = asyncio.create_task(
            cleanup_forever(SessionLocal), name="bitchat-expiry-sweep"
        )
        yield
    finally:
        if expiry_task is not None:
            expiry_task.cancel()
            with suppress(asyncio.CancelledError):
                await expiry_task
        await realtime_hub.close()
        await geocoder.close()
        await object_storage.close()
        await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="KARMA — thou art the work you do. A trust-first labour marketplace and a "
    "social proof network sharing one identity and one reputation ledger.",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
)


def cors_allow_credentials(origins: list[str]) -> bool:
    """Whether credentialled CORS may be enabled for this origin list.

    Credentialled CORS and a wildcard origin are mutually exclusive: together they let any
    site on the internet make authenticated calls as the logged-in user. The previous
    expression was::

        settings.is_production is False or "*" not in settings.ALLOWED_ORIGINS

    which short-circuits on the first clause, so *every* non-production deployment
    enabled exactly that combination. Environment must not change the answer -- the
    origin list alone decides, and it fails closed.

    Extracted as a function so the policy is testable without booting the app.
    """
    return "*" not in origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=cors_allow_credentials(settings.ALLOWED_ORIGINS),
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    max_requests=settings.RATE_LIMIT_REQUESTS,
    window=settings.RATE_LIMIT_WINDOW,
)


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
    import logging

    logging.getLogger(__name__).exception("Unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


for _router in (
    auth.router,
    karma.router,
    feed.router,
    gigs.router,
    matching.router,
    locations.router,
    media.router,
    trust.router,
    trust.admin,
    payments.router,
    bitchat.router,
    realtime.router,
    health.router,
):
    app.include_router(_router, prefix=settings.API_PREFIX)


@app.get("/")
async def root() -> dict:
    return {
        "name": settings.APP_NAME,
        "tagline": "Thou art the work you do.",
        "version": settings.APP_VERSION,
        "docs": None if settings.is_production else "/docs",
        "health": f"{settings.API_PREFIX}/health/ready",
    }
