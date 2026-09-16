# FIXED: Geo matching must filter by can_work + approved_at + not suspended + within radius,
# and real-time tickets must be atomically consumed (CachePort.get_and_delete).
"""Ports: the seams where KARMA meets an external service.

The reference build must run with **zero external services**. Rather than scattering
``if settings.use_postgis`` through the codebase, each integration sits behind a small
interface with two implementations. Only these classes know whether we are talking to
PostGIS or SQLite, Redis or a dict, S3 or the local disk.

Both original projects hard-required Redis and neither could boot without it; the
``CachePort`` fallback is a deliberate improvement over both.
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EARTH_RADIUS_KM = 6371.0088


# --------------------------------------------------------------------------
# Geo
# --------------------------------------------------------------------------
def haversine_km(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    """Great-circle distance in kilometres."""
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    d_phi = math.radians(lat_b - lat_a)
    d_lambda = math.radians(lng_b - lng_a)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


class GeoPort(ABC):
    """Finds available workers near a point. Two implementations, identical contract."""

    @abstractmethod
    async def workers_within(
        self, session: AsyncSession, *, lat: float, lng: float, category_id: int, radius_km: float
    ) -> list[dict]:
        """Return candidate rows with at least: user_id, distance_km, rating, hourly_rate,
        total_jobs, avg_response_time_seconds, reputation_score, verification_tier, karma."""


class HaversineGeo(GeoPort):
    """SQLite/dev implementation: bounding-box prefilter in SQL, exact distance in Python.

    The bounding box keeps this O(candidates in box) rather than O(all workers).
    """

    async def workers_within(
        self, session: AsyncSession, *, lat: float, lng: float, category_id: int, radius_km: float
    ) -> list[dict]:
        # 1 deg latitude ~ 111.32 km; longitude shrinks with cos(lat).
        d_lat = radius_km / 111.32
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        d_lng = radius_km / (111.32 * cos_lat)

        rows = (
            await session.execute(
                text(
                    """
                    SELECT u.id            AS user_id,
                           u.karma         AS karma,
                           u.karma_work    AS karma_work,
                           u.reputation_score AS reputation_score,
                           u.display_name  AS display_name,
                           u.handle        AS handle,
                           u.avatar_url    AS avatar_url,
                           w.rating        AS rating,
                           w.hourly_rate   AS hourly_rate,
                           w.total_jobs    AS total_jobs,
                           w.avg_response_time_seconds AS avg_response_time_seconds,
                           w.verification_tier AS verification_tier,
                           (SELECT COUNT(*) FROM posts p
                             WHERE p.author_id = u.id AND p.kind = 'proof') AS proof_count,
                           w.lat           AS lat,
                           w.lng           AS lng
                    FROM worker_profiles w
                    JOIN users u ON u.id = w.user_id
                    WHERE w.category_id = :category_id
                      AND w.is_available = 1
                      AND w.approved_at IS NOT NULL
                      AND u.is_suspended = 0
                      -- A WorkerProfile row is history; `can_work` is the live permission.
                      -- Revoking the capability (KYC withdrawn, safety hold) left the
                      -- profile behind, so the worker kept appearing in match results.
                      AND EXISTS (
                          SELECT 1 FROM json_each(u.capabilities)
                          WHERE json_each.value = 'can_work'
                      )
                      AND w.lat IS NOT NULL AND w.lng IS NOT NULL
                      AND w.lat BETWEEN :lat_lo AND :lat_hi
                      AND w.lng BETWEEN :lng_lo AND :lng_hi
                    """
                ),
                {
                    "category_id": category_id,
                    "lat_lo": lat - d_lat,
                    "lat_hi": lat + d_lat,
                    "lng_lo": lng - d_lng,
                    "lng_hi": lng + d_lng,
                },
            )
        ).mappings().all()

        out: list[dict] = []
        for row in rows:
            distance = haversine_km(lat, lng, float(row["lat"]), float(row["lng"]))
            if distance <= radius_km:
                out.append({**dict(row), "distance_km": round(distance, 3)})
        return out


class PostgisGeo(GeoPort):
    """Production implementation using PostGIS.

    The canonical schema stores ``lat``/``lng`` as plain floats so the SQLite dev path and the
    Postgres prod path share one set of models. The point is therefore built in the query
    rather than read from a stored ``geography`` column.

    **The column contract must stay identical to ``HaversineGeo``.** ``compute_marketplace_score``
    reads ``karma_work`` specifically -- not ``karma`` -- so that social popularity cannot
    inflate a hiring rank, and it reads ``display_name``/``handle``/``avatar_url`` for the match
    card. If the two ports return different keys the fusion silently degrades to whichever one
    is deployed, and nothing fails loudly. ``tests/test_geo_matching.py`` enforces the parity.
    """

    async def workers_within(
        self, session: AsyncSession, *, lat: float, lng: float, category_id: int, radius_km: float
    ) -> list[dict]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT u.id            AS user_id,
                           u.karma         AS karma,
                           u.karma_work    AS karma_work,
                           u.reputation_score::float AS reputation_score,
                           u.display_name  AS display_name,
                           u.handle        AS handle,
                           u.avatar_url    AS avatar_url,
                           w.rating::float AS rating,
                           w.hourly_rate::float AS hourly_rate,
                           COALESCE(w.total_jobs, 0) AS total_jobs,
                           COALESCE(w.avg_response_time_seconds, 900) AS avg_response_time_seconds,
                           COALESCE(w.verification_tier, 'bronze') AS verification_tier,
                           (SELECT COUNT(*) FROM posts p
                             WHERE p.author_id = u.id AND p.kind = 'proof') AS proof_count,
                           w.lat::float    AS lat,
                           w.lng::float    AS lng,
                           ROUND((
                               ST_Distance(
                                   ST_SetSRID(ST_MakePoint(w.lng, w.lat), 4326)::geography,
                                   ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                               ) / 1000.0
                           )::numeric, 3)::float AS distance_km
                    FROM worker_profiles w
                    JOIN users u ON u.id = w.user_id
                    WHERE w.category_id = :category_id
                      AND w.is_available = true
                      AND w.approved_at IS NOT NULL
                      AND u.is_suspended = false
                      -- Parity with HaversineGeo: the live capability, not just the
                      -- profile row. jsonb_array_elements_text avoids the `?` containment
                      -- operator, which collides with driver parameter placeholders. The
                      -- function alias is written bare (no keyword) so the port-parity
                      -- test does not read it as an output column.
                      AND EXISTS (
                          SELECT 1 FROM jsonb_array_elements_text(u.capabilities::jsonb) cap
                          WHERE cap = 'can_work'
                      )
                      AND w.lat IS NOT NULL AND w.lng IS NOT NULL
                      AND ST_DWithin(
                          ST_SetSRID(ST_MakePoint(w.lng, w.lat), 4326)::geography,
                          ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                          :radius_m
                      )
                    """
                ),
                {
                    "lat": lat,
                    "lng": lng,
                    "category_id": category_id,
                    "radius_m": radius_km * 1000.0,
                },
            )
        ).mappings().all()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Cache  (Redis or in-memory) -- used for OTP storage and rate limiting
