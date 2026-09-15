"""Regression tests for the fixes in the `arena/01a09e5b-karma` review round.

Each test names the behaviour that was wrong before, so the pair (test, fix) reads as one
argument. Prose lives in the routers; these are the receipts.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from tests.conftest import (
    PASSWORD,
    add_category,
    auth,
    make_worker,
    register_user,
    release_gig_payment,
    secure_gig_payment,
)


def bearer(account: dict) -> dict:
    return auth(account["token"])


# ---------------------------------------------------------------------------
# 1. `assigned` is the outcome of hiring, not an editable status.
# ---------------------------------------------------------------------------
async def test_assigned_is_not_a_status_edit(client, session_factory):
    category = await add_category(session_factory)
    customer = await register_user(client, handle="nadia")
    await client.post("/api/v1/auth/capability/can_hire", headers=bearer(customer))

    gig = (
        await client.post(
            "/api/v1/gigs",
            json={"category_id": category, "title": "Fix the fan", "lat": 22.72, "lng": 75.85},
            headers=bearer(customer),
        )
    ).json()

    refused = await client.post(
        f"/api/v1/gigs/{gig['id']}/status",
        json={"status": "assigned"},
        headers=bearer(customer),
    )
    assert refused.status_code == 409
    assert "assign" in refused.json()["detail"]

    # The point of the refusal: the gig is still hireable, not stranded.
    status = await client.get(f"/api/v1/gigs/{gig['id']}", headers=bearer(customer))
    assert status.json()["status"] == "searching"

    worker = await make_worker(client, session_factory, handle="imran", category_id=category)
    assigned = await client.post(
        f"/api/v1/gigs/{gig['id']}/assign?worker_id={worker['user_id']}",
        headers=bearer(customer),
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["worker_id"] == worker["user_id"]


# ---------------------------------------------------------------------------
# 2. The night window is judged in marketplace time, not in whatever offset the
#    client happened to serialise.
# ---------------------------------------------------------------------------
def test_night_window_is_the_same_instant_whatever_the_offset():
    from app.services.fare import estimate_fare, is_night_time

    india = timezone(timedelta(hours=5, minutes=30))
    same_instant_ist = datetime(2026, 9, 14, 23, 30, tzinfo=india)
    same_instant_utc = datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc)
    assert same_instant_ist == same_instant_utc

    assert is_night_time(same_instant_ist) is True
    assert is_night_time(same_instant_utc) is True, "18:00Z is 23:30 in Kolkata"

    def fare(at):
        return estimate_fare(
            base_fare=200,
            per_km_rate=18,
            per_hour_rate=350,
            distance_km=0,
            estimated_hours=2,
            platform_fee_rate=0.15,
            starts_at=at,
        )

    assert fare(same_instant_ist)["total"] == fare(same_instant_utc)["total"]

    # 17:00Z is 22:30 IST -- night, even though the digits say otherwise.
    assert fare(datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc))["night_multiplier"] == 1.15
    # A naive value is already marketplace-local, so the stored/hand-written case is unchanged.
    assert is_night_time(datetime(2026, 8, 27, 22, 0)) is True
    assert is_night_time(datetime(2026, 8, 27, 6, 0)) is False


def test_bad_timezone_fails_at_boot_not_at_the_first_estimate():
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="FARE_TIMEZONE"):
        Settings(FARE_TIMEZONE="Mars/Olympus_Mons")


# ---------------------------------------------------------------------------
# 3. The public ledger publishes the arithmetic, not other people's sentences.
# ---------------------------------------------------------------------------
async def test_public_ledger_hides_prose_keeps_the_numbers(client, session_factory, db):
    from app.models.user import KarmaDomain, KarmaEvent

    victim = await register_user(client, handle="rashid")
    async with session_factory() as s:
        s.add(
            KarmaEvent(
                user_id=victim["user"]["id"],
                event_type="gig_completed",
                domain=KarmaDomain.WORK.value,
                delta=3,
                reason="Completed 'Repair the bathroom leak at Flat 12B, Rose Villa' on time",
                ref_type="gig",
                ref_id=1,
            )
        )
        await s.commit()

    public = await client.get(f"/api/v1/karma/ledger/{victim['user']['id']}")
    assert public.status_code == 200  # public by design
    by_type = {e["event_type"]: e for e in public.json()["events"]}
    event = by_type["gig_completed"]
    assert event["reason"] == "Gig completed"
    assert "Flat 12B" not in public.text
    assert "Rose Villa" not in public.text
    # The number itself stays auditable.
    assert event["delta"] == 3
    assert event["event_type"] == "gig_completed"

    # The owner still reads their own reason verbatim -- they are the party who can contest it.
    own = await client.get("/api/v1/karma/ledger", headers=bearer(victim))
    own_reasons = {e["event_type"]: e["reason"] for e in own.json()["events"]}
    assert "Flat 12B" in own_reasons["gig_completed"]
    assert own_reasons["phone_verified"] == "Phone number verified"


# ---------------------------------------------------------------------------
# 4. Moderation moves the author's counter, not the moderator's.
# ---------------------------------------------------------------------------
async def test_admin_delete_decrements_the_author(client, session_factory):
    from app.models.user import User

    author = await register_user(client, handle="author")
    admin = await register_user(client, handle="moderator")
    async with session_factory() as s:
        account = await s.get(User, admin["user"]["id"])
        account.capabilities = sorted({*account.capabilities, "admin"})
        account.posts_count = 7
        await s.commit()

    created = await client.post(
        "/api/v1/feed/posts", json={"body": "a bad day"}, headers=bearer(author)
    )
    assert created.status_code == 201
    assert (await client.get("/api/v1/auth/me", headers=bearer(author))).json()["posts_count"] == 1

    deleted = await client.delete(
        f"/api/v1/feed/posts/{created.json()['id']}", headers=bearer(admin)
    )
    assert deleted.status_code == 200

    async with session_factory() as s:
        assert (await s.get(User, author["user"]["id"])).posts_count == 0
        assert (await s.get(User, admin["user"]["id"])).posts_count == 7


async def test_concurrent_posts_compose_in_the_counter(client, session_factory):
    """The counter is written in SQL, so two posts by one account cannot lose an increment."""
    from app.models.user import User

    account = await register_user(client, handle="busy")
    ids = set()
    for _ in range(3):
        response = await client.post(
            "/api/v1/feed/posts", json={"body": "one of three"}, headers=bearer(account)
        )
        ids.add(response.json()["id"])
    async with session_factory() as s:
        assert (await s.get(User, account["user"]["id"])).posts_count == 3
    assert len(ids) == 3


# ---------------------------------------------------------------------------
# 5. One identity, one KYC credit, one submission in flight.
# ---------------------------------------------------------------------------
async def test_only_one_verification_may_be_in_flight(client, session_factory):
    account = await register_user(client, handle="moleskine")
    first = await client.post(
        "/api/v1/verification/submit",
        json={"document_type": "aadhaar", "document_ref": "123456789012"},
        headers=bearer(account),
    )
    assert first.status_code == 201
    again = await client.post(
        "/api/v1/verification/submit",
        json={"document_type": "aadhaar", "document_ref": "123456789012"},
        headers=bearer(account),
    )
    assert again.status_code == 409


async def test_duplicated_approvals_pay_the_ledger_once(client, session_factory):
    from app.models.user import KarmaEvent, User

    admin = await register_user(client, handle="approver")
    async with session_factory() as s:
        account = await s.get(User, admin["user"]["id"])
        account.capabilities = sorted({*account.capabilities, "admin"})
        await s.commit()

    applicant = await register_user(client, handle="twice")
    for _ in range(2):
        submitted = await client.post(
            "/api/v1/verification/submit",
            json={"document_type": "aadhaar", "document_ref": "999988887777"},
            headers=bearer(applicant),
        )
        assert submitted.status_code == 201, submitted.text
        decided = await client.patch(
            f"/api/v1/admin/verifications/{submitted.json()['id']}",
            json={"decision": "approved"},
            headers=bearer(admin),
        )
        assert decided.status_code == 200, decided.text

    async with session_factory() as s:
        credits = (
            await s.execute(
                select(KarmaEvent.delta).where(
                    KarmaEvent.user_id == applicant["user"]["id"],
                    KarmaEvent.event_type == "kyc_approved",
                )
            )
        ).scalars().all()
        assert list(credits) == [20], "the second approval must not pay again"


async def test_a_lesser_document_never_demotes_a_verified_worker(client, session_factory):
    from app.models.user import User

    admin = await register_user(client, handle="registrar")
    async with session_factory() as s:
        account = await s.get(User, admin["user"]["id"])
        account.capabilities = sorted({*account.capabilities, "admin"})
        await s.commit()

    worker = await register_user(client, handle="goldline")
    async def approve(document: str) -> None:
        submitted = await client.post(
            "/api/v1/verification/submit",
            json={"document_type": document, "document_ref": f"ref-{document}"},
            headers=bearer(worker),
        )
        assert submitted.status_code == 201, submitted.text
        decided = await client.patch(
            f"/api/v1/admin/verifications/{submitted.json()['id']}",
            json={"decision": "approved"},
            headers=bearer(admin),
        )
        assert decided.status_code == 200, decided.text

    await approve("aadhaar")
    async with session_factory() as s:
        assert (await s.get(User, worker["user"]["id"])).verification_tier == "gold"

    # A routine second decision on weaker paper must not re-price the worker downwards:
    # `verification_tier` feeds the skill-tier multiplier in `gigs.assign_worker`.
    await approve("govt_id")
    async with session_factory() as s:
        assert (await s.get(User, worker["user"]["id"])).verification_tier == "gold"


# ---------------------------------------------------------------------------
# 6. Login is the only auth flow that used to be unthrottled.
# ---------------------------------------------------------------------------
async def test_password_guessing_is_bounded_per_address(client, session_factory):
    del session_factory
    await register_user(client, handle="targeted")
    codes = [
        (
            await client.post(
                "/api/v1/auth/login",
                json={"identifier": "targeted", "password": "WrongPass!00"},
            )
        ).status_code
        for _ in range(settings.LOGIN_LIMIT)
    ]
    assert set(codes) == {401}, codes
    over_the_line = await client.post(
        "/api/v1/auth/login", json={"identifier": "targeted", "password": "WrongPass!00"}
    )
    assert over_the_line.status_code == 429


async def test_the_per_account_budget_counts_failures_only(client, session_factory, monkeypatch):
    """A siege of one account is throttled without letting it lock the owner out."""
    del session_factory
    monkeypatch.setattr(settings, "LOGIN_LIMIT", 1000)
    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LIMIT", 3)
    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_WINDOW", 300)

    account = await register_user(client, handle="sleepless")
    for _ in range(3):
        wrong = await client.post(
            "/api/v1/auth/login", json={"identifier": "sleepless", "password": "Nope!12345"}
        )
        assert wrong.status_code == 401
    blocked = await client.post(
        "/api/v1/auth/login", json={"identifier": "sleepless", "password": "Nope!12345"}
    )
    assert blocked.status_code == 429

    # The real user still gets in: the account budget punished guesses, not logins.
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"identifier": "sleepless", "password": "StrongPass!234"},
        )
    ).status_code == 200
    del account


# ---------------------------------------------------------------------------
# 7. Party-only reads for gig reviews and post comments.
# ---------------------------------------------------------------------------
async def test_reviews_and_comments_are_not_world_readable(client, session_factory):
    category = await add_category(session_factory)
    worker = await make_worker(client, session_factory, handle="quiet", category_id=category)
    customer = await register_user(client, handle="private")
    await client.post("/api/v1/auth/capability/can_hire", headers=bearer(customer))
    gig = (
        await client.post(
            "/api/v1/gigs",
            json={"category_id": category, "title": "Wall patching", "lat": 22.72, "lng": 75.85},
            headers=bearer(customer),
        )
    ).json()

    post = (
        await client.post(
            "/api/v1/feed/posts",
            json={"body": "the flat on 9 Palm Lane"},
            headers=bearer(worker),
        )
    ).json()

    assert (await client.get(f"/api/v1/feed/posts/{post['id']}/comments")).status_code == 401
    assert (await client.get(f"/api/v1/gigs/{gig['id']}/reviews")).status_code == 401
    # A signed-in stranger is still not a party to the gig.
    stranger = await register_user(client, handle="curious")
    assert (
        await client.get(f"/api/v1/gigs/{gig['id']}/reviews", headers=bearer(stranger))
    ).status_code == 403
    # The customer, who is, gets their own reviews.
    assert (
        await client.get(f"/api/v1/gigs/{gig['id']}/reviews", headers=bearer(customer))
    ).status_code == 200


# ---------------------------------------------------------------------------
# 8. The in-process cache forgets idle keys instead of hoarding one per visitor.
# ---------------------------------------------------------------------------
async def test_memory_cache_does_not_grow_with_every_address_it_has_ever_seen():
    from app.core.ports import MemoryCache

    cache = MemoryCache()
    for i in range(5000):
        await cache.incr_window(f"karma:rl:login:10.0.0.{i}", 60)
    assert len(cache._windows) == 5000

    cache._sweep(time.monotonic() + 3601)
    assert cache._windows == {}

    await cache.incr_window("karma:rl:login:1.2.3.4", 60)
    cache._sweep(time.monotonic())
    assert list(cache._windows) == ["karma:rl:login:1.2.3.4"], "live traffic must survive"

    # A read must not mint a window entry the way `defaultdict` did.
    await cache.get("never-seen")
    assert "never-seen" not in cache._windows


async def test_expired_values_are_swept_too():
    from app.core.ports import MemoryCache

    cache = MemoryCache()
    await cache.set("ticket", "42", ttl=1)
    assert await cache.get("ticket") == "42"
    cache._values["ticket"] = ("42", time.monotonic() - 1)
    cache._sweep(time.monotonic())
    assert "ticket" not in cache._values


# ---------------------------------------------------------------------------
# 9. The simulator must not accept webhooks signed with a secret published in the repo.
# ---------------------------------------------------------------------------
async def test_unconfigured_simulator_has_no_published_webhook_secret(monkeypatch):
    from app.services.payments import PaymentProviderError, get_payment_gateway

    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "simulated")
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", None)
    get_payment_gateway.cache_clear()
    try:
        gateway = get_payment_gateway()
        assert gateway._webhook_secret != "whsec_karma_test"
        # Two processes must not derive the same secret from the source tree.
        get_payment_gateway.cache_clear()
        assert get_payment_gateway()._webhook_secret != gateway._webhook_secret
        with pytest.raises(PaymentProviderError):
            gateway.construct_webhook_event(b"{}", "t=1,v1=deadbeef")
    finally:
        get_payment_gateway.cache_clear()


async def test_configured_secret_still_works_locally(client, session_factory):
    """The escape hatch for local tooling stays: set the secret, sign the event."""
    import hashlib
    import hmac
    import json

    del session_factory
    from app.services.payments import SimulatedPaymentGateway

    secret = "whsec_local_tooling"
    gateway = SimulatedPaymentGateway(secret)
    payload = json.dumps(
        {"id": "evt_local", "type": "ping", "created": int(time.time()), "data": {"object": {}}}
    ).encode()
    stamp = str(int(time.time()))
    signature = f"t={stamp},v1=" + hmac.new(
        secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    event = gateway.construct_webhook_event(payload, signature)
    assert event["id"] == "evt_local"


# ---------------------------------------------------------------------------
# 10. A logout that the server cannot see is a UI gesture. Tokens used to be checked
#     for signature and expiry only: `jti` was minted and consulted by nobody, and
#     "signing out" cleared client storage while the pair stayed valid for its owner.
# ---------------------------------------------------------------------------
async def _session(client, handle: str) -> dict:
    """A signed-in account that keeps its refresh token, which `register_user` throws away."""
    account = await register_user(client, handle=handle)
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": f"{handle}@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {**account, "refresh_token": login.json()["refresh_token"]}


async def test_logout_revokes_both_halves_of_the_pair(client, session_factory):
    del session_factory
    phone = await _session(client, "pixel")
    laptop = await _session(client, "thinkpad")

    signed_out = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": phone["refresh_token"]},
        headers=bearer(phone),
    )
    assert signed_out.status_code == 200, signed_out.text

    denied = await client.get("/api/v1/auth/me", headers=bearer(phone))
    assert denied.status_code == 401
    assert denied.json()["detail"] == "Token revoked"

    # The refresh token has to die with it: otherwise the session quietly returns an hour later
    # on a device its owner just signed out of.
    revived = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": phone["refresh_token"]}
    )
    assert revived.status_code == 401

    # And only this device's session ends. A sign-out that logged the whole account out of every
    # device would be a worse tool, not a safer one.
    kept = await client.get("/api/v1/auth/me", headers=bearer(laptop))
    assert kept.status_code == 200


async def test_logout_revokes_what_it_was_handed_and_no_more(client, session_factory):
    """The endpoint's scope is its request: the header token always, the body token if given."""
    del session_factory
    account = await _session(client, "sparse")

    bare = await client.post("/api/v1/auth/logout", headers=bearer(account))
    assert bare.status_code == 200, bare.text
    assert (await client.get("/api/v1/auth/me", headers=bearer(account))).status_code == 401
    # A refresh token the server never saw stays valid -- which is exactly why the clients send
    # it, and why "sign out everywhere" is a separate call rather than a checkbox on this one.
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": account["refresh_token"]})
    ).status_code == 200


