"""Execute the production geo port against a real PostgreSQL/PostGIS engine.

This module is intentionally opt-in: the normal suite keeps its zero-service promise. Run it
against a database with PostGIS installed by setting ``KARMA_POSTGIS_TEST_URL``. The repository's
``tools/postgis`` harness provides a disposable PostgreSQL-in-WASM/PostGIS instance for CI and
local development without Docker.
"""

from __future__ import annotations

import os
import uuid
from contextlib import suppress

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.ports import PostgisGeo, haversine_km

POSTGIS_TEST_URL = os.getenv("KARMA_POSTGIS_TEST_URL")
PGLITE_SOCKET = os.getenv("KARMA_POSTGIS_PGLITE") == "1"

pytestmark = pytest.mark.skipif(
    not POSTGIS_TEST_URL,
    reason="set KARMA_POSTGIS_TEST_URL to run the live PostGIS contract test",
)

ORIGIN = (22.7196, 75.8577)
EXPECTED_KEYS = {
    "avatar_url",
    "avg_response_time_seconds",
    "display_name",
    "distance_km",
    "handle",
    "hourly_rate",
    "karma",
    "karma_work",
    "lat",
    "lng",
    "proof_count",
    "rating",
    "reputation_score",
    "total_jobs",
    "user_id",
    "verification_tier",
}
# id, label, lat, lng, category, available, approved, suspended, capabilities
WORKERS = [
    (1, "Ramesh", 22.7216, 75.8597, 1, True, True, False, '["can_work", "can_chat"]'),
    (2, "Sunita", 22.7286, 75.8577, 1, True, True, False, '["can_work"]'),
    (3, "Outside radius", 22.7800, 75.8577, 1, True, True, False, '["can_work"]'),
    (4, "Wrong category", 22.7200, 75.8577, 2, True, True, False, '["can_work"]'),
    (5, "Unavailable", 22.7200, 75.8577, 1, False, True, False, '["can_work"]'),
    (6, "Unapproved", 22.7200, 75.8577, 1, True, False, False, '["can_work"]'),
    (7, "Suspended", 22.7200, 75.8577, 1, True, True, True, '["can_work"]'),
    (8, "Capability revoked", 22.7200, 75.8577, 1, True, True, False, '["can_chat"]'),
    (9, "Near radius edge", 22.7636, 75.8577, 1, True, True, False, '["can_work"]'),
    (10, "Past radius edge", 22.7660, 75.8577, 1, True, True, False, '["can_work"]'),
]


def _asyncpg_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


