# FIXED: can_hire requires verified contact details — the journey now opts in through
# a verified phone rather than on an unverified account.
"""★ THE MERGE TEST.

One test walks the entire unified journey: hire -> match -> work -> prove -> earn -> review.

If the two source projects were merely co-located rather than merged, this test could not
exist -- there would be no social audience for a completed gig to publish into, and no
single ledger for a review to move.

It also asserts the two invariants that make it a *fusion* rather than an integration:
  * completing a gig publishes a proof post AND writes a karma event in one transaction;
  * a review moves BOTH the marketplace half and the blended number.
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


async def _post_proof_count(db, user_id: int) -> int:
    from app.models.social import Post

    return int(
        await db.scalar(
            select(func.count()).select_from(Post).where(
                Post.author_id == user_id, Post.kind == "proof"
            )
        )
        or 0
    )


async def _karma_events(db, user_id: int) -> list[tuple[str, str, int]]:
    from app.models.user import KarmaEvent

    rows = (
        await db.execute(
            select(KarmaEvent.event_type, KarmaEvent.domain, KarmaEvent.delta).where(
                KarmaEvent.user_id == user_id
            )
        )
    ).all()
    return [(t, d, delta) for t, d, delta in rows]


async def test_full_journey_hire_work_prove_earn_review(client, session_factory, db):
    category_id = await add_category(session_factory)

    # --- 1. A customer arrives. No role question is asked. -----------------
    customer = await register_user(client, handle="priya")
    # They registered through the phone door, so the OTP they completed has already
    # appended a PHONE_VERIFIED row: karma starts at 50 and this is the first thing above
    # it. The number is the sum of its history from the very first request.
    assert customer["user"]["karma"] == 55
    assert "can_hire" not in customer["user"]["capabilities"], "hiring must be opted into"
    assert customer["user"]["is_verified"] is False, (
        "verification is asserted by a KYC reviewer, never by registering"
    )

    # They cannot post a gig yet.
    blocked = await client.post(
        "/api/v1/gigs",
        json={
            "category_id": category_id,
            "title": "Fix ceiling fan",
            "lat": 22.7196,
            "lng": 75.8577,
        },
        headers=auth(customer["token"]),
    )
    assert blocked.status_code == 403

    # Opting in is self-service.
    granted = await client.post(
        "/api/v1/auth/capability/can_hire", headers=auth(customer["token"])
    )
    assert granted.status_code == 200
    assert "can_hire" in granted.json()["capabilities"]

    # --- 2. A worker exists, KYC-approved, nearby. ------------------------
    worker = await make_worker(
        client,
        session_factory,
        handle="ramesh",
        category_id=category_id,
        lat=22.7216,
        lng=75.8597,  # ~0.3 km away
        total_jobs=48,
        rating=4.9,
        tier="gold",
    )

    # --- 3. Price is estimated transparently. -----------------------------
    estimate = await client.post(
        "/api/v1/gigs/estimate",
        json={"category_id": category_id, "lat": 22.7196, "lng": 75.8577, "estimated_hours": 2},
    )
    assert estimate.status_code == 200
    breakdown = estimate.json()
    assert breakdown["base_fare"] == 200.0
    assert breakdown["time_fare"] == 700.0
    assert "platform_fee" in breakdown and "total" in breakdown

    # --- 4. The gig is posted. -------------------------------------------
    created = await client.post(
        "/api/v1/gigs",
        json={
            "category_id": category_id,
            "title": "Rewire 3-room flat",
            "description": "Old aluminium wiring, needs full replacement",
            "lat": 22.7196,
            "lng": 75.8577,
            "address_label": "Vijay Nagar, Indore",
            "estimated_hours": 4.0,
            "urgency": "urgent",
        },
        headers=auth(customer["token"]),
    )
    assert created.status_code == 201, created.text
    gig = created.json()
    gig_id = gig["id"]
    assert gig["status"] == "searching"
    assert gig["fare_breakdown"]["urgency_multiplier"] == 1.25, "urgent multiplier must be visible"

    # --- 5. Matching returns ranked, explained candidates. ----------------
    matches = await client.post(
        "/api/v1/matching/find", json={"gig_id": gig_id}, headers=auth(customer["token"])
    )
    assert matches.status_code == 200, matches.text
    candidates = matches.json()
    assert candidates, "expected at least one nearby available worker"
    top = candidates[0]
    assert top["user_id"] == worker["user_id"]
    assert top["reasons"], "every candidate must carry human-readable reasons"
    assert top["verification_tier"] == "gold"

    # --- 6. Assign, then drive the state machine. -------------------------
    assigned = await client.post(
        f"/api/v1/gigs/{gig_id}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "assigned"
    assert assigned.json()["payment_status"] == "requires_payment"
    await secure_gig_payment(client, customer, gig_id)

    # An illegal transition is refused.
    illegal = await client.post(
        f"/api/v1/gigs/{gig_id}/status",
        json={"status": "completed"},
        headers=auth(worker["token"]),
    )
    assert illegal.status_code == 409, "assigned -> completed must be rejected"

    # The customer may not drive worker transitions.
    wrong_actor = await client.post(
        f"/api/v1/gigs/{gig_id}/status",
        json={"status": "en_route"},
        headers=auth(customer["token"]),
    )
    assert wrong_actor.status_code == 403

    for status in ("en_route", "arrived", "in_progress"):
        step = await client.post(
            f"/api/v1/gigs/{gig_id}/status",
            json={"status": status},
            headers=auth(worker["token"]),
        )
        assert step.status_code == 200, step.text
        assert step.json()["status"] == status

    proofs_before = await _post_proof_count(db, worker["user_id"])
    assert proofs_before == 0

    # --- 7. ★ COMPLETION + ESCROW RELEASE — the fusion seam. ---------------
    before = await upload_test_image(client, worker, purpose="proof_before")
    after = await upload_test_image(client, worker, purpose="proof_after")
    submitted = await client.post(
        f"/api/v1/gigs/{gig_id}/status",
        json={
            "status": "completion_pending",
            "proof_photos": [before, after],
        },
        headers=auth(worker["token"]),
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "completion_pending"
    completed = await release_gig_payment(client, customer, gig_id)
    assert completed["released_at"] is not None

    # (a) a proof post now exists, published automatically
    proofs_after = await _post_proof_count(db, worker["user_id"])
    assert proofs_after == 1, "completing a gig must publish a proof post"

    # (b) it appears in the public feed, with its evidence attached
    feed = await client.get("/api/v1/feed/posts", headers=auth(customer["token"]))
    assert feed.status_code == 200
    proof_posts = [p for p in feed.json() if p["kind"] == "proof"]
    assert len(proof_posts) == 1
    proof = proof_posts[0]
    assert proof["gig_id"] == gig_id
    assert proof["before_url"] and proof["after_url"]
    assert proof["category_name"] == "Electrical"
    assert proof["author_handle"] == "ramesh"
    assert proof["author_karma"] is not None, "trust travels with the proof post"

    # (c) the ledger recorded BOTH a work event and a social event
    events = await _karma_events(db, worker["user_id"])
    types = {t for t, _, _ in events}
    assert "gig_completed" in types
    assert "proof_published" in types
    domains = {d for _, d, _ in events}
    assert "work" in domains and "social" in domains, "one event, both domains move"

    # (d) the wallet ledger split the money
    wallet = await client.get(f"/api/v1/gigs/stats/summary", headers=auth(worker["token"]))
    assert wallet.status_code == 200
    assert wallet.json()["lifetime_earned"] > 0

    # (e) marketplace stats advanced
    profile = await client.get("/api/v1/workers/me/profile", headers=auth(worker["token"]))
    assert profile.json()["total_jobs"] == 49

    # --- 8. ★ REVIEW — moves both halves. ---------------------------------
    karma_before = (await client.get("/api/v1/karma/ledger", headers=auth(worker["token"]))).json()

    reviewed = await client.post(
        f"/api/v1/gigs/{gig_id}/review",
        json={
            "rating": 5,
            "punctuality": 5,
            "quality": 5,
            "communication": 4,
            "comment": "On time, clean work, explained everything.",
        },
        headers=auth(customer["token"]),
    )
    assert reviewed.status_code == 201, reviewed.text

    karma_after = (await client.get("/api/v1/karma/ledger", headers=auth(worker["token"]))).json()
    assert karma_after["work"] > karma_before["work"], "review must move work karma"
    assert karma_after["blended"] > karma_before["blended"], "review must move blended karma"

    # Double-reviewing is refused.
    again = await client.post(
        f"/api/v1/gigs/{gig_id}/review",
        json={"rating": 5},
        headers=auth(customer["token"]),
    )
    assert again.status_code == 409

    # --- 9. The loop closes: the proof is visible on the hiring card. -----
    public = await client.get(f"/api/v1/workers/{worker['user_id']}")
    assert public.status_code == 200
    body = public.json()
    assert len(body["proofs"]) == 1, "the hiring card must show actual proof of work"
    assert body["karma_work"] == karma_after["work"]


async def test_proof_post_cannot_be_forged(client, session_factory):
    """★ A proof post without a paid gig must be impossible to create."""
    from app.models.social import Post

    user = await register_user(client, handle="faker")
    for kind in ("proof", "post;proof", "PROOF"):
        response = await client.post(
            "/api/v1/feed/posts",
            json={"kind": kind, "body": "Look at my totally real work"},
            headers=auth(user["token"]),
        )
        assert response.status_code == 422, f"kind={kind!r} must be rejected by the API contract"

    # And a legitimate post is never silently a proof post.
    ok = await client.post(
        "/api/v1/feed/posts",
        json={"kind": "post", "body": "hello #indore"},
        headers=auth(user["token"]),
    )
    assert ok.status_code == 201
    assert ok.json()["kind"] == "post"
    assert ok.json()["gig_id"] is None
    assert ok.json()["hashtags"] == ["indore"]


async def test_proof_posts_are_permanent(client, session_factory, db):
    """Proof is evidence tied to a paid transaction; deleting it would erase the record."""
    category_id = await add_category(session_factory)
    worker = await make_worker(client, session_factory, handle="sunita", category_id=category_id)
    customer = await register_user(client, handle="amit")
    await client.post("/api/v1/auth/capability/can_hire", headers=auth(customer["token"]))

    gig = (
        await client.post(
            "/api/v1/gigs",
            json={
                "category_id": category_id,
                "title": "Fix wiring",
                "lat": 22.7196,
                "lng": 75.8577,
            },
            headers=auth(customer["token"]),
        )
    ).json()

    await client.post(
        f"/api/v1/gigs/{gig['id']}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )
    await secure_gig_payment(client, customer, gig["id"])
    for status in ("en_route", "arrived", "in_progress", "completion_pending"):
        await client.post(
            f"/api/v1/gigs/{gig['id']}/status",
            json={"status": status},
            headers=auth(worker["token"]),
        )
    await release_gig_payment(client, customer, gig["id"])

    feed = (await client.get("/api/v1/feed/posts", headers=auth(worker["token"]))).json()
    proof_id = next(p["id"] for p in feed if p["kind"] == "proof")

    deleted = await client.delete(
        f"/api/v1/feed/posts/{proof_id}", headers=auth(worker["token"])
    )
    assert deleted.status_code == 409, "proof posts must be undeletable"


async def test_dispute_lowers_karma_and_rank(client, session_factory, db):
    """★ The two halves share one number: a marketplace dispute changes the person."""
    category_id = await add_category(session_factory)
    worker = await make_worker(
        client, session_factory, handle="mohan", category_id=category_id, total_jobs=30
    )
    customer = await register_user(client, handle="neha")
    await client.post("/api/v1/auth/capability/can_hire", headers=auth(customer["token"]))

    before = (await client.get("/api/v1/karma/ledger", headers=auth(worker["token"]))).json()

    gig = (
        await client.post(
            "/api/v1/gigs",
            json={
                "category_id": category_id,
                "title": "Paint a wall",
                "lat": 22.7196,
                "lng": 75.8577,
            },
            headers=auth(customer["token"]),
        )
    ).json()
    await client.post(
        f"/api/v1/gigs/{gig['id']}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )

    dispute = await client.post(
        f"/api/v1/gigs/{gig['id']}/dispute",
        json={"reason": "Worker never arrived and stopped responding."},
        headers=auth(customer["token"]),
    )
    assert dispute.status_code == 201, dispute.text

    after = (await client.get("/api/v1/karma/ledger", headers=auth(worker["token"]))).json()
    assert after["work"] < before["work"], "a dispute must cost work karma"
    assert after["blended"] < before["blended"], "and it must show on the blended number"


async def test_auth_is_enforced_everywhere(client, session_factory):
    category_id = await add_category(session_factory)
    anon = await client.get("/api/v1/feed/posts")
    assert anon.status_code == 401

    bad = await client.get(
        "/api/v1/feed/posts", headers={"Authorization": "Bearer not.a.real.token"}
    )
    assert bad.status_code == 401


async def test_wrong_password_and_unknown_user_are_indistinguishable(client):
    await register_user(client, handle="someone", password="RightPass!99")

    wrong = await client.post(
        "/api/v1/auth/login", json={"identifier": "someone", "password": "WrongPass!99"}
    )
    nobody = await client.post(
        "/api/v1/auth/login", json={"identifier": "ghost", "password": "WrongPass!99"}
    )
    assert wrong.status_code == nobody.status_code == 401
    assert wrong.json()["detail"] == nobody.json()["detail"], "must not leak which failed"


async def test_refresh_token_cannot_be_used_as_access_token(client):
    user = await register_user(client, handle="tokenuser")
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tokenuser", "password": "StrongPass!234"},
    )
    refresh_token = login.json()["refresh_token"]

    sneaky = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"}
    )
    assert sneaky.status_code == 401, "a refresh token must never authenticate an API call"

    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


async def test_otp_flow_gates_phone_registration(client):
    send = await client.post("/api/v1/auth/otp/send", json={"phone": "919876543210"})
    assert send.status_code == 200
    # The dev OTP is surfaced only because ENVIRONMENT=test (see settings.expose_dev_otp).
    assert send.json()["dev_otp"]

    # Registering on an unverified phone is refused.
    refused = await client.post(
        "/api/v1/auth/register",
        json={
            "handle": "phoneguy",
            "display_name": "Phone Guy",
            "phone": "919876543210",
            "password": "StrongPass!234",
        },
    )
    assert refused.status_code == 400

    verified = await client.post(
        "/api/v1/auth/otp/verify", json={"phone": "919876543210", "otp": send.json()["dev_otp"]}
    )
    assert verified.status_code == 200

    ok = await client.post(
        "/api/v1/auth/register",
        json={
            "handle": "phoneguy",
            "display_name": "Phone Guy",
            "phone": "919876543210",
            "password": "StrongPass!234",
        },
    )
    assert ok.status_code == 201, ok.text
    # Phone verification is a trust event, so karma rose above the starting 50.
    assert ok.json()["user"]["karma"] > 50


async def test_can_work_requires_approved_verification(client, session_factory):
    """A stranger cannot simply declare themselves a worker."""
    category_id = await add_category(session_factory)
    user = await register_user(client, handle="impostor")

    refused = await client.post(
        "/api/v1/workers/register",
        json={"category_id": category_id, "hourly_rate": 400},
        headers=auth(user["token"]),
    )
    assert refused.status_code == 403


async def test_authorisation_precedes_state_validation(client, session_factory):
    """★ Regression: an actor with no right to move a gig must get 403, never 409.

    Checking the state machine first would tell an unauthorised caller what state the gig
    is in -- a small information leak that also reads as a confusing API. Check *who*
    before *what*.
    """
    category_id = await add_category(session_factory)
    worker = await make_worker(client, session_factory, handle="orderworker", category_id=category_id)
    customer = await register_user(client, handle="ordercustomer")
    outsider = await register_user(client, handle="orderoutsider")
    await client.post("/api/v1/auth/capability/can_hire", headers=auth(customer["token"]))

    gig = (
        await client.post(
            "/api/v1/gigs",
            json={
                "category_id": category_id,
                "title": "Ordering test",
                "lat": 22.7196,
                "lng": 75.8577,
            },
            headers=auth(customer["token"]),
        )
    ).json()
    await client.post(
        f"/api/v1/gigs/{gig['id']}/assign?worker_id={worker['user_id']}",
        headers=auth(customer["token"]),
    )

    # The gig is 'assigned'. 'completed' is an illegal transition from there.
    # The customer is not the worker, so this must be 403 -- not 409.
    wrong_actor = await client.post(
        f"/api/v1/gigs/{gig['id']}/status",
        json={"status": "completed"},
        headers=auth(customer["token"]),
    )
    assert wrong_actor.status_code == 403, (
        f"authorisation must precede state validation, got {wrong_actor.status_code}"
    )

    # The worker gets the *state* error instead, because they are authorised.
    illegal_for_worker = await client.post(
        f"/api/v1/gigs/{gig['id']}/status",
        json={"status": "completed"},
        headers=auth(worker["token"]),
    )
    assert illegal_for_worker.status_code == 409

    # A total outsider gets neither detail -- 403.
    snooping = await client.post(
        f"/api/v1/gigs/{gig['id']}/status",
        json={"status": "en_route"},
        headers=auth(outsider["token"]),
    )
    assert snooping.status_code == 403

    # Reading someone else's gig is refused too.
    peek = await client.get(f"/api/v1/gigs/{gig['id']}", headers=auth(outsider["token"]))
    assert peek.status_code == 403


async def test_ledger_reports_true_total_beyond_page_size(client, session_factory, db):
    """★ Regression: the ledger endpoint returns a bounded page, so the UI must not
    label the ledger by that page's length.

    A worker with 60 real events was being shown as "20 events" because the public
    endpoint capped history and the frontend counted the array it got back.
    """
    from app.models.user import KarmaEventType
    from app.services.karma import KarmaLedger

    category_id = await add_category(session_factory)
    worker = await make_worker(client, session_factory, handle="ledgerheavy", category_id=category_id)
    wid = worker["user_id"]

    # Push the ledger well past one page.
    async with session_factory() as s:
        ledger = KarmaLedger(s)
        for i in range(60):
            await ledger.record(
                wid, KarmaEventType.GIG_COMPLETED, reason=f"Completed job #{i} on time"
            )
        await s.commit()

    body = (await client.get(f"/api/v1/karma/ledger/{wid}")).json()
    assert body["total_events"] > len(body["events"]), (
        "the fixture should exceed one page for this test to mean anything"
    )
    assert body["truncated"] is True
    assert len(body["events"]) > 0
    # The number a UI would render as "N events" must be the real count.
    assert body["total_events"] >= 60
