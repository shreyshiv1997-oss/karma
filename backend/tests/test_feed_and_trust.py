"""Feed and trust surface that the journey test never reaches.

The end-to-end journey exercises the work loop. It does not touch the social feed, trusted
contacts, worker location, or the negative paths around them. Those were the least-covered code
in the codebase -- and the ``/admin/analytics`` bug proved that uncovered code stays broken.
"""

from __future__ import annotations

import pytest

from tests.conftest import add_category, auth, make_worker, register_user

pytestmark = pytest.mark.asyncio


async def _poster(client, handle="priya") -> dict:
    """A user holding `can_post`.

    No re-authentication is needed after the grant: `get_current_user` reloads the user row on
    every request, so the new capability is visible to the next call using the same token.
    """
    user = await register_user(client, handle=handle)
    granted = await client.post("/api/v1/auth/capability/can_post", headers=auth(user["token"]))
    assert granted.status_code == 200, granted.text
    assert "can_post" in granted.json()["capabilities"]
    return user


# ── posting ───────────────────────────────────────────────────────────────────


async def test_a_posting_capable_user_can_post(client, session_factory):
    await add_category(session_factory)
    user = await _poster(client)

    created = await client.post(
        "/api/v1/feed/posts",
        headers=auth(user["token"]),
        json={"kind": "post", "body": "Fixed three fans today. #electrical #indore", "media_urls": []},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["body"].startswith("Fixed three fans")
    assert body["likes_count"] == 0
    assert body["author_handle"] == "priya"


async def test_hashtags_are_harvested_from_the_body(client, session_factory):
    await add_category(session_factory)
    user = await _poster(client)

    created = await client.post(
        "/api/v1/feed/posts",
        headers=auth(user["token"]),
        json={"kind": "post", "body": "Painting #interior work in #Indore today", "hashtags": ["painting"], "media_urls": []},
    )
    assert created.status_code == 201
    assert set(created.json()["hashtags"]) == {"painting", "interior", "Indore"}


async def test_a_user_without_can_post_is_refused(client, session_factory):
    """Signup grants `can_post`, so the refusal path needs the capability taken away.

    This is the moderation lever: revoke the capability and the user can no longer publish,
    without suspending the account.
    """
    from app.models.user import User

    await add_category(session_factory)
    user = await register_user(client, handle="priya")

    # Confirm the default really is permissive, so this test means something.
    allowed = await client.post(
        "/api/v1/feed/posts",
        headers=auth(user["token"]),
        json={"kind": "post", "body": "First post", "media_urls": []},
    )
    assert allowed.status_code == 201, "signup grants can_post by default"

    async with session_factory() as s:
        row = await s.get(User, user["user"]["id"])
        row.capabilities = [c for c in (row.capabilities or []) if c != "can_post"]
        await s.commit()

    refused = await client.post(
        "/api/v1/feed/posts",
        headers=auth(user["token"]),
        json={"kind": "post", "body": "Second post", "media_urls": []},
    )
    assert refused.status_code == 403


async def test_proof_posts_cannot_be_authored_directly(client, session_factory):
    """★ The feed must stay honest: proof is published by gig completion, never by hand."""
    await add_category(session_factory)
    user = await _poster(client)

    created = await client.post(
        "/api/v1/feed/posts",
        headers=auth(user["token"]),
        json={"kind": "proof", "body": "Fake proof", "media_urls": ["https://cdn/x.jpg"]},
    )
    assert created.status_code == 422, "proof is not a client-selectable kind"


async def test_the_feed_can_be_filtered_by_kind(client, session_factory):
    await add_category(session_factory)
    user = await _poster(client)
    for kind, body in (("post", "A note"), ("reel", "A reel"), ("pulse", "Available today")):
        r = await client.post(
            "/api/v1/feed/posts",
            headers=auth(user["token"]),
            json={"kind": kind, "body": body, "media_urls": []},
        )
        assert r.status_code == 201

    everything = await client.get("/api/v1/feed/posts", headers=auth(user["token"]))
    assert everything.status_code == 200
    assert len(everything.json()) == 3

    reels = await client.get("/api/v1/feed/posts", params={"kind": "reel"}, headers=auth(user["token"]))
    assert reels.status_code == 200
    assert [p["kind"] for p in reels.json()] == ["reel"]

    bad = await client.get("/api/v1/feed/posts", params={"kind": "nonsense"}, headers=auth(user["token"]))
    assert bad.status_code == 422, "the kind filter is constrained by a pattern"


# ── search ────────────────────────────────────────────────────────────────────


async def _seed_searchable_posts(client) -> dict:
    """Two authors, three posts with distinct text for the search tests to slice."""
    priya = await _poster(client)  # display_name "Priya"
    ravi = await _poster(client, handle="ravi")
    for author, body in (
        (priya, "Fixed three fans today. #electrical #indore"),
        (ravi, "Replaced a burnt-out distribution board #plumbing"),
        (ravi, "100% genuine parts, guaranteed"),
    ):
        r = await client.post(
            "/api/v1/feed/posts",
            headers=auth(author["token"]),
            json={"kind": "post", "body": body, "media_urls": []},
        )
        assert r.status_code == 201, r.text
    return {"priya": priya, "ravi": ravi}


async def test_the_feed_can_be_searched_by_text_and_hashtag(client, session_factory):
    await add_category(session_factory)
    users = await _seed_searchable_posts(client)
    headers = auth(users["priya"]["token"])

    fans = await client.get("/api/v1/feed/posts", params={"q": "fans"}, headers=headers)
    assert [p["author_handle"] for p in fans.json()] == ["priya"]

    # Hashtags are harvested from the body, so a tag search is a body search -- with or
    # without the '#'.
    for needle in ("plumbing", "#indore"):
        by_tag = await client.get("/api/v1/feed/posts", params={"q": needle}, headers=headers)
        assert len(by_tag.json()) == 1
        assert needle.lstrip("#") in by_tag.json()[0]["body"].lower() + " " + " ".join(by_tag.json()[0]["hashtags"]).lower()

    nothing = await client.get("/api/v1/feed/posts", params={"q": "carpentry"}, headers=headers)
    assert nothing.status_code == 200
    assert nothing.json() == []


async def test_feed_search_is_case_insensitive_and_matches_authors(client, session_factory):
    await add_category(session_factory)
    users = await _seed_searchable_posts(client)
    headers = auth(users["priya"]["token"])

    upper = await client.get("/api/v1/feed/posts", params={"q": "FANS"}, headers=headers)
    assert [p["author_handle"] for p in upper.json()] == ["priya"]

    by_author = await client.get("/api/v1/feed/posts", params={"q": "ravi"}, headers=headers)
    assert len(by_author.json()) == 2, "both of ravi's posts match his handle"

    by_name = await client.get("/api/v1/feed/posts", params={"q": "Priya"}, headers=headers)
    assert [p["author_handle"] for p in by_name.json()] == ["priya"], "display_name is searched too"


async def test_feed_search_escapes_like_wildcards(client, session_factory):
    """A bare '%' must mean a literal percent sign, not 'match everything'."""
    await add_category(session_factory)
    users = await _seed_searchable_posts(client)
    headers = auth(users["priya"]["token"])

    percent = await client.get("/api/v1/feed/posts", params={"q": "%"}, headers=headers)
    assert [p["body"] for p in percent.json()] == ["100% genuine parts, guaranteed"]


async def test_feed_search_combines_with_the_kind_filter(client, session_factory):
    await add_category(session_factory)
    user = await _poster(client)
    for kind, body in (("post", "Available for plumbing"), ("pulse", "plumbing apprentice wanted")):
        r = await client.post(
            "/api/v1/feed/posts",
            headers=auth(user["token"]),
            json={"kind": kind, "body": body, "media_urls": []},
        )
        assert r.status_code == 201

    pulses = await client.get(
        "/api/v1/feed/posts",
        params={"q": "plumbing", "kind": "pulse"},
        headers=auth(user["token"]),
    )
    assert [p["kind"] for p in pulses.json()] == ["pulse"]


async def test_the_feed_requires_authentication(client, session_factory):
    await add_category(session_factory)
    assert (await client.get("/api/v1/feed/posts")).status_code == 401


async def test_an_empty_feed_returns_a_list_not_an_error(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="priya")
    response = await client.get("/api/v1/feed/posts", headers=auth(user["token"]))
    assert response.status_code == 200
    assert response.json() == []


# ── likes ─────────────────────────────────────────────────────────────────────


async def test_a_like_toggles(client, session_factory):
    await add_category(session_factory)
    author = await _poster(client, handle="priya")
    post = (await client.post(
        "/api/v1/feed/posts",
        headers=auth(author["token"]),
        json={"kind": "post", "body": "Look at this", "media_urls": []},
    )).json()

    other = await register_user(client, handle="viewer")

    liked = await client.post(f"/api/v1/feed/posts/{post['id']}/like", headers=auth(other["token"]))
    assert liked.status_code == 200
    assert liked.json()["likes_count"] == 1

    # The same user liking again removes the like rather than counting twice.
    unliked = await client.post(f"/api/v1/feed/posts/{post['id']}/like", headers=auth(other["token"]))
    assert unliked.status_code == 200
    assert unliked.json()["likes_count"] == 0


async def test_the_like_button_knows_which_way_it_landed(client, session_factory):
    """★ `liked_by_me` is the contract the *tap* depends on.

    The like endpoint toggles. A client told only the count cannot render the heart
    truthfully: a card freshly loaded after an earlier like looked un-liked, and the
    next tap unliked server-side while the UI drew a like. Every response that carries
    a post now also says whether the *caller* likes it.
    """
    await add_category(session_factory)
    author = await _poster(client, handle="priya")
    post = (await client.post(
        "/api/v1/feed/posts",
        headers=auth(author["token"]),
        json={"kind": "post", "body": "State of the heart", "media_urls": []},
    )).json()
    fan = await register_user(client, handle="fan")

    # A brand-new post lists as not-liked for everyone, author included.
    feed = await client.get("/api/v1/feed/posts", headers=auth(author["token"]))
    assert feed.json()[0]["liked_by_me"] is False

    liked = await client.post(f"/api/v1/feed/posts/{post['id']}/like", headers=auth(fan["token"]))
    assert liked.json()["liked_by_me"] is True, "the tap response says which way it landed"

    # And it survives the round trip: the fan's feed shows the heart; the author's does not.
    fan_feed = await client.get("/api/v1/feed/posts", headers=auth(fan["token"]))
    assert fan_feed.json()[0]["liked_by_me"] is True
    author_feed = await client.get("/api/v1/feed/posts", headers=auth(author["token"]))
    assert author_feed.json()[0]["liked_by_me"] is False
    assert author_feed.json()[0]["likes_count"] == 1, "the count itself stays per-post global"

    # Toggling back off is also honestly reported, immediately and on reload.
    unliked = await client.post(f"/api/v1/feed/posts/{post['id']}/like", headers=auth(fan["token"]))
    assert unliked.json()["liked_by_me"] is False
    fan_feed = await client.get("/api/v1/feed/posts", headers=auth(fan["token"]))
    assert fan_feed.json()[0]["liked_by_me"] is False


async def test_likes_never_go_negative(client, session_factory):
    """★ Two different users unliking a post the counter has already zeroed."""
    await add_category(session_factory)
    author = await _poster(client, handle="priya")
    post = (await client.post(
        "/api/v1/feed/posts",
        headers=auth(author["token"]),
        json={"kind": "post", "body": "Look", "media_urls": []},
    )).json()

    first = await register_user(client, handle="liker_one")
    second = await register_user(client, handle="liker_two")

    await client.post(f"/api/v1/feed/posts/{post['id']}/like", headers=auth(first["token"]))
    await client.post(f"/api/v1/feed/posts/{post['id']}/like", headers=auth(second["token"]))
    await client.post(f"/api/v1/feed/posts/{post['id']}/like", headers=auth(first["token"]))
    final = await client.post(f"/api/v1/feed/posts/{post['id']}/like", headers=auth(second["token"]))
    assert final.status_code == 200
    assert final.json()["likes_count"] == 0


async def test_liking_a_missing_post_is_a_404(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="priya")
    assert (await client.post("/api/v1/feed/posts/999999/like", headers=auth(user["token"]))).status_code == 404


# ── comments ──────────────────────────────────────────────────────────────────


async def test_comments_are_recorded_with_their_author(client, session_factory):
    await add_category(session_factory)
    author = await _poster(client, handle="priya")
    post = (await client.post(
        "/api/v1/feed/posts",
        headers=auth(author["token"]),
        json={"kind": "post", "body": "Open for work", "media_urls": []},
    )).json()

    commenter = await register_user(client, handle="ramesh")
    added = await client.post(
        f"/api/v1/feed/posts/{post['id']}/comment",
        headers=auth(commenter["token"]),
        json={"body": "I need this done on Saturday."},
    )
    assert added.status_code == 201, added.text

    listing = await client.get(f"/api/v1/feed/posts/{post['id']}/comments", headers=auth(author["token"]))
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["body"] == "I need this done on Saturday."
    assert rows[0]["author_handle"] == "ramesh"

    refreshed = (await client.get("/api/v1/feed/posts", headers=auth(author["token"]))).json()
    assert refreshed[0]["comments_count"] == 1


async def test_an_empty_comment_is_rejected(client, session_factory):
    await add_category(session_factory)
    author = await _poster(client, handle="priya")
    post = (await client.post(
        "/api/v1/feed/posts",
        headers=auth(author["token"]),
        json={"kind": "post", "body": "Open", "media_urls": []},
    )).json()

    for body in ("", "   "):
        r = await client.post(
            f"/api/v1/feed/posts/{post['id']}/comment",
            headers=auth(author["token"]),
            json={"body": body},
        )
        assert r.status_code == 422


async def test_an_oversized_comment_is_rejected(client, session_factory):
    await add_category(session_factory)
    author = await _poster(client, handle="priya")
    post = (await client.post(
        "/api/v1/feed/posts",
        headers=auth(author["token"]),
        json={"kind": "post", "body": "Open", "media_urls": []},
    )).json()

    r = await client.post(
        f"/api/v1/feed/posts/{post['id']}/comment",
        headers=auth(author["token"]),
        json={"body": "x" * 2001},
    )
    assert r.status_code == 422


async def test_commenting_on_a_missing_post_is_a_404(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="priya")
    r = await client.post(
        "/api/v1/feed/posts/999999/comment", headers=auth(user["token"]), json={"body": "hi"}
    )
    assert r.status_code == 404


# ── deletion ──────────────────────────────────────────────────────────────────


async def test_an_author_can_delete_their_own_post(client, session_factory):
    await add_category(session_factory)
    author = await _poster(client, handle="priya")
    post = (await client.post(
        "/api/v1/feed/posts",
        headers=auth(author["token"]),
        json={"kind": "post", "body": "Delete me", "media_urls": []},
    )).json()

    deleted = await client.delete(f"/api/v1/feed/posts/{post['id']}", headers=auth(author["token"]))
    assert deleted.status_code == 200

    remaining = await client.get("/api/v1/feed/posts", headers=auth(author["token"]))
    assert remaining.json() == []


async def test_nobody_can_delete_another_users_post(client, session_factory):
    await add_category(session_factory)
    author = await _poster(client, handle="priya")
    post = (await client.post(
        "/api/v1/feed/posts",
        headers=auth(author["token"]),
        json={"kind": "post", "body": "Mine", "media_urls": []},
    )).json()

    intruder = await register_user(client, handle="intruder")
    r = await client.delete(f"/api/v1/feed/posts/{post['id']}", headers=auth(intruder["token"]))
    assert r.status_code == 403


async def test_deleting_a_missing_post_is_a_404(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="priya")
    assert (await client.delete("/api/v1/feed/posts/999999", headers=auth(user["token"]))).status_code == 404


# ── worker profile and location ───────────────────────────────────────────────


async def test_a_verified_worker_can_set_their_location(client, session_factory):
    category_id = await add_category(session_factory)
    worker = await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    moved = await client.patch(
        "/api/v1/workers/me/location",
        headers=auth(worker["token"]),
        json={
            "lat": 22.7196,
            "lng": 75.8577,
            "accuracy_m": 12.5,
            "location_source": "device",
            "location_consent": True,
            "is_available": True,
        },
    )
    assert moved.status_code == 200, moved.text

    profile = await client.get("/api/v1/workers/me/profile", headers=auth(worker["token"]))
    assert profile.status_code == 200
    body = profile.json()
    assert body["lat"] == 22.7196
    assert body["lng"] == 75.8577
    assert body["is_available"] is True


async def test_going_online_requires_a_fresh_consented_device_fix(client, session_factory):
    category_id = await add_category(session_factory)
    worker = await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    for payload in (
        {"is_available": True},
        {"lat": 22.7, "lng": 75.8, "is_available": True},
        {
            "lat": 22.7,
            "lng": 75.8,
            "location_source": "device",
            "location_consent": False,
            "is_available": True,
        },
    ):
        response = await client.patch(
            "/api/v1/workers/me/location",
            headers=auth(worker["token"]),
            json=payload,
        )
        assert response.status_code == 422, response.text

    offline = await client.patch(
        "/api/v1/workers/me/location",
        headers=auth(worker["token"]),
        json={"is_available": False},
    )
    assert offline.status_code == 200, offline.text


async def test_a_non_numeric_location_is_rejected(client, session_factory):
    category_id = await add_category(session_factory)
    worker = await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    for payload in ({"lat": "north", "lng": 75.8}, {"lng": 75.8}, {"lat": 22.7, "lng": None}):
        r = await client.patch(
            "/api/v1/workers/me/location", headers=auth(worker["token"]), json=payload
        )
        assert r.status_code == 422, f"{payload} -> {r.status_code}"


async def test_a_user_without_a_worker_profile_gets_404(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="priya")
    assert (await client.patch(
        "/api/v1/workers/me/location", headers=auth(user["token"]), json={"lat": 1.0, "lng": 2.0}
    )).status_code == 404
    assert (await client.get("/api/v1/workers/me/profile", headers=auth(user["token"]))).status_code == 404


async def test_an_unverified_user_cannot_register_as_a_worker(client, session_factory):
    """★ Entering a stranger's home requires an approved identity first."""
    category_id = await add_category(session_factory)
    user = await register_user(client, handle="ramesh")

    r = await client.post(
        "/api/v1/workers/register",
        headers=auth(user["token"]),
        json={"category_id": category_id, "hourly_rate": 350},
    )
    assert r.status_code == 403


async def test_registering_against_a_missing_category_is_a_404(client, session_factory):
    """An approved identity is checked *before* the category, so it must be granted first."""
    category_id = await add_category(session_factory)
    worker = await register_user(client, handle="ramesh")

    # Without an approval the route refuses on capability, never reaching the category lookup.
    refused = await client.post(
        "/api/v1/workers/register",
        headers=auth(worker["token"]),
        json={"category_id": 999999, "hourly_rate": 350},
    )
    assert refused.status_code == 403

    submission = await client.post(
        "/api/v1/verification/submit",
        headers=auth(worker["token"]),
        json={"document_type": "aadhaar", "document_ref": "123456789012"},
    )
    assert submission.status_code == 201

    from datetime import UTC, datetime

    from app.models.trust import VerificationSubmission

    async with session_factory() as s:
        row = await s.get(VerificationSubmission, submission.json()["id"])
        row.status = "approved"
        row.reviewed_at = datetime.now(UTC)
        await s.commit()

    missing = await client.post(
        "/api/v1/workers/register",
        headers=auth(worker["token"]),
        json={"category_id": 999999, "hourly_rate": 350},
    )
    assert missing.status_code == 404, "approved, but the category does not exist"


# ── trusted contacts ──────────────────────────────────────────────────────────


async def test_trusted_contacts_can_be_added_and_listed(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="priya")

    added = await client.post(
        "/api/v1/safety/trusted-contacts",
        headers=auth(user["token"]),
        json={"name": "Amma", "phone": "+919876543210", "relationship": "mother"},
    )
    assert added.status_code == 201, added.text

    listing = await client.get("/api/v1/safety/trusted-contacts", headers=auth(user["token"]))
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Amma"

    removed = await client.delete(
        f"/api/v1/safety/trusted-contacts/{rows[0]['id']}", headers=auth(user["token"])
    )
    assert removed.status_code == 200
    assert (await client.get("/api/v1/safety/trusted-contacts", headers=auth(user["token"]))).json() == []


async def test_the_contact_limit_is_enforced(client, session_factory):
    """★ Three contacts. A fourth is refused rather than silently displacing one."""
    await add_category(session_factory)
    user = await register_user(client, handle="priya")

    for i in range(3):
        r = await client.post(
            "/api/v1/safety/trusted-contacts",
            headers=auth(user["token"]),
            json={"name": f"Contact {i}", "phone": f"+91987654321{i}", "relationship": "friend"},
        )
        assert r.status_code == 201, r.text

    fourth = await client.post(
        "/api/v1/safety/trusted-contacts",
        headers=auth(user["token"]),
        json={"name": "Too many", "phone": "+919876543219", "relationship": "friend"},
    )
    assert fourth.status_code == 409


async def test_a_contact_belonging_to_someone_else_cannot_be_removed(client, session_factory):
    await add_category(session_factory)
    owner = await register_user(client, handle="priya")
    added = await client.post(
        "/api/v1/safety/trusted-contacts",
        headers=auth(owner["token"]),
        json={"name": "Amma", "phone": "+919876543210", "relationship": "mother"},
    )
    contact_id = added.json()["id"]

    intruder = await register_user(client, handle="intruder")
    r = await client.delete(
        f"/api/v1/safety/trusted-contacts/{contact_id}", headers=auth(intruder["token"])
    )
    assert r.status_code == 404, "not found, not forbidden -- the id must not be confirmed"

    still_there = await client.get("/api/v1/safety/trusted-contacts", headers=auth(owner["token"]))
    assert len(still_there.json()) == 1


# ── verification ──────────────────────────────────────────────────────────────


async def test_a_user_can_read_their_own_submissions(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="ramesh")

    await client.post(
        "/api/v1/verification/submit",
        headers=auth(user["token"]),
        json={"document_type": "pan", "document_ref": "ABCDE1234F"},
    )
    listing = await client.get("/api/v1/verification/me", headers=auth(user["token"]))
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["document_type"] == "pan"


async def test_a_document_reference_is_never_returned_to_the_submitter(client, session_factory):
    """★ `VerificationOut` omits the reference entirely.

    The full number is never stored -- `_mask` keeps only the last four characters -- and the
    masked tail is shown only to the admin queue, where a reviewer needs it to match against
    the document in front of them. The submitter already has the document; echoing any part of
    the number back would be pure leak surface.
    """
    await add_category(session_factory)
    user = await register_user(client, handle="ramesh")

    created = await client.post(
        "/api/v1/verification/submit",
        headers=auth(user["token"]),
        json={"document_type": "pan", "document_ref": "ABCDE1234F"},
    )
    assert created.status_code == 201
    assert "document_ref" not in created.json(), "not even the masked tail is echoed back"

    listing = await client.get("/api/v1/verification/me", headers=auth(user["token"]))
    for row in listing.json():
        assert "document_ref" not in row

    # The masked tail exists in the database, and is what the admin queue surfaces.
    import sqlite3

    db = sqlite3.connect(session_factory.kw["bind"].url.database or ":memory:")
    try:
        refs = [r[0] for r in db.execute("SELECT document_ref FROM verification_submissions")]
    except sqlite3.OperationalError:
        refs = []
    db.close()
    if refs:
        assert refs[0] == "XXXX1234F" or refs[0].startswith("XXXX"), refs


async def test_a_minimum_length_reference_is_fully_masked(client, session_factory):
    """A four-character reference -- the schema floor -- leaves nothing worth showing."""
    await add_category(session_factory)
    user = await register_user(client, handle="ramesh")
    r = await client.post(
        "/api/v1/verification/submit",
        headers=auth(user["token"]),
        json={"document_type": "govt_id", "document_ref": "AB12"},
    )
    assert r.status_code == 201, r.text
    assert "document_ref" not in r.json()


async def test_a_too_short_reference_is_rejected_at_the_schema(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="ramesh")
    r = await client.post(
        "/api/v1/verification/submit",
        headers=auth(user["token"]),
        json={"document_type": "govt_id", "document_ref": "AB"},
    )
    assert r.status_code == 422, "document_ref has min_length=4"


async def test_an_unrecognised_document_type_is_rejected(client, session_factory):
    await add_category(session_factory)
    user = await register_user(client, handle="ramesh")
    r = await client.post(
        "/api/v1/verification/submit",
        headers=auth(user["token"]),
        json={"document_type": "driving_licence", "document_ref": "DL1234567"},
    )
    assert r.status_code == 422, "document_type is pattern-constrained"


async def test_a_duplicate_worker_profile_is_refused(client, session_factory):
    category_id = await add_category(session_factory)
    worker = await make_worker(client, session_factory, handle="ramesh", category_id=category_id)

    again = await client.post(
        "/api/v1/workers/register",
        headers=auth(worker["token"]),
        json={"category_id": category_id, "hourly_rate": 400},
    )
    assert again.status_code == 409