async def test_sign_out_everywhere_ends_the_account_not_the_neighbour(client, session_factory):
    del session_factory
    handle = "drifter"
    await register_user(client, handle=handle)
    neighbour = await _session(client, "bystander")

    async def sign_in() -> dict:
        # Two logins, two devices, one account -- which is the only shape this endpoint is
        # supposed to be able to reach.
        response = await client.post(
            "/api/v1/auth/login",
            json={"identifier": f"{handle}@example.com", "password": PASSWORD},
        )
        assert response.status_code == 200, response.text
        return response.json()

    phone, laptop = await sign_in(), await sign_in()

    ended = await client.post("/api/v1/auth/logout-all", headers=auth(phone["access_token"]))
    assert ended.status_code == 200, ended.text

    for who, tokens in (("phone", phone), ("laptop", laptop)):
        stale = await client.get("/api/v1/auth/me", headers=auth(tokens["access_token"]))
        assert stale.status_code == 401, who
        assert stale.json()["detail"] == "Session ended; sign in again", who
        refused = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refused.status_code == 401, who

    # The epoch is a column on one user, so one account's panic button cannot darken another's
    # session -- a bug here would look like a global outage and read as a security win.
    kept = await client.get("/api/v1/auth/me", headers=bearer(neighbour))
    assert kept.status_code == 200

    # It ends sessions, it does not punish the account: a fresh login works, sitting at the new
    # epoch. The caller's own tokens died with the rest, deliberately -- see the handler.
    again = await sign_in()
    assert (await client.get("/api/v1/auth/me", headers=auth(again["access_token"]))).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=auth(phone["access_token"]))).status_code == 401


