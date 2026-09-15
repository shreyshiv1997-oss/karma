"""Health probes and matching error paths.

The health endpoints had never been called by a test. A probe that is never exercised is a
probe that can 500 in production and take the deployment down with it -- Kubernetes reads
`/health/ready` as the gate for sending traffic.
"""

from __future__ import annotations

import pytest

from tests.conftest import add_category, auth, make_worker, register_user

pytestmark = pytest.mark.asyncio


# ── health ────────────────────────────────────────────────────────────────────


async def test_the_root_descriptor_reports_the_active_backends(client):
    """★ The descriptor is what tells an operator which port implementations are live."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["name"]
    assert body["version"]
    assert body["environment"]
    # Neither Postgres nor Redis exists in the test environment, so both must report the
    # in-process fallback. If this ever flips, a real dependency has leaked into the tests.
    assert body["geo_backend"] == "haversine"
    assert body["cache_backend"] == "memory"
    assert body["realtime_backend"] == "memory"
    assert body["object_storage_backend"] == "local"
    assert body["geocoding_backend"] == "disabled"


async def test_liveness_does_not_require_anything(client):
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_readiness_reports_a_reachable_database(client):
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


async def test_readiness_degrades_when_redis_subscription_is_lost(client, monkeypatch):
    from app.routers import health
    from app.services.realtime import RedisRealtime

    hub = RedisRealtime(
        "redis://unused",
        channel="karma:test:health",
        redis_client=object(),
    )
    monkeypatch.setattr(health, "realtime", hub)

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "database": "ok",
        "realtime": "redis_subscription_unavailable",
    }


async def test_readiness_degrades_instead_of_failing_when_the_database_goes_away(client, monkeypatch):
    """★ A dead database must produce a 200 with `degraded`, not a 500.

    A 500 from a readiness probe looks like an application crash; the orchestrator restarts the
    pod in a loop instead of holding traffic until the database returns.
    """
    from app.routers import health

    class _Boom:
        def connect(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(health, "engine", _Boom())

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200, "the probe itself must stay up"
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"
    assert "connection refused" in body["detail"]


async def test_health_needs_no_authentication(client):
    """Probes are called by the orchestrator, which holds no user token."""
    for path in ("/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready"):
        response = await client.get(path)
        assert response.status_code == 200, f"{path} must be public"


# ── matching ──────────────────────────────────────────────────────────────────


async def test_categories_are_listed(client, session_factory):
    await add_category(session_factory)
    await add_category(session_factory, name="Plumbing", slug="plumbing", emoji="🔧")

    response = await client.get("/api/v1/categories")
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 2
    assert {r["slug"] for r in rows} == {"electrical", "plumbing"}
    assert all("base_fare" in r for r in rows)


async def test_matching_a_missing_gig_is_a_404(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="priya")
    response = await client.post(
        "/api/v1/matching/find", headers=auth(user["token"]), json={"gig_id": 999999}
    )
    assert response.status_code == 404


async def _hirer(client, handle="priya") -> dict:
    """A user holding `can_hire`, which `POST /gigs` requires."""
    user = await register_user(client, handle=handle)
    granted = await client.post("/api/v1/auth/capability/can_hire", headers=auth(user["token"]))
    assert granted.status_code == 200, granted.text
    return user


async def test_matching_a_gig_belonging_to_someone_else_is_a_403(client, session_factory):
    """★ The match list reveals who is nearby and available. It is not public."""
    category_id = await add_category(session_factory)
    owner = await _hirer(client, handle="priya")
    await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    gig = await client.post(
        "/api/v1/gigs",
        headers=auth(owner["token"]),
        json={
            "category_id": category_id,
            "title": "Rewire the kitchen",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 2,
        },
    )
    gig_id = gig.json()["id"]

    intruder = await register_user(client, handle="intruder")
    response = await client.post(
        "/api/v1/matching/find", headers=auth(intruder["token"]), json={"gig_id": gig_id}
    )
    assert response.status_code == 403, "someone else's gig must not disclose who is available"


async def test_matching_yields_the_nearby_worker(client, session_factory):
    category_id = await add_category(session_factory)
    owner = await _hirer(client, handle="priya")
    await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    gig = await client.post(
        "/api/v1/gigs",
        headers=auth(owner["token"]),
        json={
            "category_id": category_id,
            "title": "Rewire the kitchen",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 2,
        },
    )
    response = await client.post(
        "/api/v1/matching/find",
        headers=auth(owner["token"]),
        json={"gig_id": gig.json()["id"]},
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) >= 1
    assert rows[0]["handle"] == "ramesh"
    assert rows[0]["score"] > 0


async def test_a_missing_worker_profile_is_a_404(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="priya")
    assert (await client.get("/api/v1/workers/999999", headers=auth(user["token"]))).status_code == 404


async def test_a_verified_user_who_is_not_a_worker_is_a_404(client, session_factory):
    """A user can exist and be verified without ever having opened a worker profile."""
    await add_category(session_factory)
    user = await register_user(client, handle="priya")
    viewer = await register_user(client, handle="viewer")

    response = await client.get(
        f"/api/v1/workers/{user['user']['id']}", headers=auth(viewer["token"])
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Not a registered worker"


async def test_a_worker_public_profile_is_readable(client, session_factory):
    category_id = await add_category(session_factory)
    worker = await make_worker(client, session_factory, handle="ramesh", category_id=category_id)
    viewer = await register_user(client, handle="viewer")

    response = await client.get(
        f"/api/v1/workers/{worker['user_id']}", headers=auth(viewer["token"])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["handle"] == "ramesh"
    assert body["verification_tier"] == "gold"
    assert "email" not in body, "contact details stay private until a gig is agreed"
    assert "phone" not in body
