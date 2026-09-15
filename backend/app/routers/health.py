"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from app.services.geocoding import geocoder
from app.services.realtime import RedisRealtime, realtime
from app.services.storage import object_storage

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/live")
async def live() -> dict:
    return {"status": "alive"}


@router.get("/ready")
async def ready() -> dict:
    """Readiness requires a reachable database."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - infrastructure state
        return {"status": "degraded", "database": "unreachable", "detail": str(exc)[:200]}
    if isinstance(realtime, RedisRealtime) and not realtime.is_ready:
        return {
            "status": "degraded",
            "database": "ok",
            "realtime": "redis_subscription_unavailable",
        }
    return {"status": "ready", "database": "ok"}


@router.get("")
async def health() -> dict:
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "geo_backend": "postgis" if settings.use_postgis else "haversine",
        "cache_backend": "redis" if settings.REDIS_URL else "memory",
        "realtime_backend": "redis" if isinstance(realtime, RedisRealtime) else "memory",
        "object_storage_backend": object_storage.backend_name,
        "geocoding_backend": geocoder.provider_name or "disabled",
    }
