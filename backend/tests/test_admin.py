# FIXED: Proof posts are unfakeable (kind=proof requires gig_id) — the analytics test now
# asserts the forged proof is impossible, not merely that the arithmetic survives it.
"""Admin surface.

These four endpoints existed for the whole life of the project and were never exercised by a
single test. That is how ``GET /admin/analytics`` shipped with a ``NameError`` -- it imported
``Post`` from nowhere, so the first real call raised a 500, and the README cheerfully claimed
"the ``/admin/*`` endpoints work".

An unexercised endpoint is not a working endpoint. These tests are the difference.
"""

from __future__ import annotations

import pytest

from tests.conftest import (
    add_category,
    auth,
    make_worker,
    register_user,
    release_gig_payment,
    secure_gig_payment,
)

pytestmark = pytest.mark.asyncio


async def _admin(client, session_factory) -> str:
    """A user holding the `admin` capability.

    There is deliberately no API that grants it -- `POST /auth/capability/{cap}` allowlists
    four self-service capabilities and refuses everything else. Admin is provisioned
    out-of-band, which is what the test does by writing the column directly.
    """
    account = await register_user(client, handle="root")
    user_id = account["user"]["id"]

    from app.models.user import User

    async with session_factory() as s:
        user = await s.get(User, user_id)
        user.capabilities = sorted({*(user.capabilities or []), "admin"})
        await s.commit()

    # Re-authenticate so the caller's capability set is current.
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "root@example.com", "password": "StrongPass!234"},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


# ── authorisation ─────────────────────────────────────────────────────────────


async def test_admin_endpoints_refuse_an_ordinary_user(client, session_factory):
    await add_category(session_factory)
    ordinary = await register_user(client, handle="priya")

    for path in (
        "/admin/analytics",
        "/admin/verifications",
        "/admin/safety/incidents",
        "/admin/disputes",
    ):
        response = await client.get(f"/api/v1{path}", headers=auth(ordinary["token"]))
        assert response.status_code == 403, f"{path} -> {response.status_code}"

    for path in ("/admin/safety/incidents/1", "/admin/disputes/1"):
        response = await client.patch(
            f"/api/v1{path}",
            headers=auth(ordinary["token"]),
            json={"status": "resolved"},
        )
        assert response.status_code == 403, f"{path} -> {response.status_code}"


async def test_admin_endpoints_refuse_an_anonymous_caller(client, session_factory):
    await add_category(session_factory)
    for path in (
        "/admin/analytics",
        "/admin/verifications",
        "/admin/safety/incidents",
        "/admin/disputes",
    ):
        response = await client.get(f"/api/v1{path}")
        assert response.status_code == 401, f"{path} -> {response.status_code}"

    for path in ("/admin/safety/incidents/1", "/admin/disputes/1"):
        response = await client.patch(
            f"/api/v1{path}", json={"status": "resolved"}
        )
        assert response.status_code == 401, f"{path} -> {response.status_code}"


async def test_admin_cannot_be_self_granted(client, session_factory):
    """★ The capability endpoint must not be a privilege-escalation path."""
    await add_category(session_factory)
    user = await register_user(client, handle="priya")

    for capability in ("admin", "can_work", "can_verify", "can_moderate"):
        response = await client.post(
            f"/api/v1/auth/capability/{capability}", headers=auth(user["token"])
        )
        assert response.status_code == 400, f"{capability} -> {response.status_code}"

    me = await client.get("/api/v1/auth/me", headers=auth(user["token"]))
    assert me.status_code == 200
    assert "admin" not in me.json()["capabilities"]
    assert "can_work" not in me.json()["capabilities"]


# ── analytics ─────────────────────────────────────────────────────────────────


async def test_analytics_returns_200(client, session_factory):
    """★ Regression: this raised `NameError: name 'Post' is not defined` and returned 500."""
    await add_category(session_factory)
    token = await _admin(client, session_factory)

    response = await client.get("/api/v1/admin/analytics", headers=auth(token))
    assert response.status_code == 200, response.text

    body = response.json()
    for key in (
        "users",
        "workers",
        "gigs",
        "gigs_completed",
        "posts",
        "proof_posts",
        "proof_posts_from_gigs",
        "pending_verifications",
        "open_incidents",
        "open_disputes",
        "proof_rate",
    ):
        assert key in body, f"missing {key}"