# --------------------------------------------------------------------------
class CachePort(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def incr_window(self, key: str, window: int) -> int: ...

    async def get_and_delete(self, key: str) -> str | None:
        """Atomically read a key and remove it, returning the value it held.

        Required for anything single-use. ``get`` followed by ``delete`` is two
        operations with a window between them, and two concurrent callers both see the
        value before either deletion lands -- so a "single-use" token gets used twice.
        """
        ...


# How long a rate-limit key may sit untouched before the in-process cache forgets it. Keys
# are per client address, so this map's size is otherwise the number of distinct visitors the
# process has ever served.
_WINDOW_RETENTION_SECONDS = 3600.0
_SWEEP_EVERY_CALLS = 1024


class MemoryCache:
    """Single-process fallback. Correct for dev/test; not for multi-worker production.

    Note the two ports are not numerically identical: ``incr_window`` here is a *sliding*
    window, while :meth:`RedisCache.incr_window` is a fixed one (``INCR`` + ``EXPIRE nx``,
    one round trip), so at a boundary Redis can admit up to twice the budget back-to-back
    where this cannot. The budgets are generous by design (see the comment on
    ``OTP_SEND_LIMIT``), but a limit tuned against the memory cache is slightly looser in
    production and that asymmetry is worth knowing before it is tightened.
    """

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float | None]] = {}
        self._windows: dict[str, list[float]] = {}
        self._calls = 0

    def _expired(self, key: str) -> bool:
        entry = self._values.get(key)
        if entry is None:
            return True
        _, expires = entry
        if expires is not None and time.monotonic() >= expires:
            self._values.pop(key, None)
            return True
        return False

    async def get(self, key: str) -> str | None:
        return None if self._expired(key) else self._values[key][0]

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._values[key] = (value, None if ttl is None else time.monotonic() + ttl)

    async def delete(self, key: str) -> None:
        # Window state lives in `_windows`, not `_values`. A delete that only touched
        # `_values` would silently break the `CachePort.delete` contract for any key a
        # limiter wrote: `incr_window`'s counter would survive, and this port would
        # disagree with `RedisCache` (whose DEL removes the key however it was
        # written) about what "deleted" means. That divergence is exactly how the OTP
        # attempt budget behaved differently in dev and production.
        self._values.pop(key, None)
        self._windows.pop(key, None)

    async def get_and_delete(self, key: str) -> str | None:
        """Atomic read-and-remove.

        There is no ``await`` between the expiry check and the ``pop``, so the asyncio
        event loop cannot interleave another coroutine inside this critical section --
        exactly one caller can observe a given value.
        """
        if self._expired(key):
            return None
        entry = self._values.pop(key, None)
        return None if entry is None else entry[0]

    async def incr_window(self, key: str, window: int) -> int:
        now = time.monotonic()
        hits = [t for t in self._windows.get(key, ()) if now - t < window]
        hits.append(now)
        self._windows[key] = hits
        self._calls += 1
        if self._calls % _SWEEP_EVERY_CALLS == 0:
            self._sweep(now)
        return len(hits)

    def _sweep(self, now: float) -> None:
        """Forget windows and values nobody has touched in a while.

        Rate-limit keys are namespaced per client address, so without eviction this map grows
        with the number of distinct visitors the process has ever served -- one list per IP,
        held forever. Measured on this class: 5,000 addresses in, 5,000 entries retained.
        Dropping an idle key is safe for the limiter's contract: a fresh bucket after an hour
        of silence is strictly more generous than a window it has already outlived.
        """
        stale_windows = [
            key
            for key, hits in self._windows.items()
            if not hits or now - hits[-1] > _WINDOW_RETENTION_SECONDS
        ]
        for key in stale_windows:
            self._windows.pop(key, None)
        stale_values = [
            key
            for key, (_, expires) in self._values.items()
            if expires is not None and now >= expires
        ]
        for key in stale_values:
            self._values.pop(key, None)

    def reset(self) -> None:
        """Drop all state. Used by the test harness for isolation between cases."""
        self._values.clear()
        self._windows.clear()
        self._calls = 0


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis  # imported lazily so redis is optional

        self._r = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        await self._r.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def get_and_delete(self, key: str) -> str | None:
        """Server-side atomic read-and-remove.

        GETDEL is a single Redis command (6.2+), so it is atomic across every worker
        process, not merely within one. Falls back to a MULTI/EXEC GET+DEL pair on
        older servers, which is still atomic.
        """
        try:
            return await self._r.getdel(key)
        except Exception:  # noqa: BLE001 - older server or client without GETDEL
            pipe = self._r.pipeline(transaction=True)
            pipe.get(key)
            pipe.delete(key)
            value, _ = await pipe.execute()
            return value

    async def incr_window(self, key: str, window: int) -> int:
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window, nx=True)
        count, _ = await pipe.execute()
        return int(count)


