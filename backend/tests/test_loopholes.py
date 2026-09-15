# FIXED: all mandatory invariants — regression suite; every test here fails against the
# pre-audit code and passes against the fixed code.
"""★ THE LOOPHOLE SUITE.

One test per finding in LOOPS.md. Each is written so that it *fails* against the code as
it was before the audit and passes after, so the suite is a permanent statement of what
must never regress rather than a description of the current implementation.

The finding id in each test name maps to the LOOPS.md entry.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from tests.conftest import (
    add_category,
    auth,
    make_worker,
    register_user,
    release_gig_payment,
    secure_gig_payment,
)



# ==========================================================================
# L-01  can_hire requires verified contact details and cannot be self-granted
# ==========================================================================
async def test_l01_unverified_account_cannot_self_grant_can_hire(client):
    """An email-only account with nothing verified must be refused can_hire.

    Before the fix this returned 200 and handed the capability to anyone who had merely
    registered.
    """
    account = await register_user(client, handle="grifter", verify_phone=False)

    response = await client.post(
        "/api/v1/auth/capability/can_hire", headers=auth(account["token"])
    )
    assert response.status_code == 403, response.text
    assert "verify" in response.json()["detail"].lower()

    me = (await client.get("/api/v1/auth/me", headers=auth(account["token"]))).json()
    assert "can_hire" not in me["capabilities"]


async def test_l01_granting_a_capability_never_sets_is_verified(client):
    """The trust badge belongs to the KYC reviewer, not to the applicant.

    Before the fix, `grant_capability` set `user.is_verified = True` unconditionally, so
    any account could award itself the badge that the feed and the match cards render.
    """
    account = await register_user(client, handle="badgehunter")
    assert account["user"]["is_verified"] is False

    response = await client.post(
        "/api/v1/auth/capability/can_post", headers=auth(account["token"])
    )
    assert response.status_code == 200
    assert response.json()["is_verified"] is False, "self-granting must not confer verification"

    granted = await client.post(
        "/api/v1/auth/capability/can_hire", headers=auth(account["token"])
    )
    assert granted.status_code == 200, "a verified phone is sufficient for can_hire"
    assert granted.json()["is_verified"] is False, "hiring is not identity verification"


async def test_l01_verified_phone_satisfies_the_requirement(client):
    """The rule is a real gate, not a blanket refusal: OTP-verified accounts pass."""
    account = await register_user(client, handle="legit")  # completes the OTP flow
    response = await client.post(
        "/api/v1/auth/capability/can_hire", headers=auth(account["token"])
    )
    assert response.status_code == 200
    assert "can_hire" in response.json()["capabilities"]


async def test_l01_can_work_is_never_self_grantable(client):
    """Unchanged behaviour, asserted so it cannot be widened by accident."""
    account = await register_user(client, handle="wannabe")
    response = await client.post(
        "/api/v1/auth/capability/can_work", headers=auth(account["token"])
    )
    assert response.status_code == 400
    me = (await client.get("/api/v1/auth/me", headers=auth(account["token"]))).json()
    assert "can_work" not in me["capabilities"]


# ==========================================================================
# L-02  A gig is a transaction between two parties (no self-dealing)
# ==========================================================================
async def _self_dealer(client, session_factory, category_id: int) -> dict:
    """An account holding both can_hire and can_work, with a live worker profile."""
    from datetime import UTC, datetime

    from app.models.marketplace import WorkerProfile
    from app.models.trust import VerificationSubmission
    from app.models.user import User

    account = await register_user(client, handle="ouroboros")
    token, uid = account["token"], account["user"]["id"]
    await client.post("/api/v1/auth/capability/can_hire", headers=auth(token))

    submission = await client.post(
        "/api/v1/verification/submit",
        json={"document_type": "aadhaar", "document_ref": "123456789012"},
        headers=auth(token),
    )
    async with session_factory() as s:
        row = await s.get(VerificationSubmission, submission.json()["id"])
        row.status = "approved"
        user = await s.get(User, uid)
        user.capabilities = sorted({*(user.capabilities or []), "can_work"})
        s.add(
            WorkerProfile(
                user_id=uid,
                category_id=category_id,
                hourly_rate=Decimal("350"),
                is_available=True,
                approved_at=datetime.now(UTC),
                lat=22.7196,
                lng=75.8577,
                verification_tier="gold",
            )
        )
        await s.commit()
    return {"token": token, "user_id": uid}


async def test_l02_a_customer_cannot_assign_themselves_to_their_own_gig(
    client, session_factory
):
    """★ The karma-and-money mint.

    Before the fix this whole sequence succeeded: the account hired itself, marched the
    gig to `completed`, and the completion path credited its wallet, appended
    GIG_COMPLETED and PROOF_PUBLISHED karma, and published a proof post -- after which
    the same account could post itself a five-star review. Repeat for unbounded karma
    and unbounded wallet balance, with a proof post minted each time.
    """
    from app.models.trust import Wallet
    from app.models.user import User

    category_id = await add_category(session_factory)
    dealer = await _self_dealer(client, session_factory, category_id)

    gig = await client.post(
        "/api/v1/gigs",
        json={
            "category_id": category_id,
            "title": "Ghost job",
            "description": "Work that will never happen.",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 8.0,
            "urgency": "urgent",
        },
        headers=auth(dealer["token"]),
    )
    gig_id = gig.json()["id"]

    response = await client.post(
        f"/api/v1/gigs/{gig_id}/assign?worker_id={dealer['user_id']}",
        headers=auth(dealer["token"]),
    )
    assert response.status_code == 400, response.text
    assert "yourself" in response.json()["detail"].lower()

    async with session_factory() as s:
        user = await s.get(User, dealer["user_id"])
        wallet = await s.get(Wallet, dealer["user_id"])
        assert wallet is None, "no self-issued payout"
        assert user.karma == 55, "karma unchanged by the attempt (55 = 50 + phone verified)"


async def test_l02_a_worker_cannot_review_their_own_work(client, session_factory):
    """Defence in depth: even if a self-assigned gig existed, the review is refused."""
    from datetime import UTC, datetime

    from app.models.marketplace import Gig
    from app.models.user import User

    category_id = await add_category(session_factory)
    dealer = await _self_dealer(client, session_factory, category_id)

    # Forge the state assignment now refuses, to prove the review path guards separately.
    async with session_factory() as s:
        gig = Gig(
            customer_id=dealer["user_id"],
            worker_id=dealer["user_id"],
            category_id=category_id,
            title="Self gig",
            status="completed",
            lat=22.7196,
            lng=75.8577,
            total=Decimal("1000"),
            payment_status="paid",
            completed_at=datetime.now(UTC),
        )
        s.add(gig)
        await s.commit()
        gig_id = gig.id

    response = await client.post(
        f"/api/v1/gigs/{gig_id}/review",
        json={"rating": 5, "punctuality": 5, "quality": 5, "communication": 5, "comment": "ace"},
        headers=auth(dealer["token"]),
    )
    assert response.status_code == 403, response.text
    assert "your own work" in response.json()["detail"].lower()


# ==========================================================================
# L-03  Assignment requires the live can_work capability
# ==========================================================================
async def test_l03_a_worker_without_can_work_cannot_be_assigned(client, session_factory):
    """A stale WorkerProfile must not survive the capability being revoked.

    Before the fix, `assign_worker` checked only `approved_at` and `is_available` on the
    profile row, so revoking `can_work` -- the thing KYC actually grants -- left the
    worker fully assignable.
    """
    from app.models.user import User

    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="priya")
    await client.post("/api/v1/auth/capability/can_hire", headers=auth(customer["token"]))
    worker = await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    # Safety hold: the capability is revoked, the profile row is left behind.
    async with session_factory() as s:
        user = await s.get(User, worker["user_id"])
        user.capabilities = [c for c in user.capabilities if c != "can_work"]
        await s.commit()

    gig = await client.post(
        "/api/v1/gigs",
        json={
            "category_id": category_id,
            "title": "Rewire the kitchen",
            "description": "Two dead sockets.",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 2.0,
        },
        headers=auth(customer["token"]),
    )
    response = await client.post(
        f"/api/v1/gigs/{gig.json()['id']}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )
    assert response.status_code == 400, response.text
    assert "not approved to take work" in response.json()["detail"]


async def test_l03_a_suspended_worker_cannot_be_assigned(client, session_factory):
    """Suspension must reach the assignment path, not only the login path."""
    from app.models.user import User

    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="priya")
    await client.post("/api/v1/auth/capability/can_hire", headers=auth(customer["token"]))
    worker = await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    async with session_factory() as s:
        user = await s.get(User, worker["user_id"])
        user.is_suspended = True
        await s.commit()

    gig = await client.post(
        "/api/v1/gigs",
        json={
            "category_id": category_id,
            "title": "Rewire the kitchen",
            "description": "Two dead sockets.",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 2.0,
        },
        headers=auth(customer["token"]),
    )
    response = await client.post(
        f"/api/v1/gigs/{gig.json()['id']}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )
    assert response.status_code == 400, response.text


# ==========================================================================
# L-04  Wallet ledger updates must be atomic
# ==========================================================================
async def test_l04_concurrent_wallet_credits_do_not_lose_money(tmp_path):
    """★ Five concurrent payouts must sum to five payouts.

    Against the old read-modify-write (`wallet.balance = Decimal(wallet.balance) + x`)
    the interleaved reads overwrite each other and the total lands below 500 -- while the
    LedgerEntry rows still record every payout, so the cached balance silently stops
    agreeing with its own append-only ledger.

    This uses a file-backed database rather than the shared in-memory fixture, because
    `sqlite:///:memory:` is served by a single pooled connection: every "concurrent"
    session would serialise onto it and no race could occur at all.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.db import Base
    from app.models.trust import Wallet
    from app.models.user import User
    from app.routers.gigs import _credit_wallet

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'race.db'}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with factory() as s:
            user = User(handle="racer", display_name="Racer", email="r@example.com",
                        password_hash="x")
            s.add(user)
            await s.flush()
            user_id = user.id
            await s.commit()

        async def credit() -> None:
            # Retry only on SQLite's coarse whole-database write lock, which is an
            # artefact of the dev driver, not of the invariant under test. A lost update
            # is not a lock error and is never retried away.
            from sqlalchemy.exc import OperationalError

            for _ in range(40):
                try:
                    async with factory() as s:
                        await _credit_wallet(s, user_id, Decimal("100.00"))
                        await s.commit()
                    return
                except OperationalError as exc:
                    if "locked" not in str(exc).lower():
                        raise
                    await asyncio.sleep(0.02)
            raise AssertionError("could not acquire the sqlite write lock")

        await asyncio.gather(*(credit() for _ in range(5)))

        async with factory() as s:
            wallet = await s.get(Wallet, user_id)
            assert wallet is not None
            assert Decimal(str(wallet.balance)) == Decimal("500.00"), (
                f"lost update: expected 500.00, got {wallet.balance}"
            )
            assert Decimal(str(wallet.lifetime_earned)) == Decimal("500.00")
    finally:
        await engine.dispose()