async def test_a_proof_post_without_a_gig_cannot_exist(client, session_factory):
    """★ The unfakeable-proof invariant, enforced by the schema rather than by a caller.

    This test used to insert six gig-less proof posts and then assert that the analytics
    *arithmetic* coped with them. That accepted the wrong premise: a proof post with no
    gig behind it is not awkward data to divide carefully, it is a forged trust signal,
    and the feed rendered it identically to evidence of real paid work.

    Now the database refuses it. Against the old schema this insert succeeded and the
    assertion below failed.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models.social import Post, PostKind

    await add_category(session_factory)
    token = await _admin(client, session_factory)
    worker = await make_worker(client, session_factory, handle="ramesh", category_id=1)

    with pytest.raises(IntegrityError, match="ck_posts_proof_requires_gig"):
        async with session_factory() as s:
            s.add(
                Post(
                    author_id=worker["user_id"],
                    kind=PostKind.PROOF.value,
                    body="Standalone proof",
                    media_urls=[],
                    hashtags=[],
                )
            )
            await s.commit()

    # And the metric stays bounded, because the only proofs that can exist are gig-backed.
    response = await client.get("/api/v1/admin/analytics", headers=auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["gigs_completed"] == 0
    assert body["proof_posts"] == 0
    assert body["proof_posts_from_gigs"] == 0
    assert body["proof_rate"] == 0.0
    assert 0.0 <= body["proof_rate"] <= 1.0


async def test_proof_rate_counts_only_gig_backed_proofs(client, session_factory):
    """With one completed gig and one linked proof, the rate is exactly 1.0."""
    category_id = await add_category(session_factory)
    token = await _admin(client, session_factory)

    customer = await register_user(client, handle="priya")
    granted = await client.post(
        "/api/v1/auth/capability/can_hire", headers=auth(customer["token"])
    )
    assert granted.status_code == 200
    worker = await make_worker(
        client, session_factory, handle="ramesh", category_id=category_id
    )

    gig = await client.post(
        "/api/v1/gigs",
        headers=auth(customer["token"]),
        json={
            "category_id": category_id,
            "title": "Rewire the kitchen",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 2,
        },
    )
    gig_id = gig.json()["id"]
    await client.post(
        f"/api/v1/gigs/{gig_id}/assign",
        params={"worker_id": worker["user_id"]},
        headers=auth(customer["token"]),
    )
    await secure_gig_payment(client, customer, gig_id)
    for status_value in ("en_route", "arrived", "in_progress", "completion_pending"):
        moved = await client.post(
            f"/api/v1/gigs/{gig_id}/status",
            headers=auth(worker["token"]),
            json={"status": status_value, "proof_photos": []},
        )
        assert moved.status_code == 200, moved.text
    await release_gig_payment(client, customer, gig_id)

    body = (await client.get("/api/v1/admin/analytics", headers=auth(token))).json()
    assert body["gigs_completed"] == 1
    assert body["proof_posts_from_gigs"] == 1
    assert body["proof_rate"] == 1.0, "every completed gig published proof"


# ── the other three admin routes ──────────────────────────────────────────────


async def test_pending_verifications_lists_submissions(client, session_factory):
    await add_category(session_factory)
    token = await _admin(client, session_factory)

    worker = await register_user(client, handle="ramesh")
    submitted = await client.post(
        "/api/v1/verification/submit",
        headers=auth(worker["token"]),
        json={"document_type": "aadhaar", "document_ref": "123456789012"},
    )
    assert submitted.status_code == 201

    response = await client.get("/api/v1/admin/verifications", headers=auth(token))
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["document_ref"] == "XXXX9012", "document numbers are masked at rest"


async def test_approving_a_verification_grants_can_work(client, session_factory):
    """★ The admin decision is what makes a stranger eligible to enter a home."""
    await add_category(session_factory)
    token = await _admin(client, session_factory)

    worker = await register_user(client, handle="ramesh")
    submission = await client.post(
        "/api/v1/verification/submit",
        headers=auth(worker["token"]),
        json={"document_type": "aadhaar", "document_ref": "123456789012"},
    )
    submission_id = submission.json()["id"]

    approved = await client.patch(
        f"/api/v1/admin/verifications/{submission_id}",
        headers=auth(token),
        json={"decision": "approved", "note": "Document verified."},
    )
    assert approved.status_code == 200, approved.text

    onboarded = await client.post(
        "/api/v1/workers/register",
        headers=auth(worker["token"]),
        json={"category_id": 1, "hourly_rate": 350},
    )
    assert onboarded.status_code == 201, onboarded.text

    me = await client.get("/api/v1/auth/me", headers=auth(worker["token"]))
    assert "can_work" in me.json()["capabilities"]
    assert me.json()["verification_tier"] == "gold"


async def test_an_invalid_decision_is_rejected(client, session_factory):
    await add_category(session_factory)
    token = await _admin(client, session_factory)
    response = await client.patch(
        "/api/v1/admin/verifications/1",
        headers=auth(token),
        json={"decision": "maybe"},
    )
    assert response.status_code == 422


async def test_safety_incidents_are_visible_to_admin(client, session_factory):
    await add_category(session_factory)
    token = await _admin(client, session_factory)

    raiser = await register_user(client, handle="priya")
    raised = await client.post(
        "/api/v1/safety/emergency",
        headers=auth(raiser["token"]),
        json={"gig_id": None, "lat": 22.7196, "lng": 75.8577, "note": "Test signal"},
    )
    assert raised.status_code == 201, raised.text

    response = await client.get("/api/v1/admin/safety/incidents", headers=auth(token))
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["note"] == "Test signal"
    assert rows[0]["raised_by"] == raiser["user"]["id"]
    assert rows[0]["raised_by_name"] == raiser["user"]["display_name"]

    incident_id = rows[0]["id"]
    claimed = await client.patch(
        f"/api/v1/admin/safety/incidents/{incident_id}",
        headers=auth(token),
        json={"status": "in_review"},
    )
    assert claimed.status_code == 200, claimed.text
    resolved = await client.patch(
        f"/api/v1/admin/safety/incidents/{incident_id}",
        headers=auth(token),
        json={"status": "resolved"},
    )
    assert resolved.status_code == 200, resolved.text
    retried = await client.patch(
        f"/api/v1/admin/safety/incidents/{incident_id}",
        headers=auth(token),
        json={"status": "resolved"},
    )
    assert retried.status_code == 200, retried.text
    cannot_reopen = await client.patch(
        f"/api/v1/admin/safety/incidents/{incident_id}",
        headers=auth(token),
        json={"status": "in_review"},
    )
    assert cannot_reopen.status_code == 409


async def test_disputes_can_be_triaged_and_resolved(client, session_factory):
    category_id = await add_category(session_factory)
    token = await _admin(client, session_factory)
    customer = await register_user(client, handle="priya")
    granted = await client.post(
        "/api/v1/auth/capability/can_hire", headers=auth(customer["token"])
    )
    assert granted.status_code == 200
    gig = await client.post(
        "/api/v1/gigs",
        headers=auth(customer["token"]),
        json={
            "category_id": category_id,
            "title": "Unsafe wiring inspection",
            "lat": 22.7196,
            "lng": 75.8577,
        },
    )
    assert gig.status_code == 201, gig.text
    gig_id = gig.json()["id"]
    raised = await client.post(
        f"/api/v1/gigs/{gig_id}/dispute",
        headers=auth(customer["token"]),
        json={"reason": "The quoted scope changed."},
    )
    assert raised.status_code == 201, raised.text

    listing = await client.get("/api/v1/admin/disputes", headers=auth(token))
    assert listing.status_code == 200, listing.text
    dispute = listing.json()[0]
    assert dispute["gig_title"] == "Unsafe wiring inspection"
    assert dispute["raised_by_handle"] == "priya"

    resolved = await client.patch(
        f"/api/v1/admin/disputes/{dispute['id']}",
        headers=auth(token),
        json={"status": "resolved"},
    )
    assert resolved.status_code == 200, resolved.text
    analytics = await client.get("/api/v1/admin/analytics", headers=auth(token))
    assert analytics.json()["open_disputes"] == 0
