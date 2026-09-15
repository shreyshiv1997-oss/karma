# FIXED: Real-time tickets must be atomically consumed / can_hire requires verified
# contact — the sync socket fixtures now register through the real OTP door.
"""Real-time fanout for the gig lifecycle.

The property that matters most is *when* an event becomes visible. Every other assertion
here supports this one: a client must never be told about a state change that did not
survive the commit.
"""

from __future__ import annotations

import pytest

from app.services.realtime import (
    MAX_CONNECTIONS_PER_USER,
    Event,
    MemoryRealtime,
    drain_events,
    issue_ticket,
    queue_event,
    realtime,
    redeem_ticket,
)
from tests.conftest import (
    _phone_for,
    add_category,
    auth,
    make_worker,
    register_user,
    release_gig_payment,
    secure_gig_payment,
)



@pytest.fixture(autouse=True)
def _clean_realtime():
    """No test may inherit another test's sockets or publication log."""
    realtime.reset()
    yield
    realtime.reset()


async def _customer_with_hiring(client, session_factory, category_id: int) -> dict:
    customer = await register_user(client, handle="priya")
    granted = await client.post(
        "/api/v1/auth/capability/can_hire", headers=auth(customer["token"])
    )
    assert granted.status_code == 200, granted.text
    return customer