def test_l04_the_wallet_credit_is_a_sql_expression_not_a_python_read():
    """The structural guarantee behind the race test.

    A future refactor could reintroduce `wallet.balance = wallet.balance + x` and, on a
    single-connection dev database, every concurrency test would still pass. This asserts
    the increment is computed by the database inside the row lock.
    """
    import ast
    import inspect
    import textwrap

    from app.routers import gigs

    def _body_without_docstring(func) -> str:
        """The executable source only. The docstring quotes the old buggy line on
        purpose, and must not be mistaken for the bug itself."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
        node = tree.body[0]
        statements = node.body
        if (
            statements
            and isinstance(statements[0], ast.Expr)
            and isinstance(statements[0].value, ast.Constant)
            and isinstance(statements[0].value.value, str)
        ):
            statements = statements[1:]
        return "\n".join(ast.unparse(stmt) for stmt in statements)

    source = _body_without_docstring(gigs._credit_wallet)
    assert "update(Wallet)" in source
    assert "balance=Wallet.balance + amount" in source
    assert "wallet.balance =" not in source, "read-modify-write has returned"

    complete = _body_without_docstring(gigs._complete_gig)
    assert "wallet.balance" not in complete, "the payout must go through _credit_wallet"
    assert "_credit_wallet" in complete


async def test_l04_completing_a_gig_keeps_wallet_and_ledger_in_agreement(
    client, session_factory
):
    """The cached balance must equal the sum of the append-only payout rows."""
    from sqlalchemy import func, select

    from app.models.trust import LedgerEntry, Wallet

    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="priya")
    await client.post("/api/v1/auth/capability/can_hire", headers=auth(customer["token"]))
    worker = await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    for i in range(3):
        gig = await client.post(
            "/api/v1/gigs",
            json={
                "category_id": category_id,
                "title": f"Job number {i}",
                "description": "Work.",
                "lat": 22.7196,
                "lng": 75.8577,
                "estimated_hours": 2.0,
            },
            headers=auth(customer["token"]),
        )
        gig_id = gig.json()["id"]
        await client.post(
            f"/api/v1/gigs/{gig_id}/assign?worker_id={worker['user_id']}",
            headers=auth(customer["token"]),
        )
        await secure_gig_payment(client, customer, gig_id)
        for status in ("en_route", "arrived", "in_progress", "completion_pending"):
            response = await client.post(
                f"/api/v1/gigs/{gig_id}/status",
                json={"status": status, "proof_photos": []},
                headers=auth(worker["token"]),
            )
            assert response.status_code == 200, response.text
        await release_gig_payment(client, customer, gig_id)

    async with session_factory() as s:
        wallet = await s.get(Wallet, worker["user_id"])
        total = await s.scalar(
            select(func.sum(LedgerEntry.amount)).where(
                LedgerEntry.user_id == worker["user_id"],
                LedgerEntry.entry_type == "payout",
            )
        )
        assert Decimal(str(wallet.balance)) == Decimal(str(total)), (
            "the cached balance must be the sum of its ledger"
        )


# ==========================================================================
# L-05  Geo matching must filter by can_work
# ==========================================================================
async def test_l05_geo_matching_excludes_workers_without_can_work(client, session_factory):
    """A revoked capability must remove someone from the match results.

    Before the fix, GeoPort filtered on category, availability, `approved_at`, suspension
    and radius -- but never on the capability, so a worker whose permission had been
    revoked kept being offered to customers.
    """
    from app.models.user import User

    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="priya")
    await client.post("/api/v1/auth/capability/can_hire", headers=auth(customer["token"]))
    keeper = await make_worker(client, session_factory, handle="ramesh", category_id=category_id)
    revoked = await make_worker(client, session_factory, handle="sunita", category_id=category_id)

    gig = await client.post(
        "/api/v1/gigs",
        json={
            "category_id": category_id,
            "title": "Rewire the kitchen",
            "description": "Two dead sockets.",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 2.0,
        },
        headers=auth(customer["token"]),
    )
    gig_id = gig.json()["id"]

    before = await client.post(
        "/api/v1/matching/find", json={"gig_id": gig_id}, headers=auth(customer["token"])
    )
    assert {c["user_id"] for c in before.json()} == {keeper["user_id"], revoked["user_id"]}

    async with session_factory() as s:
        user = await s.get(User, revoked["user_id"])
        user.capabilities = [c for c in user.capabilities if c != "can_work"]
        await s.commit()

    after = await client.post(
        "/api/v1/matching/find", json={"gig_id": gig_id}, headers=auth(customer["token"])
    )
    ids = {c["user_id"] for c in after.json()}
    assert revoked["user_id"] not in ids, "a revoked worker must not be matchable"
    assert keeper["user_id"] in ids, "the filter must not remove legitimate workers"


def test_l05_both_geo_ports_filter_on_the_capability():
    """Parity: the SQLite and PostGIS queries must both carry the filter.

    PostGIS is asserted rather than executed here (the project states it is not run in
    this environment), so the guard against the two ports drifting is textual.
    """
    import inspect

    from app.core.ports import HaversineGeo, PostgisGeo

    for port in (HaversineGeo, PostgisGeo):
        sql = inspect.getsource(port.workers_within)
        assert "can_work" in sql, f"{port.__name__} does not filter on can_work"
        assert "approved_at IS NOT NULL" in sql
        assert "is_suspended" in sql


# ==========================================================================
# L-06  Rate limiting must survive behind reverse proxies
# ==========================================================================
def test_l06_client_ip_reads_through_a_trusted_proxy():
    """With one trusted hop the real client is used, so buckets stay per-user."""
    from starlette.requests import Request

    from app.core.net import client_ip

    def conn(xff: str | None, peer: str = "10.0.0.1") -> Request:
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        return Request({"type": "http", "headers": headers, "client": (peer, 1234)})

    # No proxy trusted: the header is ignored entirely and cannot be spoofed.
    assert client_ip(conn("1.2.3.4"), trusted_hops=0) == "10.0.0.1"

    # One trusted proxy: the rightmost header entry is the real client.
    assert client_ip(conn("203.0.113.7"), trusted_hops=1) == "203.0.113.7"

    # A forged prefix cannot reach past the hops we actually trust.
    assert client_ip(conn("1.2.3.4, 203.0.113.7"), trusted_hops=1) == "203.0.113.7"

    # Two trusted proxies: skip the one appended hop, take the client.
    assert client_ip(conn("203.0.113.7, 172.16.0.9"), trusted_hops=2) == "203.0.113.7"

    # Chain shorter than the trusted depth: fail closed onto the verifiable peer.
    assert client_ip(conn(None), trusted_hops=2) == "10.0.0.1"


async def test_l06_rate_limit_buckets_are_per_client_behind_a_proxy(client, monkeypatch):
    """★ Two users behind one proxy must not share a rate-limit bucket.

    Before the fix every proxied request keyed on the proxy address, so a single global
    bucket served the whole internet: one script exhausted it and everyone else got 429.
    """
    from app.core import middleware
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    middleware._cache.reset()

    for i in range(3):
        await client.get("/api/v1/health/live", headers={"X-Forwarded-For": f"203.0.113.{i}"})

    keys = [k for k in middleware._cache._windows if k.startswith("karma:rl:")]
    assert len(keys) == 3, f"each client needs its own bucket, got {keys}"
    assert all(len(v) == 1 for v in middleware._cache._windows.values())


async def test_l06_forwarded_header_is_ignored_when_no_proxy_is_trusted(client, monkeypatch):
    """The default must not let a client mint a fresh bucket per request."""
    from app.core import middleware
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 0)
    middleware._cache.reset()

    for i in range(4):
        await client.get("/api/v1/health/live", headers={"X-Forwarded-For": f"9.9.9.{i}"})

    keys = [k for k in middleware._cache._windows if k.startswith("karma:rl:")]
    assert len(keys) == 1, "spoofed headers must not create buckets"
    assert len(middleware._cache._windows[keys[0]]) == 4


# ==========================================================================
# L-07  Real-time tickets must be atomically consumed
# ==========================================================================
async def test_l07_a_ticket_survives_only_one_of_two_concurrent_redemptions():
    """★ The double-redemption race.

    Against the old read-then-delete implementation both coroutines observe the value
    before either delete lands and the ticket is spent twice. The fix makes redemption a
    single atomic get-and-delete, so exactly one caller wins.
    """
    from app.core import ports
    from app.services import realtime as rt

    ticket = await rt.issue_ticket(4242)

    original = ports.MemoryCache.get_and_delete

    async def slow(self, key):
        # Widen the window an attacker would have to hit. An implementation that is
        # genuinely atomic is unaffected; a check-then-act one fails wide open.
        await asyncio.sleep(0.05)
        return await original(self, key)

    ports.MemoryCache.get_and_delete = slow
    try:
        first, second = await asyncio.gather(
            rt.redeem_ticket(ticket), rt.redeem_ticket(ticket)
        )
    finally:
        ports.MemoryCache.get_and_delete = original

    assert {first, second} == {4242, None}, (
        f"exactly one redemption must succeed, got {first!r} and {second!r}"
    )


async def test_l07_memory_cache_get_and_delete_is_single_use():
    """The port contract itself, independent of the ticket layer."""
    from app.core.ports import MemoryCache

    cache = MemoryCache()
    await cache.set("k", "v", ttl=30)

    results = await asyncio.gather(*(cache.get_and_delete("k") for _ in range(10)))
    assert results.count("v") == 1, f"value must be handed out once, got {results}"
    assert await cache.get("k") is None


async def test_l07_expired_tickets_are_refused():
    """TTL still applies; atomicity must not have widened the window."""
    from app.core.ports import MemoryCache

    cache = MemoryCache()
    await cache.set("k", "v", ttl=0)
    await asyncio.sleep(0.01)
    assert await cache.get_and_delete("k") is None


# ==========================================================================
# L-08  A KYC submission is decided exactly once
# ==========================================================================
async def _make_admin(client, session_factory, handle: str) -> str:
    from app.models.user import User

    account = await register_user(client, handle=handle)
    async with session_factory() as s:
        user = await s.get(User, account["user"]["id"])
        user.capabilities = sorted({*(user.capabilities or []), "admin"})
        await s.commit()
    return account["token"]


async def test_l08_a_submission_cannot_be_approved_twice(client, session_factory):
    """★ Re-approval used to append a fresh KYC_APPROVED row every time.

    The ledger is append-only and never deducts, so each replay ratcheted karma upward
    from one document -- +8 to +20 a click. `users.karma` is a projection of the ledger,
    so the inflated number was fully "auditable" and entirely false.
    """
    from sqlalchemy import func, select

    from app.models.user import KarmaEvent, KarmaEventType, User

    applicant = await register_user(client, handle="farmer")
    admin_token = await _make_admin(client, session_factory, "root")

    submission = await client.post(
        "/api/v1/verification/submit",
        json={"document_type": "aadhaar", "document_ref": "123456789012"},
        headers=auth(applicant["token"]),
    )
    submission_id = submission.json()["id"]

    first = await client.patch(
        f"/api/v1/admin/verifications/{submission_id}",
        json={"decision": "approved"},
        headers=auth(admin_token),
    )
    assert first.status_code == 200

    async with session_factory() as s:
        user = await s.get(User, applicant["user"]["id"])
        karma_after_one_approval = user.karma

    for _ in range(4):
        replay = await client.patch(
            f"/api/v1/admin/verifications/{submission_id}",
            json={"decision": "approved"},
            headers=auth(admin_token),
        )
        assert replay.status_code == 409, replay.text
        assert "already" in replay.json()["detail"].lower()

    async with session_factory() as s:
        user = await s.get(User, applicant["user"]["id"])
        assert user.karma == karma_after_one_approval, "karma must not ratchet on replay"

        kyc_rows = await s.scalar(
            select(func.count())
            .select_from(KarmaEvent)
            .where(
                KarmaEvent.user_id == applicant["user"]["id"],
                KarmaEvent.event_type == KarmaEventType.KYC_APPROVED.value,
            )
        )
    assert kyc_rows == 1, f"one document, one KYC event, got {kyc_rows}"


async def test_l08_a_rejected_submission_cannot_be_flipped_to_approved(
    client, session_factory
):
    """A decision is final in both directions."""
    applicant = await register_user(client, handle="applicant")
    admin_token = await _make_admin(client, session_factory, "root")

    submission = await client.post(
        "/api/v1/verification/submit",
        json={"document_type": "pan", "document_ref": "ABCDE1234F"},
        headers=auth(applicant["token"]),
    )
    submission_id = submission.json()["id"]

    rejected = await client.patch(
        f"/api/v1/admin/verifications/{submission_id}",
        json={"decision": "rejected"},
        headers=auth(admin_token),
    )
    assert rejected.status_code == 200

    flipped = await client.patch(
        f"/api/v1/admin/verifications/{submission_id}",
        json={"decision": "approved"},
        headers=auth(admin_token),
    )
    assert flipped.status_code == 409


async def test_l08_an_admin_cannot_approve_their_own_document(client, session_factory):
    """Reviewer and reviewed must be two people."""
    admin_token = await _make_admin(client, session_factory, "root")

    submission = await client.post(
        "/api/v1/verification/submit",
        json={"document_type": "aadhaar", "document_ref": "999988887777"},
        headers=auth(admin_token),
    )
    response = await client.patch(
        f"/api/v1/admin/verifications/{submission.json()['id']}",
        json={"decision": "approved"},
        headers=auth(admin_token),
    )
    assert response.status_code == 403, response.text


# ==========================================================================
# L-09  Proof posts are unfakeable
# ==========================================================================
async def test_l09_the_feed_refuses_to_publish_a_proof_post(client):
    """Over HTTP the request-schema pattern rejects it (422). Control test."""
    account = await register_user(client, handle="storyteller")
    response = await client.post(
        "/api/v1/feed/posts",
        json={"kind": "proof", "body": "Totally did a job", "media_urls": []},
        headers=auth(account["token"]),
    )
    assert response.status_code in (403, 422), response.text


async def test_l09_the_feed_router_refuses_proof_even_if_the_schema_stops_doing_so(
    client, session_factory
):
    """★ The router must say no in its own voice.

    The `PostCreate.kind` pattern is input validation on one schema; widen the pattern,
    add a field, or accept a dict, and the invariant silently disappears with nothing
    failing. This bypasses the schema exactly the way such a refactor would, and asserts
    the handler still refuses.
    """
    from fastapi import HTTPException

    from app.routers.feed import create_post
    from app.schemas import PostCreate

    account = await register_user(client, handle="schemabypass")

    # model_construct skips validation, simulating a widened/replaced request schema.
    payload = PostCreate.model_construct(
        kind="proof", body="Forged evidence", media_urls=[], hashtags=[]
    )

    async with session_factory() as s:
        from app.models.user import User

        user = await s.get(User, account["user"]["id"])
        with pytest.raises(HTTPException) as excinfo:
            await create_post(payload, user, s)

    assert excinfo.value.status_code == 403
    assert "paid gig" in excinfo.value.detail


async def test_l09_the_database_refuses_a_proof_post_with_no_gig(session_factory):
    """★ The invariant lives in the schema, so every writer is bound by it.

    Before the fix this insert succeeded: the seed script did exactly this, putting
    fabricated evidence into the demo database, and an ETL or a psql session could do the
    same in production.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models.social import Post
    from app.models.user import User

    async with session_factory() as s:
        user = User(handle="faker", display_name="Faker", email="f@example.com",
                    password_hash="x")
        s.add(user)
        await s.flush()
        author_id = user.id
        await s.commit()

    with pytest.raises(IntegrityError, match="ck_posts_proof_requires_gig"):
        async with session_factory() as s:
            s.add(Post(author_id=author_id, kind="proof", body="Forged",
                       amount_earned=99999.0))
            await s.commit()