async def test_postgis_geo_executes_distance_shape_and_all_filters():
    """Run PostgisGeo itself, not a copied SQL approximation or source-code assertion."""
    assert POSTGIS_TEST_URL is not None  # narrowed after the module-level skip
    connect_args: dict = {}
    engine_options: dict = {}
    if PGLITE_SOCKET:
        # PGlite's socket bridge has no TLS and supports one PostgreSQL execution context.
        connect_args = {
            "command_timeout": 10,
            "server_settings": {},
            "ssl": False,
            "statement_cache_size": 0,
        }
        engine_options["poolclass"] = StaticPool

    engine = create_async_engine(
        _asyncpg_url(POSTGIS_TEST_URL),
        connect_args=connect_args,
        **engine_options,
    )
    connection = await engine.connect()
    schema = f"karma_postgis_{uuid.uuid4().hex}"
    session: AsyncSession | None = None
    try:
        version = (
            await connection.execute(
                text(
                    "SELECT current_setting('server_version') AS postgres, "
                    "postgis_lib_version() AS postgis"
                )
            )
        ).mappings().one()

        # A private schema makes this safe against a shared developer database. ``public`` stays
        # on the path because that is where a conventional CREATE EXTENSION installs PostGIS.
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET search_path TO "{schema}", public'))
        await connection.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    karma INTEGER NOT NULL,
                    karma_work INTEGER NOT NULL,
                    reputation_score DOUBLE PRECISION NOT NULL,
                    display_name TEXT NOT NULL,
                    handle TEXT NOT NULL,
                    avatar_url TEXT,
                    capabilities JSONB NOT NULL,
                    is_suspended BOOLEAN NOT NULL DEFAULT false
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TABLE worker_profiles (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id),
                    category_id INTEGER NOT NULL,
                    rating DOUBLE PRECISION,
                    hourly_rate NUMERIC(10, 2),
                    total_jobs INTEGER,
                    avg_response_time_seconds INTEGER,
                    verification_tier TEXT,
                    is_available BOOLEAN NOT NULL,
                    approved_at TIMESTAMPTZ,
                    lat DOUBLE PRECISION,
                    lng DOUBLE PRECISION
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TABLE posts (
                    id SERIAL PRIMARY KEY,
                    author_id INTEGER NOT NULL REFERENCES users(id),
                    kind TEXT NOT NULL
                )
                """
            )
        )

        for (
            user_id,
            label,
            lat,
            lng,
            category,
            available,
            approved,
            suspended,
            capabilities,
        ) in WORKERS:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, karma, karma_work, reputation_score, display_name, handle,
                        avatar_url, capabilities, is_suspended
                    ) VALUES (
                        :id, 70, :karma_work, 72.5, :label, :handle,
                        NULL, CAST(:capabilities AS JSONB), :suspended
                    )
                    """
                ),
                {
                    "capabilities": capabilities,
                    "handle": f"worker{user_id}",
                    "id": user_id,
                    "karma_work": 50 + user_id,
                    "label": label,
                    "suspended": suspended,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO worker_profiles (
                        user_id, category_id, rating, hourly_rate, total_jobs,
                        avg_response_time_seconds, verification_tier, is_available,
                        approved_at, lat, lng
                    ) VALUES (
                        :id, :category, 4.8, 350.00, 20,
                        300, 'gold', :available,
                        CASE WHEN :approved THEN NOW() ELSE NULL END, :lat, :lng
                    )
                    """
                ),
                {
                    "approved": approved,
                    "available": available,
                    "category": category,
                    "id": user_id,
                    "lat": lat,
                    "lng": lng,
                },
            )
        await connection.execute(
            text(
                """
                INSERT INTO posts (author_id, kind)
                VALUES (1, 'proof'), (2, 'proof'), (2, 'proof'), (7, 'proof')
                """
            )
        )
        await connection.commit()

        session = AsyncSession(bind=connection, expire_on_commit=False)
        rows = await PostgisGeo().workers_within(
            session,
            lat=ORIGIN[0],
            lng=ORIGIN[1],
            category_id=1,
            radius_km=5.0,
        )
        by_id = {row["user_id"]: row for row in rows}

        # 1 and 2 are ordinary in-range workers. 9 proves ST_DWithin includes a worker near the
        # edge. Every other row violates exactly one radius/category/status/capability gate.
        assert set(by_id) == {1, 2, 9}
        assert {3, 4, 5, 6, 7, 8, 10}.isdisjoint(by_id)
        assert all(set(row) == EXPECTED_KEYS for row in rows)
        assert {user_id: row["proof_count"] for user_id, row in by_id.items()} == {
            1: 1,
            2: 2,
            9: 0,
        }

        expected_postgis_km = {1: 0.302, 2: 0.997, 9: 4.873}
        for user_id, row in by_id.items():
            worker = next(candidate for candidate in WORKERS if candidate[0] == user_id)
            spherical_km = haversine_km(*ORIGIN, worker[2], worker[3])
            # PostGIS geography uses the WGS84 spheroid while the fallback is spherical; they
            # should remain within 25 m over this five-kilometre matching radius.
            assert row["distance_km"] == pytest.approx(expected_postgis_km[user_id], abs=0.002)
            assert row["distance_km"] == pytest.approx(spherical_km, abs=0.025)
            assert isinstance(row["distance_km"], float)

        print(  # visible under the harness's ``pytest -s`` invocation
            f"PostGIS {version['postgis']} / PostgreSQL {version['postgres']}: "
            f"eligible={sorted(by_id)}, rejected=[3, 4, 5, 6, 7, 8, 10]"
        )
    finally:
        if session is not None:
            with suppress(Exception):
                await session.close()
        with suppress(Exception):
            await connection.rollback()
            await connection.execute(text("SET search_path TO public"))
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await connection.commit()
        if PGLITE_SOCKET:
            # The WASM socket bridge does not acknowledge asyncpg's terminate packet. Invalidate
            # the already-clean test connection rather than waiting for a graceful close.
            await connection.invalidate()
        else:
            await connection.close()
        await engine.dispose()