async def test_a_revocation_marker_expires_with_the_token_it_revokes():
    """The denylist must not grow with every logout the service has ever recorded."""
    from app.core import revocation
    from app.core.ports import MemoryCache
    from app.core.security import TokenClaims, create_access_token, decode_claims

    claims = decode_claims(create_access_token(7), "access")
    await revocation.revoke(claims)
    assert await revocation.is_revoked(claims) is True

    cache = revocation._cache
    key = revocation.REVOKED_KEY.format(jti=claims.jti)
    if isinstance(cache, MemoryCache):  # the Redis path has its own integration test
        _, deadline = cache._values[key]
        # Not `None`: an entry that never expires is a key that outlives the very token it was
        # written for, and outlives the argument for revoking it.
        assert deadline is not None
        assert deadline - time.monotonic() <= settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60 + 1

    # An already-expired token gets no marker at all -- nothing is left to protect, and a
    # zero-length TTL is what a cache stores forever as.
    gone = TokenClaims(
        subject=7,
        token_type="access",
        jti="j-gone",
        version=0,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    await revocation.revoke(gone)
    assert await revocation.is_revoked(gone) is False
    if isinstance(cache, MemoryCache):
        assert revocation.REVOKED_KEY.format(jti="j-gone") not in cache._values


async def test_a_token_minted_before_the_epoch_claim_existed_still_works():
    """The migration must not sign anybody out, and must still be able to."""
    from jose import jwt

    from app.core.revocation import session_is_current
    from app.core.security import TOKEN_AUDIENCE, TOKEN_ISSUER, decode_claims

    legacy = jwt.encode(
        {
            "sub": "42",
            "type": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
        },
        settings.SECRET_KEY.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )
    claims = decode_claims(legacy, "access")
    assert claims.jti is None  # nothing to name in a denylist
    assert claims.version == 0  # and the claim defaults to a fresh account's epoch
    assert await session_is_current(claims, 0) is True
    # So the epoch is what still governs a token this old: one bump ends it.
    assert await session_is_current(claims, 1) is False


# ---------------------------------------------------------------------------
# 11. An allegation that falls away has to give the karma back. Filing a dispute (-15)
#     or an SOS (-25) bites immediately, and until this round a dismissal left the
#     number broken: an unfounded accusation cost a worker their standing permanently.
# ---------------------------------------------------------------------------
async def _hired_gig(client, session_factory, *, customer_handle: str, worker_handle: str) -> tuple:
    """A gig with a real worker on it, ready to be disputed.

    The dispute and SOS penalties are recorded against the *other* party, so a gig with no
    worker assigned (`against is None`) records nothing -- which is how the existing admin
    fixtures came to look like coverage of this while touching none of it.
    """
    category = await add_category(session_factory)
    customer = await register_user(client, handle=customer_handle)
    await client.post("/api/v1/auth/capability/can_hire", headers=bearer(customer))
    gig = (
        await client.post(
            "/api/v1/gigs",
            json={
                "category_id": category,
                "title": "Regrind the circuit board",
                "lat": 22.7196,
                "lng": 75.8577,
            },
            headers=bearer(customer),
        )
    ).json()
    worker = await make_worker(client, session_factory, handle=worker_handle, category_id=category)
    assigned = await client.post(
        f"/api/v1/gigs/{gig['id']}/assign?worker_id={worker['user_id']}",
        headers=bearer(customer),
    )
    assert assigned.status_code == 200, assigned.text
    return customer, worker, gig["id"]


async def _ledger_rows(session_factory, user_id: int) -> list[tuple[str, int]]:
    from app.models.user import KarmaEvent

    async with session_factory() as s:
        rows = (
            await s.execute(
                select(KarmaEvent.event_type, KarmaEvent.delta).where(
                    KarmaEvent.user_id == user_id
                )
            )
        ).all()
    return [(event_type, delta) for event_type, delta in rows]


async def _admin_token(client, session_factory, handle: str = "judge") -> dict:
    account = await register_user(client, handle=handle)
    from app.models.user import User

    async with session_factory() as s:
        user = await s.get(User, account["user"]["id"])
        user.capabilities = sorted({*(user.capabilities or []), "admin"})
        await s.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": f"{handle}@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {**account, "token": login.json()["access_token"]}


async def test_a_dismissed_dispute_gives_the_karma_back(client, session_factory):
    from app.models.user import User

    async def standing(user_id: int) -> tuple[int, int]:
        async with session_factory() as s:
            account = await s.get(User, user_id)
            return account.karma, account.karma_work

    customer, worker, gig_id = await _hired_gig(
        client, session_factory, customer_handle="accuser", worker_handle="framed"
    )
    admin = await _admin_token(client, session_factory)
    before = await standing(worker["user_id"])

    filed = await client.post(
        f"/api/v1/gigs/{gig_id}/dispute",
        json={"reason": "He never showed up and took the deposit."},
        headers=bearer(customer),
    )
    assert filed.status_code == 201, filed.text
    dispute_id = (await client.get("/api/v1/admin/disputes", headers=bearer(admin))).json()[0]["id"]

    assert ("dispute_filed", -15) in await _ledger_rows(session_factory, worker["user_id"])
    accused = await standing(worker["user_id"])
    assert accused < before, "an allegation has to bite before anyone can investigate it"

    dismissed = await client.patch(
        f"/api/v1/admin/disputes/{dispute_id}", json={"status": "dismissed"}, headers=bearer(admin)
    )
    assert dismissed.status_code == 200, dismissed.text
    assert "karma restored" in dismissed.json()["detail"]

    # The number lands back exactly where the accusation found it. Both halves are checked:
    # `karma_work` is where the penalty and its reversal cancel out, and `karma` is the 0.6/0.4
    # blend of the two domains that every ranking actually reads -- an exoneration that restored
    # the domain but not the blend would be invisible to the matcher.
    assert await standing(worker["user_id"]) == before

    rows = await _ledger_rows(session_factory, worker["user_id"])
    assert rows.count(("case_dismissed", 15)) == 1, rows
    # History is never edited: the -15 is still on the ledger, answered by a +15, so anyone
    # auditing the account can see both halves of what happened to them.
    assert ("dispute_filed", -15) in rows

    # A console that lost the response retries the same dismissal. `dismissed` is terminal, so the
    # route answers 200 with the same status, and that retry must not credit anybody again.
    retry = await client.patch(
        f"/api/v1/admin/disputes/{dispute_id}", json={"status": "dismissed"}, headers=bearer(admin)
    )
    assert retry.status_code == 200, retry.text
    assert "karma restored" not in retry.json()["detail"]
    assert (await _ledger_rows(session_factory, worker["user_id"])).count(("case_dismissed", 15)) == 1
    assert await standing(worker["user_id"]) == before


async def test_a_settled_dispute_is_not_an_innocence(client, session_factory):
    """`resolved` means the concern was real and has been settled between the parties.

    Paying the karma back for that would make a dispute free to file: worst case it costs the
    accused nothing and buys time, best case the filer's enemy loses standing while they wait.
    Only a dismissal -- the accusation falling away -- gives the number back.
    """
    from app.models.user import User

    customer, worker, gig_id = await _hired_gig(
        client, session_factory, customer_handle="accuser2", worker_handle="framed2"
    )
    admin = await _admin_token(client, session_factory, handle="arbiter2")
    async with session_factory() as s:
        before = (await s.get(User, worker["user_id"])).karma

    await client.post(
        f"/api/v1/gigs/{gig_id}/dispute",
        json={"reason": "The work was shoddy but he did turn up."},
        headers=bearer(customer),
    )
    dispute_id = (await client.get("/api/v1/admin/disputes", headers=bearer(admin))).json()[0]["id"]

    settled = await client.patch(
        f"/api/v1/admin/disputes/{dispute_id}", json={"status": "resolved"}, headers=bearer(admin)
    )
    assert settled.status_code == 200, settled.text
    assert "karma restored" not in settled.json()["detail"]

    async with session_factory() as s:
        assert (await s.get(User, worker["user_id"])).karma == before - 9  # 0.6 x 15, blended
    assert await _ledger_rows(session_factory, worker["user_id"]) == [
        row for row in await _ledger_rows(session_factory, worker["user_id"])
        if row[0] != "case_dismissed"
    ]


async def test_a_dismissed_emergency_signal_gives_the_karma_back(client, session_factory):
    from app.models.user import User

    customer, worker, gig_id = await _hired_gig(
        client, session_factory, customer_handle="noisy", worker_handle="watched"
    )
    admin = await _admin_token(client, session_factory, handle="referee")

    async def standing(user_id: int) -> tuple[int, int]:
        async with session_factory() as s:
            account = await s.get(User, user_id)
            return account.karma, account.karma_work

    accused = customer["user"]["id"]
    before = await standing(accused)

    raised = await client.post(
        "/api/v1/safety/emergency",
        json={"gig_id": gig_id, "lat": 22.7196, "lng": 75.8577, "note": "Customer looked drunk"},
        headers=bearer(worker),
    )
    assert raised.status_code == 201, raised.text
    assert ("sos_raised", -25) in await _ledger_rows(session_factory, accused)
    assert (await standing(accused)) < before

    # `open` may not jump to `dismissed`; triage first, as the console does.
    incident_id = raised.json()["incident_id"]
    await client.patch(
        f"/api/v1/admin/safety/incidents/{incident_id}",
        json={"status": "in_review"},
        headers=bearer(admin),
    )
    dismissed = await client.patch(
        f"/api/v1/admin/safety/incidents/{incident_id}",
        json={"status": "dismissed"},
        headers=bearer(admin),
    )
    assert dismissed.status_code == 200, dismissed.text
    assert "karma restored" in dismissed.json()["detail"]

    assert await standing(accused) == before
    assert (await _ledger_rows(session_factory, accused)).count(("case_dismissed", 25)) == 1


async def test_an_exoneration_is_public_labelled_not_private_prose(client, session_factory):
    """The reversal lands in the *public* ledger, so its wording is a product decision too."""
    customer, worker, gig_id = await _hired_gig(
        client, session_factory, customer_handle="gossip", worker_handle="quiet"
    )
    admin = await _admin_token(client, session_factory, handle="arbiter")
    await client.post(
        f"/api/v1/gigs/{gig_id}/dispute",
        json={"reason": "He quoted ₹4,000 then demanded more at the door."},
        headers=bearer(customer),
    )
    dispute_id = (await client.get("/api/v1/admin/disputes", headers=bearer(admin))).json()[0]["id"]
    await client.patch(
        f"/api/v1/admin/disputes/{dispute_id}", json={"status": "dismissed"}, headers=bearer(admin)
    )

    public = await client.get(f"/api/v1/karma/ledger/{worker['user_id']}")
    assert public.status_code == 200
    by_type = {e["event_type"]: e for e in public.json()["events"]}
    assert by_type["case_dismissed"]["reason"] == "Case dismissed"
    assert by_type["case_dismissed"]["delta"] == 15
    assert "4,000" not in public.text  # the accusation behind the exoneration stays private
    own = await client.get("/api/v1/karma/ledger", headers=bearer(worker))
    assert any(
        e["event_type"] == "case_dismissed" and "no wrongdoing" in e["reason"]
        for e in own.json()["events"]
    )


# ---------------------------------------------------------------------------
# 12. The feed pages from a cursor. It had no pagination at all, so a client could only
#     ever show the newest N posts; anything behind them was unreachable.
# ---------------------------------------------------------------------------
async def test_the_feed_pages_by_cursor_without_losing_or_repeating(client, session_factory):
    del session_factory
    author = await register_user(client, handle="chronicler")
    ids = []
    for n in range(5):
        created = await client.post(
            "/api/v1/feed/posts",
            json={"kind": "pulse", "body": f"Pulse {n}"},
            headers=bearer(author),
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])

    headers = bearer(author)
    first = (await client.get("/api/v1/feed/posts?limit=2", headers=headers)).json()
    assert [p["id"] for p in first] == [ids[4], ids[3]]

    second = (
        await client.get(f"/api/v1/feed/posts?limit=2&before_id={first[-1]['id']}", headers=headers)
    ).json()
    assert [p["id"] for p in second] == [ids[2], ids[1]]

    third = (
        await client.get(f"/api/v1/feed/posts?limit=2&before_id={second[-1]['id']}", headers=headers)
    ).json()
    assert [p["id"] for p in third] == [ids[0]]  # a short page is the end of the feed

    seen = [p["id"] for page in (first, second, third) for p in page]
    assert len(seen) == len(set(seen)) == 5

    # A post added at the head while page 2 was in flight shifts nothing: the cursor is an id,
    # not a row count, which is the whole reason for using one.
    extra = await client.post(
        "/api/v1/feed/posts", json={"kind": "pulse", "body": "Late entry"}, headers=headers
    )
    late_id = extra.json()["id"]
    again = (
        await client.get(f"/api/v1/feed/posts?limit=2&before_id={first[-1]['id']}", headers=headers)
    ).json()
    assert [p["id"] for p in again] == [ids[2], ids[1]]
    head = (await client.get("/api/v1/feed/posts?limit=2", headers=headers)).json()
    assert [p["id"] for p in head] == [late_id, ids[4]]