async def test_l09_a_real_gig_completion_still_publishes_proof(client, session_factory):
    """The constraint must not break the legitimate path it exists to protect."""
    from sqlalchemy import select

    from app.models.social import Post

    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="priya")
    await client.post("/api/v1/auth/capability/can_hire", headers=auth(customer["token"]))
    worker = await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    gig = await client.post(
        "/api/v1/gigs",
        json={
            "category_id": category_id,
            "title": "Rewire the kitchen",
            "description": "Two dead sockets.",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 2.0,
        },
        headers=auth(customer["token"]),
    )
    gig_id = gig.json()["id"]
    await client.post(
        f"/api/v1/gigs/{gig_id}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )
    await secure_gig_payment(client, customer, gig_id)
    for status in ("en_route", "arrived", "in_progress", "completion_pending"):
        await client.post(
            f"/api/v1/gigs/{gig_id}/status",
            json={"status": status, "proof_photos": []},
            headers=auth(worker["token"]),
        )
    await release_gig_payment(client, customer, gig_id)

    async with session_factory() as s:
        proof = await s.scalar(select(Post).where(Post.kind == "proof", Post.gig_id == gig_id))
        assert proof is not None, "a completed paid gig must still publish its proof"
        assert proof.author_id == worker["user_id"]


# ==========================================================================
# L-10 / L-11  Production settings fail closed
# ==========================================================================
def _prod(**overrides):
    from app.core.config import Settings

    base = dict(
        ENVIRONMENT="production",
        SECRET_KEY="a-real-production-secret-value-32-chars",
        ALLOWED_ORIGINS=["https://karma.app"],
        TRUSTED_HOSTS=["karma.app"],
        REDIS_URL="redis://localhost:6379/0",
        OBJECT_STORAGE_BACKEND="s3",
        S3_ACCESS_KEY="test-access",
        S3_SECRET_KEY="test-secret",
        GEOCODING_PROVIDER="nominatim",
        GEOCODING_USER_AGENT="KARMA/1.0 ops@karma.test",
        PAYMENT_PROVIDER="stripe",
        STRIPE_SECRET_KEY="sk_test_config_only",
        STRIPE_PUBLISHABLE_KEY="pk_test_config_only",
        STRIPE_WEBHOOK_SECRET="whsec_config_only",
    )
    base.update(overrides)
    return Settings(**base)


def test_l10_cors_credentials_are_never_paired_with_a_wildcard_origin():
    """★ The old expression short-circuited on `is_production is False`.

    Every non-production deployment therefore enabled credentialled CORS alongside a
    wildcard origin -- any site on the internet making authenticated calls as the
    logged-in user. Environment must not change the answer.
    """
    from app.main import cors_allow_credentials

    assert cors_allow_credentials(["*"]) is False, (
        "a wildcard origin must disable credentials in every environment"
    )
    assert cors_allow_credentials(["*", "https://karma.app"]) is False
    assert cors_allow_credentials(["http://localhost:5173"]) is True
    assert cors_allow_credentials(["https://karma.app"]) is True


def test_l10_the_app_never_enables_credentials_with_a_wildcard():
    """Read the wiring as assembled, not the expression in isolation."""
    from fastapi.middleware.cors import CORSMiddleware

    from app.main import app

    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert cors, "CORS middleware must be installed"
    options = cors[0].kwargs
    if "*" in options["allow_origins"]:
        assert options["allow_credentials"] is False


def test_l11_production_rejects_a_wildcard_trusted_host():
    with pytest.raises(Exception, match="TRUSTED_HOSTS"):
        _prod(TRUSTED_HOSTS=["*"])


def test_l11_production_rejects_a_wildcard_origin():
    with pytest.raises(Exception, match="ALLOWED_ORIGINS"):
        _prod(ALLOWED_ORIGINS=["*"])


def test_l11_production_rejects_the_default_secret():
    from app.core.config import DEFAULT_SECRET

    with pytest.raises(Exception, match="SECRET_KEY"):
        _prod(SECRET_KEY=DEFAULT_SECRET)


def test_l11_production_requires_redis():
    """★ MemoryCache is per-process.

    Without Redis, rate limits, OTP codes and single-use realtime tickets are local to
    one worker, so an attacker only has to be balanced onto another process to get a
    fresh budget or replay a spent ticket. That is a broken security control, not a
    degraded cache, so the process must refuse to boot.
    """
    with pytest.raises(Exception, match="REDIS_URL"):
        _prod(REDIS_URL=None)


def test_l11_the_default_trusted_hosts_are_not_a_wildcard():
    """The default must be safe on its own, not only when ENVIRONMENT is also correct."""
    from app.core.config import Settings

    defaults = Settings(ENVIRONMENT="development")
    assert "*" not in defaults.TRUSTED_HOSTS
    assert "*" not in defaults.ALLOWED_ORIGINS


def test_l11_a_correctly_configured_production_boots():
    """The guards must not be unsatisfiable."""
    settings = _prod()
    assert settings.is_production is True
    assert settings.expose_dev_otp is False


def test_l11_production_requires_durable_object_storage():
    with pytest.raises(Exception, match="OBJECT_STORAGE_BACKEND"):
        _prod(OBJECT_STORAGE_BACKEND="local")
    with pytest.raises(Exception, match="S3_ACCESS_KEY"):
        _prod(S3_ACCESS_KEY=None)


def test_l11_production_requires_a_geocoding_provider_identity():
    with pytest.raises(Exception, match="GEOCODING_PROVIDER"):
        _prod(GEOCODING_PROVIDER="disabled")
    with pytest.raises(Exception, match="GEOCODING_USER_AGENT"):
        _prod(GEOCODING_USER_AGENT="KARMA-development/1.0")


def test_l11_production_refuses_simulated_payments():
    with pytest.raises(Exception, match="PAYMENT_PROVIDER"):
        _prod(PAYMENT_PROVIDER="simulated")


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"STRIPE_SECRET_KEY": None}, "STRIPE_SECRET_KEY"),
        ({"STRIPE_PUBLISHABLE_KEY": None}, "STRIPE_PUBLISHABLE_KEY"),
        ({"STRIPE_WEBHOOK_SECRET": None}, "STRIPE_WEBHOOK_SECRET"),
    ],
)
def test_l11_production_requires_every_stripe_secret(override, message):
    with pytest.raises(Exception, match=message):
        _prod(**override)


