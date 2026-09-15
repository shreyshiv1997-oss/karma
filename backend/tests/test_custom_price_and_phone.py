"""Poster-set pricing and post-registration phone verification.

Two product freedoms that share one file because both end at the same place -- an
account that can post a gig it priced itself:

  * ``custom_price`` lets the person posting the gig name what the work is worth. The
    platform fee is computed on top of that number and nothing else is; no multiplier
    may touch a price a person set themselves, and assignment must never re-price it.
  * ``POST /auth/phone/verify`` is the other door to ``can_hire``: an account that
    registered with an email can prove a phone number by OTP and become hirable.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.conftest import (
    add_category,
    auth,
    make_worker,
    register_user,
    release_gig_payment,
    secure_gig_payment,
    upload_test_image,
)

pytestmark = pytest.mark.asyncio

GIG_BODY = {
    "title": "Fix the garden tap",
    "description": "Tap washer replacement, all parts on site",
    "lat": 22.7196,
    "lng": 75.8577,
    "address_label": "Vijay Nagar, Indore",
}


async def _otp(client, phone: str) -> str:
    sent = await client.post("/api/v1/auth/otp/send", json={"phone": phone})
    assert sent.status_code == 200, sent.text
    code = sent.json()["dev_otp"]
    assert code, "test environment must expose dev_otp"
    return code


async def _grant_hire(client, token: str):
    return await client.post("/api/v1/auth/capability/can_hire", headers=auth(token))


async def _post_custom_gig(client, token: str, category_id: int, price: float):
    return await client.post(
        "/api/v1/gigs",
        json={**GIG_BODY, "category_id": category_id, "custom_price": price},
        headers=auth(token),
    )


# --------------------------------------------------------------------------
# custom pricing
# --------------------------------------------------------------------------
async def test_custom_price_is_the_posters_number_plus_our_fee(client, session_factory):
    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="selfpriced")
    await _grant_hire(client, customer["token"])

    created = await _post_custom_gig(client, customer["token"], category_id, 1000.0)
    assert created.status_code == 201, created.text
    gig = created.json()

    assert gig["fare_breakdown"]["pricing_mode"] == "custom"
    assert gig["fare_breakdown"]["subtotal"] == 1000.0
    assert gig["fare_breakdown"]["platform_fee"] == 150.0, "15% on top, never folded in"
    assert gig["fare_breakdown"]["total"] == 1150.0
    assert gig["total"] == 1150.0
    # A poster-set price has no estimate left in it.
    assert gig["fare_breakdown"]["skill_multiplier"] == 1.0
    assert gig["fare_breakdown"]["urgency_multiplier"] == 1.0
    assert gig["fare_breakdown"]["night_multiplier"] == 1.0


async def test_assignment_never_reprices_a_poster_set_price(client, session_factory):
    """The worker's tier and distance re-price *estimates*, not promises."""
    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="promised")
    await _grant_hire(client, customer["token"])
    # Gold tier and far away: both would raise an estimated fare at assignment.
    worker = await make_worker(
        client,
        session_factory,
        handle="goldfar",
        category_id=category_id,
        lat=23.2599,  # Bhopal-side, well outside the default estimate
        lng=77.4126,
        tier="gold",
    )

    created = await _post_custom_gig(client, customer["token"], category_id, 800.0)
    assert created.status_code == 201, created.text
    gig_id = created.json()["id"]
    total_at_post = created.json()["total"]

    assigned = await client.post(
        f"/api/v1/gigs/{gig_id}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["total"] == total_at_post == 920.0
    assert assigned.json()["fare_breakdown"]["pricing_mode"] == "custom", (
        "a poster-set price must survive assignment unchanged"
    )


async def test_estimated_gigs_still_recompute_at_assignment(client, session_factory):
    """The guard is scoped: an ordinary gig keeps the behaviour it always had."""
    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="estimated")
    await _grant_hire(client, customer["token"])
    worker = await make_worker(
        client, session_factory, handle="silvernear", category_id=category_id, tier="silver"
    )

    created = await client.post(
        "/api/v1/gigs",
        json={**GIG_BODY, "category_id": category_id},
        headers=auth(customer["token"]),
    )
    assert created.status_code == 201, created.text
    gig_id = created.json()["id"]
    assert "pricing_mode" not in created.json()["fare_breakdown"]

    assigned = await client.post(
        f"/api/v1/gigs/{gig_id}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )
    assert assigned.status_code == 200, assigned.text
    # Silver's 1.08 skill multiplier is applied at assignment -- proof the recompute
    # still runs for everything that is not poster-priced.
    assert assigned.json()["fare_breakdown"]["skill_multiplier"] == 1.08


async def test_custom_price_must_be_a_sane_amount(client, session_factory):
    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="priceless")
    await _grant_hire(client, customer["token"])

    for bad in (0, -50, 2_000_000):
        refused = await _post_custom_gig(client, customer["token"], category_id, bad)
        assert refused.status_code == 422, f"custom_price={bad} must be refused"