# ---------------------------------------------------------------------------
# 13. A dispute is not a free weapon. Filing one costs the other party 15 karma on the spot and
#     freezes their payout until an admin decides it, so "any number of open cases per gig" let a
#     complainant grind a stranger down with restatements: five 201s took a verified worker from
#     work 100 to 33 in a live run, while an exoneration (``KarmaLedger.reverse``) pays back one
#     penalty per dismissal. The guard is one *open* case per party, which is also the shape the
#     payment freeze already uses -- the same list, now the same constant.
# ---------------------------------------------------------------------------
async def _hired_gig_for(client, customer: dict, worker: dict, category_id: int) -> int:
    """The one-gig version of `_hired_gig`, for a test that supplies its own worker."""
    gig = (
        await client.post(
            "/api/v1/gigs",
            json={
                "category_id": category_id,
                "title": "Replace the motor",
                "lat": 22.72,
                "lng": 75.85,
            },
            headers=bearer(customer),
        )
    ).json()
    assigned = await client.post(
        f"/api/v1/gigs/{gig['id']}/assign?worker_id={worker['user_id']}",
        headers=bearer(customer),
    )
    assert assigned.status_code == 200, assigned.text
    return gig["id"]


async def _completed_gig(client, customer: dict, worker: dict, category_id: int, gig_id: int) -> None:
    """Drive a hired gig through payment to a released completion, which is what a review needs."""
    await secure_gig_payment(client, customer, gig_id)
    for status in ("en_route", "arrived", "in_progress", "completion_pending"):
        step = await client.post(
            f"/api/v1/gigs/{gig_id}/status", json={"status": status}, headers=bearer(worker)
        )
        assert step.status_code == 200, step.text
    await release_gig_payment(client, customer, gig_id)