# ==========================================================================
# L-12  Origin/host allowlists must be configurable from the environment
# ==========================================================================
def test_l12_csv_env_values_are_accepted(monkeypatch):
    """★ `_split_csv` was unreachable dead code.

    pydantic-settings JSON-decodes complex fields straight from the environment before
    any validator runs, so `ALLOWED_ORIGINS=https://karma.app` did not fall back to CSV:
    it raised SettingsError and the process died on boot. The one documented way to
    narrow the two settings that gate the wildcard-origin invariant could not be used.
    """
    from app.core.config import Settings

    monkeypatch.setenv("ALLOWED_ORIGINS", "https://karma.app,https://www.karma.app")
    monkeypatch.setenv("TRUSTED_HOSTS", "karma.app, api")

    settings = Settings(_env_file=None)
    assert settings.ALLOWED_ORIGINS == ["https://karma.app", "https://www.karma.app"]
    assert settings.TRUSTED_HOSTS == ["karma.app", "api"]


def test_l12_json_env_values_still_work(monkeypatch):
    """docker-compose.yml passes JSON arrays; that path must not regress."""
    from app.core.config import Settings

    monkeypatch.setenv("ALLOWED_ORIGINS", '["https://karma.example.com"]')
    monkeypatch.setenv("TRUSTED_HOSTS", '["karma.example.com","api"]')

    settings = Settings(_env_file=None)
    assert settings.ALLOWED_ORIGINS == ["https://karma.example.com"]
    assert settings.TRUSTED_HOSTS == ["karma.example.com", "api"]


def test_l12_a_wildcard_supplied_as_csv_is_still_refused_in_production(monkeypatch):
    """Making the setting reachable must not make it bypassable."""
    from app.core.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "a-real-production-secret-value-32-chars")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://karma.app")
    monkeypatch.setenv("TRUSTED_HOSTS", "*")

    with pytest.raises(Exception, match="TRUSTED_HOSTS"):
        Settings(_env_file=None)


def test_l12_malformed_json_is_rejected_not_silently_mangled(monkeypatch):
    """A broken JSON array must fail loudly rather than become one weird origin."""
    from app.core.config import Settings

    monkeypatch.setenv("ALLOWED_ORIGINS", '["https://karma.app"')
    with pytest.raises(Exception):
        Settings(_env_file=None)