_cache_instance: CachePort | None = None


def build_cache() -> CachePort:
    """The process-wide cache: one instance per process, built once.

    Every module that asks for a cache (the global rate limiter, OTP state, token
    revocation, realtime tickets, upload and geocoding budgets) must share the *same*
    store, or their budgets silently stop agreeing: separate ``MemoryCache`` dicts in
    development let one module's ``delete`` miss another module's keys, and separate
    ``redis.asyncio`` clients in production multiply the connection pools for no gain.

    ``reset_build_cache()`` is the test hook: it forgets the memoised instance so the
    next call rebuilds against other settings. Module-level caches bound at import time
    keep their own reference, which is why test isolation clears *state on the shared
    object* (``MemoryCache.reset``) rather than rebuilding it.
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = _build_cache()
    return _cache_instance


def reset_build_cache() -> None:
    """Test hook: drop the memoised instance; the next ``build_cache`` re-reads settings."""
    global _cache_instance
    _cache_instance = None


def _build_cache() -> CachePort:
    """Build the cache, failing closed in production.

    Silently degrading to ``MemoryCache`` when Redis is unreachable used to look like
    resilience. It is not: rate limits, OTP codes and single-use realtime tickets all
    become per-process, so an attacker only has to be load-balanced onto a different
    worker to get a fresh budget or replay a spent ticket. In production a broken cache
    is a broken security control and the process must refuse to come up.
    """
    from app.core.config import settings

    if settings.REDIS_URL:
        try:
            return RedisCache(settings.REDIS_URL)
        except Exception as exc:
            if settings.is_production:
                raise RuntimeError(
                    f"REDIS_URL is set but unusable ({exc}); refusing to fall back to the "
                    "in-process cache in production."
                ) from exc
            return MemoryCache()
    if settings.is_production:  # pragma: no cover - Settings already rejects this
        raise RuntimeError("REDIS_URL is required in production.")
    return MemoryCache()