async def test_one_open_dispute_per_party_per_gig(client, session_factory):
    customer, worker, gig_id = await _hired_gig(
        client, session_factory, customer_handle="spurned", worker_handle="wary"
    )

    before = (await client.get(f"/api/v1/karma/ledger/{worker['user_id']}")).json()
    first = await client.post(
        f"/api/v1/gigs/{gig_id}/dispute",
        json={"reason": "No work was done."},
        headers=bearer(customer),
    )
    assert first.status_code == 201, first.text
    after_one = (await client.get(f"/api/v1/karma/ledger/{worker['user_id']}")).json()
    assert after_one["work"] < before["work"], "the guard must not defang a legitimate dispute"
    assert after_one["total_events"] == before["total_events"] + 1

    refused = []
    for n in range(4):
        again = await client.post(
            f"/api/v1/gigs/{gig_id}/dispute",
            json={"reason": f"The same grievance, restated ({n})."},
            headers=bearer(customer),
        )
        assert again.status_code == 409, again.text
        assert "already have a case open" in again.json()["detail"]
        refused.append(again.status_code)
    assert len(refused) == 4

    charged = (await client.get(f"/api/v1/karma/ledger/{worker['user_id']}")).json()
    assert charged["work"] == after_one["work"], "refused filings must not charge karma again"
    assert charged["total_events"] == after_one["total_events"], "or append a row"

    # The other party's grievance is a separate case and stays available.
    theirs = await client.post(
        f"/api/v1/gigs/{gig_id}/dispute",
        json={"reason": "The customer is lying about the parts."},
        headers=bearer(worker),
    )
    assert theirs.status_code == 201, theirs.text

    # And once this one is decided, the complainant may file again: a problem that came back is a
    # real complaint, which is why the rule is "one open", never "one ever".
    admin = await _admin_token(client, session_factory, handle="marshal")
    queue = (await client.get("/api/v1/admin/disputes", headers=bearer(admin))).json()
    mine = [d for d in queue if d["gig_id"] == gig_id and d["raised_by"] == customer["user"]["id"]]
    assert len(mine) == 1
    decided = await client.patch(
        f"/api/v1/admin/disputes/{mine[0]['id']}",
        json={"status": "dismissed"},
        headers=bearer(admin),
    )
    assert decided.status_code == 200, decided.text

    renewed = await client.post(
        f"/api/v1/gigs/{gig_id}/dispute",
        json={"reason": "The motor failed again the next week."},
        headers=bearer(customer),
    )
    assert renewed.status_code == 201, renewed.text