async def test_estimate_honors_a_custom_price(client, session_factory):
    """The live estimate the UI shows must be the arithmetic the gig will store."""
    category_id = await add_category(session_factory)

    estimate = await client.post(
        "/api/v1/gigs/estimate",
        json={
            "category_id": category_id,
            "lat": 22.7196,
            "lng": 75.8577,
            "custom_price": 500,
            "urgency": "urgent",
            "estimated_hours": 8,
        },
    )
    assert estimate.status_code == 200, estimate.text
    breakdown = estimate.json()
    # Neither the urgent flag nor the hour count may touch a poster's number.
    assert breakdown["pricing_mode"] == "custom"
    assert breakdown["subtotal"] == 500.0
    assert breakdown["platform_fee"] == 75.0
    assert breakdown["total"] == 575.0

    missing = await client.post(
        "/api/v1/gigs/estimate",
        json={"category_id": 999999, "lat": 22.7, "lng": 75.8, "custom_price": 500},
    )
    assert missing.status_code == 404, "category existence is checked before pricing"


async def test_a_custom_priced_gig_completes_and_pays_out(client, session_factory):
    """A poster-set total flows through escrow to the wallet like any other."""
    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="payer")
    await _grant_hire(client, customer["token"])
    worker = await make_worker(client, session_factory, handle="payee", category_id=category_id)

    created = await _post_custom_gig(client, customer["token"], category_id, 1000.0)
    assert created.status_code == 201, created.text
    gig_id = created.json()["id"]

    assigned = await client.post(
        f"/api/v1/gigs/{gig_id}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )
    assert assigned.status_code == 200, assigned.text
    payment = await secure_gig_payment(client, customer, gig_id)
    assert payment["amount"] == 1150.0, "escrow secures the poster's total, fee included"

    for status in ("en_route", "arrived", "in_progress"):
        step = await client.post(
            f"/api/v1/gigs/{gig_id}/status",
            json={"status": status},
            headers=auth(worker["token"]),
        )
        assert step.status_code == 200, step.text

    before = await upload_test_image(client, worker, purpose="proof_before")
    after = await upload_test_image(client, worker, purpose="proof_after")
    submitted = await client.post(
        f"/api/v1/gigs/{gig_id}/status",
        json={"status": "completion_pending", "proof_photos": [before, after]},
        headers=auth(worker["token"]),
    )
    assert submitted.status_code == 200, submitted.text

    released = await release_gig_payment(client, customer, gig_id)
    assert released["status"] == "paid"

    summary = await client.get("/api/v1/gigs/stats/summary", headers=auth(worker["token"]))
    # split_payout(1150.0, 0.15): the worker's side of the poster's total.
    assert summary.json()["lifetime_earned"] == 977.5


async def test_summary_counts_only_the_callers_gigs(client, session_factory):
    """A user with no work of their own sees zeroes, not marketplace totals."""
    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="summaryowner")
    await _grant_hire(client, customer["token"])
    worker = await make_worker(client, session_factory, handle="summaryworker", category_id=category_id)

    # Drive one gig all the way through escrow to completion.
    created = await client.post(
        "/api/v1/gigs",
        json={**GIG_BODY, "category_id": category_id},
        headers=auth(customer["token"]),
    )
    assert created.status_code == 201, created.text
    gig_id = created.json()["id"]
    assigned = await client.post(
        f"/api/v1/gigs/{gig_id}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )
    assert assigned.status_code == 200, assigned.text
    await secure_gig_payment(client, customer, gig_id)
    for status in ("en_route", "arrived", "in_progress", "completion_pending"):
        step = await client.post(
            f"/api/v1/gigs/{gig_id}/status",
            json={"status": status},
            headers=auth(worker["token"]),
        )
        assert step.status_code == 200, step.text
    await release_gig_payment(client, customer, gig_id)

    # The bystander: registered, verified, zero gigs of their own.
    bystander = await register_user(client, handle="bystander")
    stats = await client.get("/api/v1/gigs/stats/summary", headers=auth(bystander["token"]))
    assert stats.json()["gigs_total"] == 0, "an empty 'No gigs yet' list cannot sit under totals"
    assert stats.json()["gigs_completed"] == 0

    # Both parties to the gig count it once — no more, no less.
    for account in (customer, worker):
        own = await client.get("/api/v1/gigs/stats/summary", headers=auth(account["token"]))
        assert own.json()["gigs_total"] == 1
        assert own.json()["gigs_completed"] == 1


# --------------------------------------------------------------------------
# phone verification after registration
# --------------------------------------------------------------------------
async def test_phone_verify_links_a_number_and_unlocks_hiring(client, session_factory, db):
    """An email-door account proves a phone and becomes able to post gigs."""
    customer = await register_user(client, handle="emailonly", verify_phone=False)

    blocked = await _grant_hire(client, customer["token"])
    assert blocked.status_code == 403, "no verified contact yet"

    phone = "+919812345001"
    code = await _otp(client, phone)
    verified = await client.post(
        "/api/v1/auth/phone/verify",
        json={"phone": phone, "otp": code},
        headers=auth(customer["token"]),
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["phone"] == phone

    granted = await _grant_hire(client, customer["token"])
    assert granted.status_code == 200, "a proven number is a verified contact"

    from app.models.user import KarmaEvent, KarmaEventType

    events = (
        (await db.execute(select(KarmaEvent).where(KarmaEvent.user_id == customer["user"]["id"])))
        .scalars()
        .all()
    )
    phone_events = [e for e in events if e.event_type == KarmaEventType.PHONE_VERIFIED.value]
    assert len(phone_events) == 1
    assert phone_events[0].meta.get("phone") == phone, "the evidence names the number"


async def test_a_wrong_code_links_nothing(client, session_factory):
    customer = await register_user(client, handle="fatfinger", verify_phone=False)
    phone = "+919812345002"
    await _otp(client, phone)

    refused = await client.post(
        "/api/v1/auth/phone/verify",
        json={"phone": phone, "otp": "000000"},
        headers=auth(customer["token"]),
    )
    assert refused.status_code in (400, 429)
    me = await client.get("/api/v1/auth/me", headers=auth(customer["token"]))
    assert me.json()["phone"] is None

    blocked = await _grant_hire(client, customer["token"])
    assert blocked.status_code == 403


async def test_a_number_belonging_to_another_account_is_refused(client, session_factory):
    taken_owner = await register_user(client, handle="firstowner")  # phone-door account
    assert taken_owner["user"]["phone"]

    customer = await register_user(client, handle="secondowner", verify_phone=False)
    phone = taken_owner["user"]["phone"]
    code = await _otp(client, phone)  # possession of the SIM is not ownership of the row

    refused = await client.post(
        "/api/v1/auth/phone/verify",
        json={"phone": phone, "otp": code},
        headers=auth(customer["token"]),
    )
    assert refused.status_code == 409, refused.text


async def test_swapping_numbers_is_refused(client, session_factory):
    """One proven number per account via this endpoint; changes are a support review."""
    customer = await register_user(client, handle="wedsim", verify_phone=False)

    first = "+919812345003"
    code = await _otp(client, first)
    linked = await client.post(
        "/api/v1/auth/phone/verify",
        json={"phone": first, "otp": code},
        headers=auth(customer["token"]),
    )
    assert linked.status_code == 200, linked.text

    second = "+919812345004"
    code = await _otp(client, second)
    refused = await client.post(
        "/api/v1/auth/phone/verify",
        json={"phone": second, "otp": code},
        headers=auth(customer["token"]),
    )
    assert refused.status_code == 409, refused.text
    me = await client.get("/api/v1/auth/me", headers=auth(customer["token"]))
    assert me.json()["phone"] == first, "the proven number survives the refused swap"


async def test_relinking_the_same_number_pays_karma_once(client, session_factory, db):
    """A dropped-connection retry must not ratchet karma nor 409 on the same number."""
    customer = await register_user(client, handle="retryer", verify_phone=False)
    phone = "+919812345005"

    for _ in range(2):
        code = await _otp(client, phone)
        linked = await client.post(
            "/api/v1/auth/phone/verify",
            json={"phone": phone, "otp": code},
            headers=auth(customer["token"]),
        )
        assert linked.status_code == 200, linked.text

    from app.models.user import KarmaEvent, KarmaEventType

    count = await db.scalar(
        select(func.count())
        .select_from(KarmaEvent)
        .where(
            KarmaEvent.user_id == customer["user"]["id"],
            KarmaEvent.event_type == KarmaEventType.PHONE_VERIFIED.value,
        )
    )
    assert count == 1, "the +5 is a one-time credit, not a per-click reward"


async def test_linking_a_phone_requires_a_signed_in_account(client, session_factory):
    phone = "+919812345006"
    code = await _otp(client, phone)
    anonymous = await client.post(
        "/api/v1/auth/phone/verify", json={"phone": phone, "otp": code}
    )
    assert anonymous.status_code == 401