async def _post_gig(client, customer: dict, category_id: int, title: str = "Rewire kitchen") -> int:
    response = await client.post(
        "/api/v1/gigs",
        headers=auth(customer["token"]),
        json={
            "category_id": category_id,
            "title": title,
            "description": "Two dead sockets and a tripping breaker.",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 2,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ── the event buffer ──────────────────────────────────────────────────────────


class _FakeSession:
    """Stand-in exposing only the `.info` dict the buffer uses."""

    def __init__(self) -> None:
        self.info: dict = {}


def test_queued_events_are_held_until_drained():
    session = _FakeSession()
    queue_event(session, Event.of("gig.assigned", 1, status="assigned"))

    queue_event(session, Event.of("gig.assigned", 7, status="assigned"))
    drained = drain_events(session)
    assert len(drained) == 2
    assert {e.gig_id for e in drained} == {1, 7}
    assert drain_events(session) == [], "draining must clear the buffer"


def test_draining_a_session_with_no_events_is_not_an_error():
    assert drain_events(_FakeSession()) == []


def test_events_are_namespaced_and_timestamped():
    event = Event.of("gig.status_changed", 3, status="arrived")
    wire = event.to_wire()
    assert set(wire) == {"type", "gig_id", "data", "at"}
    assert wire["type"] == "gig.status_changed"
    assert wire["data"] == {"status": "arrived"}
    assert wire["at"], "a client needs a timestamp to order events"


# ── tickets ───────────────────────────────────────────────────────────────────


async def test_a_ticket_is_single_use():
    """★ A leaked ticket must not be replayable."""
    ticket = await issue_ticket(42)
    assert await redeem_ticket(ticket) == 42
    assert await redeem_ticket(ticket) is None, "second redemption must fail"


async def test_an_unknown_ticket_is_rejected():
    assert await redeem_ticket("not-a-real-ticket") is None


async def test_an_empty_ticket_is_rejected():
    assert await redeem_ticket("") is None


async def test_tickets_are_distinct_per_issue():
    a = await issue_ticket(1)
    b = await issue_ticket(1)
    assert a != b, "reissuing must not mint the same ticket"


# ── fanout ────────────────────────────────────────────────────────────────────


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


async def test_publish_reaches_every_subscriber_of_that_gig():
    hub = MemoryRealtime()
    a, b, other = _FakeSocket(), _FakeSocket(), _FakeSocket()
    await hub.connect(1, 10, a)
    await hub.connect(1, 11, b)
    await hub.connect(2, 12, other)  # different gig: must not receive

    delivered = await hub.publish(Event.of("gig.status_changed", 1, status="en_route"))

    assert delivered == 2
    assert a.sent[0]["type"] == "gig.status_changed"
    assert b.sent[0]["data"]["status"] == "en_route"
    assert other.sent == [], "a subscriber to another gig must not receive this event"


async def test_a_dead_socket_is_dropped_without_failing_the_broadcast():
    """One client that closed its laptop must not stop the worker hearing about the job."""
    from fastapi import WebSocketDisconnect

    hub = MemoryRealtime()

    class _Dead(_FakeSocket):
        async def send_json(self, payload: dict) -> None:
            raise WebSocketDisconnect(code=1006)

    dead, alive = _Dead(), _FakeSocket()
    await hub.connect(1, 10, dead)
    await hub.connect(1, 11, alive)

    delivered = await hub.publish(Event.of("gig.status_changed", 1, status="arrived"))

    assert delivered == 1
    assert alive.sent, "the healthy socket must still have been served"
    assert hub.channel_size(1) == 1, "the dead socket must have been pruned"


async def test_disconnect_removes_only_that_socket():
    hub = MemoryRealtime()
    a, b = _FakeSocket(), _FakeSocket()
    await hub.connect(1, 10, a)
    await hub.connect(1, 11, b)

    await hub.disconnect(1, 10, a)

    assert hub.channel_size(1) == 1
    await hub.publish(Event.of("gig.status_changed", 1, status="in_progress"))
    assert a.sent == []
    assert b.sent


async def test_the_connection_cap_is_enforced():
    """The HTTP rate limiter does not see WebSocket upgrades, so this is the only backstop."""
    hub = MemoryRealtime()
    for _ in range(MAX_CONNECTIONS_PER_USER):
        assert await hub.connect(1, 10, _FakeSocket()) is True

    assert await hub.connect(1, 10, _FakeSocket()) is False
    assert hub.channel_size(1) == MAX_CONNECTIONS_PER_USER


async def test_a_different_user_is_not_blocked_by_another_user_s_cap():
    hub = MemoryRealtime()
    for _ in range(MAX_CONNECTIONS_PER_USER):
        await hub.connect(1, 10, _FakeSocket())
    assert await hub.connect(1, 11, _FakeSocket()) is True


async def test_disconnecting_twice_does_not_underflow_the_counter():
    hub = MemoryRealtime()
    socket = _FakeSocket()
    await hub.connect(1, 10, socket)
    await hub.disconnect(1, 10, socket)
    await hub.disconnect(1, 10, socket)  # idempotent
    assert await hub.connect(1, 10, _FakeSocket()) is True


# ── end-to-end over HTTP ──────────────────────────────────────────────────────


async def test_the_ticket_endpoint_requires_authentication(client):
    response = await client.post("/api/v1/realtime/ticket")
    assert response.status_code == 401


async def test_the_ticket_endpoint_mints_a_usable_ticket(client):
    customer = await register_user(client, handle="priya")
    response = await client.post(
        "/api/v1/realtime/ticket", headers=auth(customer["token"])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ticket"]
    assert body["expires_in"] > 0
    assert body["ws_path"].startswith("/realtime/gigs/")
    assert await redeem_ticket(body["ticket"]) == customer["user"]["id"]


async def test_a_full_lifecycle_publishes_events_in_order(client, session_factory):
    """★ Hire → work → prove → review must each produce exactly one push, after commit."""
    category_id = await add_category(session_factory)
    customer = await _customer_with_hiring(client, session_factory, category_id)
    worker = await make_worker(
        client, session_factory, handle="ramesh", category_id=category_id
    )

    gig_id = await _post_gig(client, customer, category_id)

    assigned = await client.post(
        f"/api/v1/gigs/{gig_id}/assign",
        params={"worker_id": worker["user_id"]},
        headers=auth(customer["token"]),
    )
    assert assigned.status_code == 200, assigned.text
    await secure_gig_payment(client, customer, gig_id)

    for status_value in ("en_route", "arrived", "in_progress", "completion_pending"):
        moved = await client.post(
            f"/api/v1/gigs/{gig_id}/status",
            headers=auth(worker["token"]),
            json={
                "status": status_value,
                "proof_photos": [],
            },
        )
        assert moved.status_code == 200, f"{status_value}: {moved.text}"
    await release_gig_payment(client, customer, gig_id)

    reviewed = await client.post(
        f"/api/v1/gigs/{gig_id}/review",
        headers=auth(customer["token"]),
        json={
            "rating": 5,
            "punctuality": 5,
            "quality": 5,
            "communication": 5,
            "comment": "Spot on.",
        },
    )
    assert reviewed.status_code == 201, reviewed.text

    types = [e.type for e in realtime.published if e.gig_id == gig_id]
    assert types == [
        "gig.assigned",
        "gig.payment_updated",  # authorization created
        "gig.status_changed",  # en_route
        "gig.status_changed",  # arrived
        "gig.status_changed",  # in_progress
        "gig.status_changed",  # completion_pending
        "gig.payment_released",  # captured, completed, and paid
        "gig.reviewed",
    ]

    final = realtime.published[-1]
    assert final.type == "gig.reviewed"
    assert final.data["rating"] == 5


async def test_a_rejected_transition_publishes_nothing(client, session_factory):
    """★ An illegal move raises 409 and must leave no event behind."""
    category_id = await add_category(session_factory)
    customer = await _customer_with_hiring(client, session_factory, category_id)
    await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    gig_id = await _post_gig(client, customer, category_id)

    stranger = await register_user(client, handle="outsider")
    illegal = await client.post(
        f"/api/v1/gigs/{gig_id}/status",
        headers=auth(stranger["token"]),
        json={"status": "completed"},
    )
    assert illegal.status_code == 403

    assert [e for e in realtime.published if e.gig_id == gig_id] == [], (
        "a rejected transition must never be announced"
    )


async def test_a_rolled_back_request_publishes_nothing(client, session_factory):
    """★ The buffer is drained on rollback, so an undone write is never announced.

    This is the invariant the whole design exists to protect: the original design broadcast
    from inside the handler, so a client could be told a gig was completed and then watch
    the transaction roll back.
    """
    category_id = await add_category(session_factory)
    customer = await _customer_with_hiring(client, session_factory, category_id)
    worker = await make_worker(
        client, session_factory, handle="ramesh", category_id=category_id
    )
    gig_id = await _post_gig(client, customer, category_id)
    await client.post(
        f"/api/v1/gigs/{gig_id}/assign",
        params={"worker_id": worker["user_id"]},
        headers=auth(customer["token"]),
    )
    await secure_gig_payment(client, customer, gig_id)

    before = len(realtime.published)

    # Drive the gig to a terminal state, then attempt a transition the state machine forbids.
    for status_value in ("en_route", "arrived", "in_progress", "completion_pending"):
        await client.post(
            f"/api/v1/gigs/{gig_id}/status",
            headers=auth(worker["token"]),
            json={"status": status_value, "proof_photos": []},
        )
    await release_gig_payment(client, customer, gig_id)
    after_completion = len(realtime.published)
    assert after_completion > before

    impossible = await client.post(
        f"/api/v1/gigs/{gig_id}/status",
        headers=auth(worker["token"]),
        json={"status": "en_route"},
    )
    assert impossible.status_code == 409
    assert len(realtime.published) == after_completion, "no event for a failed transition"


async def test_events_carry_the_gig_id_and_reach_only_that_gig(client, session_factory):
    category_id = await add_category(session_factory)
    customer = await _customer_with_hiring(client, session_factory, category_id)
    worker = await make_worker(
        client, session_factory, handle="ramesh", category_id=category_id
    )

    first = await _post_gig(client, customer, category_id, title="Paint a wall")
    second = await _post_gig(client, customer, category_id, title="Fix a leak")

    await client.post(
        f"/api/v1/gigs/{first}/assign",
        params={"worker_id": worker["user_id"]},
        headers=auth(customer["token"]),
    )

    assert {e.gig_id for e in realtime.published} == {first}
    assert all(e.gig_id != second for e in realtime.published), (
        "an unrelated gig must not appear in another gig's stream"
    )


async def test_a_missing_gig_publishes_nothing(client, session_factory):
    await add_category(session_factory)
    worker = await make_worker(
        client, session_factory, handle="ramesh", category_id=1
    )
    before = len(realtime.published)

    response = await client.post(
        "/api/v1/gigs/999999/status",
        headers=auth(worker["token"]),
        json={"status": "cancelled"},
    )
    assert response.status_code == 404
    assert len(realtime.published) == before


# ── the actual socket handshake ───────────────────────────────────────────────
#
# Everything above exercises the publisher and the manager. These drive a real WebSocket
# through the ASGI app, so the handshake, the ticket check, the authorisation check and the
# snapshot frame are all executed rather than assumed.

from starlette.testclient import TestClient  # noqa: E402

from app.core.db import get_session as _get_session  # noqa: E402
from app.core.db import get_session_factory as _get_session_factory  # noqa: E402
from app.core.db import session_scope as _session_scope  # noqa: E402
from app.main import app as _app  # noqa: E402


@pytest.fixture
def socket_client(session_factory):
    """A TestClient, because httpx has no WebSocket support.

    The override must itself *be* an async generator function -- returning a generator from a
    plain function hands FastAPI an object with no ``.scalar`` and the request fails.
    """

    async def _override():
        async with session_factory() as s:
            async for value in _session_scope(s):
                yield value

    _app.dependency_overrides[_get_session] = _override
    # The WebSocket route cannot use the request-scoped session for its whole lifetime, so it
    # depends on the factory instead. Overriding only `get_session` left the authorisation
    # query reading the real database, and every socket was refused with 4403.
    _app.dependency_overrides[_get_session_factory] = lambda: session_factory
    with TestClient(_app) as c:
        yield c
    _app.dependency_overrides.clear()


def test_a_socket_without_a_ticket_is_refused(socket_client):
    """★ Refused before accept, so no unauthenticated socket is ever held open.

    Note on what this does and does not prove. The route calls ``websocket.close(4401)``
    *before* ``accept()``, and Starlette turns that into an **HTTP 403 on the handshake** --
    the 4401 close code is never transmitted, because no WebSocket is ever established.
    Starlette's TestClient skips the HTTP layer and surfaces the close code instead, so this
    assertion checks the application's *intent* (refuse, don't accept) rather than the bytes
    a browser receives.

    The wire-level behaviour is covered by ``scripts/live_socket_journey.py``, which asserts
    HTTP 403 against a running server.
    """
    with pytest.raises(Exception) as excinfo:
        with socket_client.websocket_connect("/api/v1/realtime/gigs/1"):
            pass
    assert "4401" in str(excinfo.value) or getattr(excinfo.value, "code", None) == 4401


def test_a_socket_with_a_forged_ticket_is_refused(socket_client):
    with pytest.raises(Exception) as excinfo:
        with socket_client.websocket_connect(
            "/api/v1/realtime/gigs/1?ticket=absolutely-not-valid"
        ):
            pass
    assert "4401" in str(excinfo.value) or getattr(excinfo.value, "code", None) == 4401


def test_a_ticket_cannot_be_spent_twice(socket_client, session_factory):
    """★ The first connect consumes it; the second must be refused."""
    token = _mint_token(socket_client, "priya")
    gig_id = _create_gig(socket_client, token, session_factory)
    ticket = socket_client.post(
        "/api/v1/realtime/ticket", headers={"Authorization": f"Bearer {token}"}
    ).json()["ticket"]

    with socket_client.websocket_connect(f"/api/v1/realtime/gigs/{gig_id}?ticket={ticket}") as ws:
        assert ws.receive_json()["type"] == "gig.snapshot"

    with pytest.raises(Exception):
        with socket_client.websocket_connect(f"/api/v1/realtime/gigs/{gig_id}?ticket={ticket}"):
            pass


def test_a_stranger_cannot_watch_someone_elses_gig(socket_client, session_factory):
    """★ Labour Link accepted any connection for any job id. This must not."""
    owner = _mint_token(socket_client, "priya")
    gig_id = _create_gig(socket_client, owner, session_factory)

    intruder = _mint_token(socket_client, "intruder")
    ticket = socket_client.post(
        "/api/v1/realtime/ticket", headers={"Authorization": f"Bearer {intruder}"}
    ).json()["ticket"]

    with pytest.raises(Exception) as excinfo:
        with socket_client.websocket_connect(f"/api/v1/realtime/gigs/{gig_id}?ticket={ticket}"):
            pass
    assert "4403" in str(excinfo.value) or getattr(excinfo.value, "code", None) == 4403


def test_a_connected_socket_receives_a_snapshot_then_live_events(socket_client, session_factory):
    """★ The real end-to-end path: subscribe, then change state over HTTP, then see it arrive."""
    token = _mint_token(socket_client, "priya")
    socket_client.post("/api/v1/auth/capability/can_hire", headers={"Authorization": f"Bearer {token}"})
    gig_id = _create_gig(socket_client, token, session_factory)

    ticket = socket_client.post(
        "/api/v1/realtime/ticket", headers={"Authorization": f"Bearer {token}"}
    ).json()["ticket"]

    with socket_client.websocket_connect(f"/api/v1/realtime/gigs/{gig_id}?ticket={ticket}") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "gig.snapshot"
        assert snapshot["data"]["status"] == "searching"

        cancelled = socket_client.post(
            f"/api/v1/gigs/{gig_id}/status",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "cancelled"},
        )
        assert cancelled.status_code == 200, cancelled.text

        pushed = ws.receive_json()
        assert pushed["type"] == "gig.status_changed"
        assert pushed["data"]["status"] == "cancelled"
        assert pushed["gig_id"] == gig_id


def test_the_socket_answers_an_application_ping(socket_client, session_factory):
    token = _mint_token(socket_client, "priya")
    gig_id = _create_gig(socket_client, token, session_factory)
    ticket = socket_client.post(
        "/api/v1/realtime/ticket", headers={"Authorization": f"Bearer {token}"}
    ).json()["ticket"]

    with socket_client.websocket_connect(f"/api/v1/realtime/gigs/{gig_id}?ticket={ticket}") as ws:
        assert ws.receive_json()["type"] == "gig.snapshot"
        ws.send_text("ping")
        assert ws.receive_json()["type"] == "pong"


def _create_gig(client: TestClient, token: str, session_factory) -> int:
    """Post a gig the caller owns, granting can_hire if needed."""
    from sqlalchemy import select

    from app.models.marketplace import ServiceCategory

    import asyncio

    async def _ensure_category() -> int:
        async with session_factory() as s:
            existing = await s.scalar(select(ServiceCategory.id).limit(1))
            if existing is not None:
                return int(existing)
            from decimal import Decimal

            cat = ServiceCategory(
                name="Electrical",
                slug="electrical",
                emoji="⚡",
                description="Wiring, fans, fittings",
                base_fare=Decimal("200"),
                per_km_rate=Decimal("18"),
                per_hour_rate=Decimal("350"),
            )
            s.add(cat)
            await s.commit()
            return cat.id

    # A fresh loop: TestClient drives its own portal thread, and `get_event_loop()` is
    # unreliable from a sync test body.
    category_id = asyncio.run(_ensure_category())

    client.post("/api/v1/auth/capability/can_hire", headers={"Authorization": f"Bearer {token}"})
    response = client.post(
        "/api/v1/gigs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "category_id": category_id,
            "title": "Rewire the kitchen",
            "description": "Two dead sockets.",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 2,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _mint_token(client: TestClient, handle: str) -> str:
    """Register through the phone door, completing the real OTP exchange.

    ``can_hire`` now requires a contact detail somebody actually proved they own, so an
    email-only registration can no longer post a gig. Doing the OTP round-trip here is
    what a real customer does; the previous shortcut only worked because the capability
    was grantable on nothing at all.
    """
    number = _phone_for(handle)
    sent = client.post("/api/v1/auth/otp/send", json={"phone": number})
    assert sent.status_code == 200, sent.text
    code = sent.json()["dev_otp"]
    assert code, "test environment must expose dev_otp"
    verified = client.post("/api/v1/auth/otp/verify", json={"phone": number, "otp": code})
    assert verified.status_code == 200, verified.text

    response = client.post(
        "/api/v1/auth/register",
        json={
            "handle": handle,
            "display_name": handle.title(),
            "email": f"{handle}@example.com",
            "phone": number,
            "password": "StrongPass!234",
            "city": "Indore",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]