# ---------------------------------------------------------------------------
# 14. A logout the server refuses to read is worse than no logout button, because the client
#     treats either the same. The endpoint used to take `CurrentUser`, so a device whose access
#     token had already expired -- an hour after its last request, which is the normal case for a
#     phone -- got a 401 back and left its refresh token valid for the remaining thirteen days.
#     It now authenticates from whichever credential it is handed, since a refresh token is
#     self-authenticating for /auth/refresh and must be for revoking it too.
# ---------------------------------------------------------------------------
def _expired_access_token(user_id: int) -> str:
    """Signed by the real key, trusted by nobody: what a tab holds an hour later."""
    from datetime import timedelta

    from app.core.security import TOKEN_AUDIENCE, TOKEN_ISSUER
    from jose import jwt

    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "ver": 0,
            "jti": "dusty-tab",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(minutes=1),
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
        },
        settings.SECRET_KEY.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )


async def test_sign_out_works_with_an_expired_access_token(client, session_factory):
    del session_factory
    account = await _session(client, "dusty")
    stale = _expired_access_token(account["user"]["id"])

    # The token itself is worthless, as it must be.
    denied = await client.get("/api/v1/auth/me", headers=auth(stale))
    assert denied.status_code == 401

    signed_out = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": account["refresh_token"]},
        headers={"Authorization": f"Bearer {stale}"},
    )
    assert signed_out.status_code == 200, signed_out.text
    assert "already invalid" in signed_out.json()["detail"], "say what could not be revoked"

    killed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": account["refresh_token"]}
    )
    assert killed.status_code == 401, "the session outlived the sign-out"


