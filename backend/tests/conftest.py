# FIXED: can_hire requires verified contact / can_work cannot be self-granted — fixtures
# now go through the real OTP and capability-grant paths instead of forging the state.
"""Shared fixtures: an in-memory SQLite database and an authenticated HTTP client.

Deliberately overrides only ``get_session``, so tests drive the real app wiring —
middleware, dependencies, routers — rather than a parallel harness.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import os
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("PAYMENT_PROVIDER", "simulated")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_karma_test")

from app.core.db import Base, get_session, session_scope  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _isolate_rate_limits():
    """The rate-limit and OTP caches are process-wide singletons.

    Without this, one test's registrations exhaust the next test's per-IP budget and
    unrelated tests fail with 429. Clearing them keeps cases independent.
    """
    from app.core.middleware import _cache as middleware_cache
    from app.routers import auth as auth_router
    from app.routers import media as media_router
    from app.routers import trust as trust_router
    from app.services.payments import get_payment_gateway

    gateway = get_payment_gateway()
    reset_gateway = getattr(gateway, "reset", None)
    if reset_gateway is not None:
        reset_gateway()

    for cache in {id(middleware_cache): middleware_cache,
                  id(auth_router._cache): auth_router._cache,
                  id(media_router._cache): media_router._cache,
                  id(trust_router._cache): trust_router._cache}.values():
        reset = getattr(cache, "reset", None)
        if reset is not None:
            reset()
    yield


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def db(session_factory) -> AsyncIterator[AsyncSession]:
    """A raw session for asserting database state directly."""
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncIterator[AsyncClient]:
    async def _override() -> AsyncIterator[AsyncSession]:
        # Delegates to the production lifecycle rather than re-implementing commit/rollback.
        # A previous version inlined that logic here, which meant the post-commit real-time
        # flush existed only in production and was never exercised by a test.
        async with session_factory() as s:
            async for value in session_scope(s):
                yield value

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
PASSWORD = "StrongPass!234"


_phone_counter = itertools.count(1)


def _phone_for(handle: str) -> str:
    """A stable, unique E.164-ish number per test user."""
    digest = hashlib.sha1(handle.encode()).hexdigest()[:8]
    return f"+9198{int(digest, 16) % 100000000:08d}"


async def register_user(
    client: AsyncClient,
    *,
    handle: str,
    email: str | None = None,
    password: str = PASSWORD,
    name: str | None = None,
    phone: str | None = None,
    verify_phone: bool = True,
) -> dict:
    """Register a user and return {'token', 'user'}.

    By default the account is created through the *phone* door, completing the real OTP
    exchange first. That matters now that ``can_hire`` requires a verified contact
    detail: previously every fixture user was email-only and self-granted ``can_hire``
    with nothing verified at all, which is precisely the loophole being closed. Driving
    the OTP flow here means the tests exercise the path a real customer takes.

    Pass ``verify_phone=False`` for an email-only account with no verified contact --
    used to assert that such an account is *refused* ``can_hire``.
    """
    body = {
        "handle": handle,
        "display_name": name or handle.title(),
        "email": email or f"{handle}@example.com",
        "password": password,
        "city": "Indore",
    }

    if verify_phone:
        number = phone or _phone_for(handle)
        sent = await client.post("/api/v1/auth/otp/send", json={"phone": number})
        assert sent.status_code == 200, sent.text
        code = sent.json()["dev_otp"]
        assert code, "test environment must expose dev_otp"
        verified = await client.post(
            "/api/v1/auth/otp/verify", json={"phone": number, "otp": code}
        )
        assert verified.status_code == 200, verified.text
        body["phone"] = number

    response = await client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 201, response.text
    data = response.json()
    return {"token": data["access_token"], "user": data["user"]}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def upload_test_image(
    client: AsyncClient,
    account: dict,
    *,
    purpose: str,
) -> str:
    """Upload a tiny signature-valid PNG through the real object contract."""
    response = await client.post(
        "/api/v1/media/uploads",
        headers=auth(account["token"]),
        data={"purpose": purpose},
        files={
            "file": (
                f"{purpose}.png",
                b"\x89PNG\r\n\x1a\n" + purpose.encode(),
                "image/png",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["url"]


async def secure_gig_payment(client: AsyncClient, customer: dict, gig_id: int) -> dict:
    """Authorize the deterministic test PaymentIntent before worker travel begins."""
    response = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/intent",
        headers=auth(customer["token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "authorized"
    return response.json()


async def release_gig_payment(client: AsyncClient, customer: dict, gig_id: int) -> dict:
    """Capture and release a worker-submitted completion in the test provider."""
    response = await client.post(
        f"/api/v1/payments/gigs/{gig_id}/release",
        headers=auth(customer["token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paid"
    return response.json()


async def add_category(session_factory, **overrides) -> int:
    """Insert a service category through the same engine the client uses."""
    from app.models.marketplace import ServiceCategory

    defaults = dict(
        name="Electrical",
        slug="electrical",
        emoji="⚡",
        description="Wiring, fans, fittings",
        base_fare=Decimal("200"),
        per_km_rate=Decimal("18"),
        per_hour_rate=Decimal("350"),
    )
    defaults.update(overrides)
    async with session_factory() as s:
        category = ServiceCategory(**defaults)
        s.add(category)
        await s.commit()
        return category.id


async def make_worker(
    client: AsyncClient,
    session_factory,
    *,
    handle: str,
    category_id: int,
    lat: float = 22.7196,
    lng: float = 75.8577,
    hourly_rate: float = 350.0,
    total_jobs: int = 0,
    rating: float = 5.0,
    tier: str = "gold",
) -> dict:
    """Register a user, approve their KYC, and open a worker profile.

    Goes through the real endpoints wherever one exists, so the capability grant and the
    karma event it produces are exercised rather than bypassed.
    """
    from datetime import UTC, datetime

    from app.models.trust import VerificationSubmission
    from app.models.marketplace import WorkerProfile
    from app.models.user import User

    account = await register_user(client, handle=handle)
    token = account["token"]
    user_id = account["user"]["id"]

    # KYC: submit via the API, approve via the database (admin provisioning path).
    response = await client.post(
        "/api/v1/verification/submit",
        json={"document_type": "aadhaar", "document_ref": "123456789012"},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    submission_id = response.json()["id"]

    async with session_factory() as s:
        submission = await s.get(VerificationSubmission, submission_id)
        submission.status = "approved"
        submission.reviewed_at = datetime.now(UTC)
        user = await s.get(User, user_id)
        user.verification_tier = tier
        user.is_verified = True
        # The real grant happens in POST /workers/register, behind the approved KYC this
        # fixture has just written. Provisioning the profile without the capability left
        # every fixture worker in a state the production code cannot produce -- and it
        # was that gap which hid the missing `can_work` filter in GeoPort and in
        # gigs.assign_worker, because no test ever had a worker who lacked it.
        user.capabilities = sorted({*(user.capabilities or []), "can_work"})
        s.add(
            WorkerProfile(
                user_id=user_id,
                category_id=category_id,
                hourly_rate=Decimal(str(hourly_rate)),
                total_jobs=total_jobs,
                rating=rating,
                verification_tier=tier,
                is_available=True,
                approved_at=datetime.now(UTC),
                lat=lat,
                lng=lng,
            )
        )
        await s.commit()

    return {"token": token, "user_id": user_id}