async def test_logout_needs_one_usable_credential_and_says_what_it_killed(client, session_factory):
    del session_factory
    account = await _session(client, "frugal")

    nothing = await client.post("/api/v1/auth/logout")
    assert nothing.status_code == 401
    assert "Nothing to revoke" in nothing.json()["detail"]

    # A body with a token that cannot be read and no header to fall back on is a 401 too, rather
    # than a 200 that claims a session ended when none did.
    garbage = await client.post("/api/v1/auth/logout", json={"refresh_token": "not-a-token"})
    assert garbage.status_code == 401

    # Handing over only the access token revokes only the access token -- and the response now
    # says so, because the caller cannot otherwise tell "signed out" from "signed out for an hour".
    bare = await client.post("/api/v1/auth/logout", headers=bearer(account))
    assert bare.status_code == 200, bare.text
    assert "no refresh token was presented" in bare.json()["detail"]
    assert (await client.get("/api/v1/auth/me", headers=bearer(account))).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": account["refresh_token"]})
    ).status_code == 200


async def test_logout_still_reports_a_refresh_token_it_could_not_read(client, session_factory):
    """The 400 half survives: a *presented* token the server cannot parse is the caller's bug."""
    del session_factory
    account = await _session(client, "fussy")
    refused = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "not-a-token"},
        headers=bearer(account),
    )
    assert refused.status_code == 400, refused.text
    assert "was revoked; the refresh token was not" in refused.json()["detail"]
    # The access token died in that request, which is why it is a 400 and not a 401.
    assert (await client.get("/api/v1/auth/me", headers=bearer(account))).status_code == 401


# ---------------------------------------------------------------------------
# 15. The like button toggles. Two taps in the same millisecond both saw no existing like, and the
#     loser's INSERT then surfaced as an unhandled IntegrityError out of the counter UPDATE's
#     autoflush -- six parallel taps on a live server produced [200, 200, 200, 500, 500, 200].
# ---------------------------------------------------------------------------
async def test_a_double_tapped_like_is_a_toggle_not_a_crash(client, session_factory):
    author = await register_user(client, handle="liked")
    headers = bearer(author)
    post_id = (
        await client.post(
            "/api/v1/feed/posts", json={"kind": "pulse", "body": "Six taps"}, headers=headers
        )
    ).json()["id"]

    taps = await asyncio.gather(
        *[client.post(f"/api/v1/feed/posts/{post_id}/like", headers=headers) for _ in range(6)]
    )
    codes = sorted(r.status_code for r in taps)
    assert max(codes) < 500, codes

    shown = (await client.get("/api/v1/feed/posts?limit=50", headers=headers)).json()
    mine = next(p for p in shown if p["id"] == post_id)
    assert mine["likes_count"] in (0, 1), f"six taps cannot mean more than one like: {mine['likes_count']}"

    # The counter is only worth trusting if it agrees with the table it summarises -- asserted one
    # tap at a time here, because the in-memory SQLite this suite runs on shares a single
    # connection between the concurrent sessions, so a "concurrent" check of rows against a
    # counter would be measuring the harness rather than the database.
    from app.models.social import Like

    async def _rows() -> int:
        async with session_factory() as s:
            return len((await s.execute(select(Like.id).where(Like.post_id == post_id))).all())

    # A clean pair of taps on a post nobody raced, so the bookkeeping is checked against a known
    # start rather than against whatever the six taps above left behind.
    other = (
        await client.post(
            "/api/v1/feed/posts", json={"kind": "pulse", "body": "One tap"}, headers=headers
        )
    ).json()["id"]

    liked = await client.post(f"/api/v1/feed/posts/{other}/like", headers=headers)
    assert liked.status_code == 200 and liked.json()["likes_count"] == 1, liked.text
    async with session_factory() as s:
        assert len((await s.execute(select(Like.id).where(Like.post_id == other))).all()) == 1

    unliked = await client.post(f"/api/v1/feed/posts/{other}/like", headers=headers)
    assert unliked.status_code == 200 and unliked.json()["likes_count"] == 0, unliked.text
    async with session_factory() as s:
        assert (await s.execute(select(Like.id).where(Like.post_id == other))).all() == []


# ---------------------------------------------------------------------------
# 16. A rolling rating is per *worker*, but the review path locks the *gig*. Two customers reviewing
#     two different gigs of the same worker therefore read (rating, rating_count) together and the
#     slower write discarded the faster one -- the wallet's old bug, and the wallet's fix.
# ---------------------------------------------------------------------------
async def test_two_reviews_of_two_gigs_both_count(client, session_factory):
    category_id = await add_category(session_factory)
    worker = await make_worker(
        client, session_factory, handle="twice", category_id=category_id, rating=4.0, total_jobs=0
    )
    gigs = []
    for handle in ("annabell", "batool"):
        customer = await register_user(client, handle=handle)
        await client.post("/api/v1/auth/capability/can_hire", headers=bearer(customer))
        gig_id = await _hired_gig_for(client, customer, worker, category_id)
        await _completed_gig(client, customer, worker, category_id, gig_id)
        gigs.append((customer, gig_id))

    reviews = await asyncio.gather(
        *[
            client.post(
                f"/api/v1/gigs/{gig_id}/review",
                json={"rating": rating, "punctuality": 4, "quality": 4, "communication": 4},
                headers=bearer(customer),
            )
            for (customer, gig_id), rating in zip(gigs, (5, 3))
        ]
    )
    assert [r.status_code for r in reviews] == [201, 201], [r.text for r in reviews]

    profile = (await client.get("/api/v1/workers/me/profile", headers=bearer(worker))).json()
    assert profile["rating_count"] == 2, "one review was written and then overwritten"
    # Both orders of (5, 3) over an empty count land on 4.0, so the arithmetic is checked without
    # depending on which request got there first.
    assert abs(profile["rating"] - 4.0) < 0.005, profile["rating"]


# ---------------------------------------------------------------------------
# 17. The karma ledger pages like the feed does. The owner's route had a page size and a `truncated`
#     flag but no cursor, so anybody with more events than one page could not reach their own oldest
#     rows -- while a stranger reading the same table could be told they existed.
# ---------------------------------------------------------------------------
async def test_the_ledger_has_a_cursor_too(client, session_factory):
    from app.models.user import KarmaEventType
    from app.services.karma import KarmaLedger

    account = await register_user(client, handle="scrollback")
    uid = account["user"]["id"]
    async with session_factory() as s:
        ledger = KarmaLedger(s)
        for n in range(4):
            await ledger.record(
                uid,
                KarmaEventType.GIG_COMPLETED,
                reason=f"Backfill {n}",
                ref_type="gig",
                ref_id=9000 + n,
            )
        await s.commit()

    headers = bearer(account)
    first = (await client.get("/api/v1/karma/ledger?limit=2", headers=headers)).json()
    second = (
        await client.get(
            f"/api/v1/karma/ledger?limit=2&before_id={first['events'][-1]['id']}", headers=headers
        )
    ).json()
    ids = [e["id"] for e in first["events"]] + [e["id"] for e in second["events"]]
    assert len(ids) == 4 and len(set(ids)) == 4, ids
    assert first["total_events"] == second["total_events"] == 5, "one phone-verified event plus four"

    # A short page is the end of the ledger -- the feed's contract, deliberately the same one.
    tail = (
        await client.get(
            f"/api/v1/karma/ledger?limit=2&before_id={second['events'][-1]['id']}", headers=headers
        )
    ).json()
    assert len(tail["events"]) == 1, [e["id"] for e in tail["events"]]
    assert tail["events"][0]["id"] not in ids
    assert tail["truncated"] is False, "the last page is not telling anybody there is more"

    # Refused, not ignored: a cursor of 0 would mean "everything older than nothing" and quietly
    # return the whole ledger, which is the opposite of a page.
    bad = await client.get("/api/v1/karma/ledger?before_id=0", headers=headers)
    assert bad.status_code == 422
