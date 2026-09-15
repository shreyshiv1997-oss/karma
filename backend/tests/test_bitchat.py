"""Bitchat integration and security invariants.

The backend must prove what it can prove without possessing message keys: only gig parties may
exchange envelopes, public prekeys and envelopes are signed, every prekey is consumed once,
plaintext never enters storage, expiry physically deletes ciphertext, and panic leaves only a
minimal safety audit.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import func, select

from app.models.messaging import (
    BitchatDevice,
    BitchatEnvelope,
    BitchatPanicEvent,
    BitchatPreKey,
)
from app.models.trust import SafetyIncident
from app.schemas.messaging import (
    BitchatEnvelopeIn,
    BitchatPreKeyIn,
    envelope_signed_bytes,
    prekey_signed_bytes,
)
from app.services.bitchat import purge_expired
from app.services.realtime import realtime
from tests.conftest import (
    add_category,
    auth,
    make_worker,
    register_user,
    release_gig_payment,
    secure_gig_payment,
)

pytestmark = pytest.mark.asyncio


def _raw_public(key) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


@pytest.fixture(autouse=True)
def _clean_realtime():
    realtime.reset()
    yield
    realtime.reset()


async def _active_gig(client, session_factory):
    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="priya")
    grant = await client.post(
        "/api/v1/auth/capability/can_hire", headers=auth(customer["token"])
    )
    assert grant.status_code == 200, grant.text
    worker = await make_worker(
        client,
        session_factory,
        handle="ramesh",
        category_id=category_id,
    )
    posted = await client.post(
        "/api/v1/gigs",
        headers=auth(customer["token"]),
        json={
            "category_id": category_id,
            "title": "Repair the service panel",
            "description": "Breaker trips under load.",
            "lat": 22.7196,
            "lng": 75.8577,
        },
    )
    assert posted.status_code == 201, posted.text
    gig_id = posted.json()["id"]
    assigned = await client.post(
        f"/api/v1/gigs/{gig_id}/assign",
        params={"worker_id": worker["user_id"]},
        headers=auth(customer["token"]),
    )
    assert assigned.status_code == 200, assigned.text
    return customer, worker, gig_id


def _device_payload(*, count: int = 3):
    device_id = str(uuid4())
    identity = Ed25519PrivateKey.generate()
    identity_public = _b64(_raw_public(identity))
    prekeys = []
    for key_id in range(1, count + 1):
        private = X25519PrivateKey.generate()
        public = _b64(_raw_public(private))
        unsigned = BitchatPreKeyIn(
            key_id=key_id,
            public_key=public,
            signature=_b64(bytes(64)),
        )
        signature = identity.sign(prekey_signed_bytes(device_id, unsigned))
        prekeys.append(
            {
                "key_id": key_id,
                "public_key": public,
                "signature": _b64(signature),
            }
        )
    return identity, {
        "device_id": device_id,
        "label": "Test phone",
        "identity_key": identity_public,
        "prekeys": prekeys,
    }


async def _register(client, account, *, count: int = 3):
    identity, payload = _device_payload(count=count)
    response = await client.post(
        "/api/v1/bitchat/devices",
        headers=auth(account["token"]),
        json=payload,
    )
    assert response.status_code == 200, response.text
    return identity, payload


async def _claim(client, customer, gig_id: int, sender: dict, recipient: dict):
    response = await client.post(
        f"/api/v1/bitchat/gigs/{gig_id}/prekeys/claim",
        headers=auth(customer["token"]),
        json={
            "sender_device_id": sender["device_id"],
            "recipient_device_id": recipient["device_id"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _envelope(
    identity: Ed25519PrivateKey,
    *,
    room_id: str,
    sender: dict,
    recipient: dict,
    claimed: dict,
    message_id: str | None = None,
) -> dict:
    body = {
        "message_id": message_id or str(uuid4()),
        "room_id": room_id,
        "sender_device_id": sender["device_id"],
        "recipient_device_id": recipient["device_id"],
        "prekey_id": claimed["key_id"],
        "ephemeral_key": _b64(_raw_public(X25519PrivateKey.generate())),
        "nonce": _b64(b"n" * 12),
        # Opaque bytes on purpose: this endpoint must not know or accept plaintext.
        "ciphertext": _b64(b"encrypted-not-readable-by-the-server"),
        "mac": _b64(b"m" * 16),
        "signature": _b64(bytes(64)),
        "sent_at": datetime.now(UTC).isoformat(),
        "ttl_seconds": 3600,
        "max_hops": 3,
        "transport": "hybrid",
    }
    parsed = BitchatEnvelopeIn.model_validate(body)
    body["signature"] = _b64(identity.sign(envelope_signed_bytes(parsed)))
    return body


async def test_only_gig_parties_can_open_a_pseudonymous_session(
    client, session_factory
):
    customer, worker, gig_id = await _active_gig(client, session_factory)
    await _register(client, worker)

    opened = await client.get(
        f"/api/v1/bitchat/gigs/{gig_id}/session",
        headers=auth(customer["token"]),
    )
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["room_id"]
    assert body["peer_alias"] != worker.get("display_name", "Ramesh")
    assert body["can_send"] is True
    assert body["peer_devices"][0]["prekeys_available"] == 3
    assert body["ttl_options"] == [10, 60, 3600, 86400, 604800]

    stranger = await register_user(client, handle="stranger")
    refused = await client.get(
        f"/api/v1/bitchat/gigs/{gig_id}/session",
        headers=auth(stranger["token"]),
    )
    assert refused.status_code == 404


async def test_device_keys_are_signed_immutable_and_capability_gated(
    client, session_factory
):
    customer, _worker, _gig_id = await _active_gig(client, session_factory)
    identity, payload = await _register(client, customer)

    replay = await client.post(
        "/api/v1/bitchat/devices",
        headers=auth(customer["token"]),
        json=payload,
    )
    assert replay.status_code == 200
    assert replay.json()["prekeys_available"] == 3

    forged = dict(payload)
    forged["prekeys"] = [dict(payload["prekeys"][0])]
    forged["prekeys"][0]["key_id"] = 99
    invalid = await client.post(
        "/api/v1/bitchat/devices",
        headers=auth(customer["token"]),
        json=forged,
    )
    assert invalid.status_code == 422

    changed = dict(payload)
    changed["identity_key"] = _b64(_raw_public(Ed25519PrivateKey.generate()))
    replaced = await client.post(
        "/api/v1/bitchat/devices",
        headers=auth(customer["token"]),
        json=changed,
    )
    assert replaced.status_code == 409

    from app.models.user import User

    async with session_factory() as session:
        user = await session.get(User, customer["user"]["id"])
        user.capabilities = [c for c in user.capabilities if c != "can_chat"]
        await session.commit()
    denied = await client.get(
        "/api/v1/bitchat/gigs/1/session", headers=auth(customer["token"])
    )
    assert denied.status_code == 403
    assert identity is not None


async def test_prekey_is_reserved_once_and_consumed_by_signed_ciphertext(
    client, session_factory
):
    customer, worker, gig_id = await _active_gig(client, session_factory)
    customer_identity, customer_device = await _register(client, customer)
    _worker_identity, worker_device = await _register(client, worker, count=2)
    session = await client.get(
        f"/api/v1/bitchat/gigs/{gig_id}/session",
        headers=auth(customer["token"]),
    )
    room_id = session.json()["room_id"]

    claimed = await _claim(client, customer, gig_id, customer_device, worker_device)
    assert claimed["key_id"] == 1
    body = _envelope(
        customer_identity,
        room_id=room_id,
        sender=customer_device,
        recipient=worker_device,
        claimed=claimed,
    )
    sent = await client.post(
        f"/api/v1/bitchat/gigs/{gig_id}/messages",
        headers=auth(customer["token"]),
        json=body,
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["ciphertext"] == body["ciphertext"]
    assert "plaintext" not in sent.json()

    inbox = await client.get(
        f"/api/v1/bitchat/gigs/{gig_id}/inbox",
        params={"device_id": worker_device["device_id"]},
        headers=auth(worker["token"]),
    )
    assert inbox.status_code == 200, inbox.text
    assert [item["message_id"] for item in inbox.json()] == [body["message_id"]]
    assert inbox.json()[0]["sender_identity_key"] == customer_device["identity_key"]

    # An HTTP retry is idempotent even though the one-time prekey has been deleted.
    retried = await client.post(
        f"/api/v1/bitchat/gigs/{gig_id}/messages",
        headers=auth(customer["token"]),
        json=body,
    )
    assert retried.status_code == 201, retried.text

    # Opening the recipient app before inbox decryption re-registers every local
    # private prekey. A consumed tombstone must stop key 1 becoming available again.
    reopened = await client.post(
        "/api/v1/bitchat/devices",
        headers=auth(worker["token"]),
        json=worker_device,
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["prekeys_available"] == 1

    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(BitchatEnvelope)) == 1
        tombstone = await db.get(BitchatPreKey, (worker_device["device_id"], 1))
        assert tombstone is not None
        assert tombstone.consumed_at is not None
        assert tombstone.claimed_by_device_id is None
        assert tombstone.claimed_gig_id is None

    events = [event for event in realtime.published if event.type == "bitchat.message"]
    assert len(events) == 1
    assert events[0].data["message_id"] == body["message_id"]


async def test_wrong_recipient_and_tampered_envelopes_are_rejected(
    client, session_factory
):
    customer, worker, gig_id = await _active_gig(client, session_factory)
    customer_identity, customer_device = await _register(client, customer)
    _worker_identity, worker_device = await _register(client, worker)
    stranger = await register_user(client, handle="mallory")
    _stranger_identity, stranger_device = await _register(client, stranger)

    room_id = (
        await client.get(
            f"/api/v1/bitchat/gigs/{gig_id}/session",
            headers=auth(customer["token"]),
        )
    ).json()["room_id"]
    wrong = await client.post(
        f"/api/v1/bitchat/gigs/{gig_id}/prekeys/claim",
        headers=auth(customer["token"]),
        json={
            "sender_device_id": customer_device["device_id"],
            "recipient_device_id": stranger_device["device_id"],
        },
    )
    assert wrong.status_code == 404

    claimed = await _claim(client, customer, gig_id, customer_device, worker_device)
    body = _envelope(
        customer_identity,
        room_id=room_id,
        sender=customer_device,
        recipient=worker_device,
        claimed=claimed,
    )
    body["ciphertext"] = _b64(b"tampered-after-signing")
    rejected = await client.post(
        f"/api/v1/bitchat/gigs/{gig_id}/messages",
        headers=auth(customer["token"]),
        json=body,
    )
    assert rejected.status_code == 422


async def test_stale_mesh_claim_metadata_is_anonymized_but_never_recycled(
    client, session_factory
):
    customer, worker, gig_id = await _active_gig(client, session_factory)
    _identity, customer_device = await _register(client, customer)
    _other, worker_device = await _register(client, worker)
    claimed = await _claim(client, customer, gig_id, customer_device, worker_device)

    async with session_factory() as db:
        row = await db.get(
            BitchatPreKey, (worker_device["device_id"], claimed["key_id"])
        )
        row.claimed_at = datetime.now(UTC) - timedelta(days=8)
        await db.commit()

    async with session_factory() as db:
        await purge_expired(db)
        await db.commit()
        tombstone = await db.get(
            BitchatPreKey, (worker_device["device_id"], claimed["key_id"])
        )
        assert tombstone is not None
        assert tombstone.claimed_at is not None
        assert tombstone.claimed_by_device_id is None
        assert tombstone.claimed_gig_id is None

    session = await client.get(
        f"/api/v1/bitchat/gigs/{gig_id}/session",
        headers=auth(customer["token"]),
    )
    assert session.status_code == 200
    assert session.json()["peer_devices"][0]["prekeys_available"] == 2


async def test_expired_ciphertext_is_physically_deleted(client, session_factory):
    customer, worker, gig_id = await _active_gig(client, session_factory)
    identity, customer_device = await _register(client, customer)
    _other, worker_device = await _register(client, worker)
    room_id = (
        await client.get(
            f"/api/v1/bitchat/gigs/{gig_id}/session",
            headers=auth(customer["token"]),
        )
    ).json()["room_id"]
    claimed = await _claim(client, customer, gig_id, customer_device, worker_device)
    body = _envelope(
        identity,
        room_id=room_id,
        sender=customer_device,
        recipient=worker_device,
        claimed=claimed,
    )
    sent = await client.post(
        f"/api/v1/bitchat/gigs/{gig_id}/messages",
        headers=auth(customer["token"]),
        json=body,
    )
    assert sent.status_code == 201

    async with session_factory() as db:
        row = await db.scalar(select(BitchatEnvelope))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()

    empty = await client.get(
        f"/api/v1/bitchat/gigs/{gig_id}/inbox",
        params={"device_id": worker_device["device_id"]},
        headers=auth(worker["token"]),
    )
    assert empty.status_code == 200
    assert empty.json() == []
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(BitchatEnvelope)) == 0


async def test_finished_gig_is_read_only(client, session_factory):
    customer, worker, gig_id = await _active_gig(client, session_factory)
    customer_identity, customer_device = await _register(client, customer)
    _worker_identity, worker_device = await _register(client, worker)

    await secure_gig_payment(client, customer, gig_id)
    for state in ("en_route", "arrived", "in_progress", "completion_pending"):
        response = await client.post(
            f"/api/v1/gigs/{gig_id}/status",
            headers=auth(worker["token"]),
            json={
                "status": state,
                "proof_photos": [],
            },
        )
        assert response.status_code == 200, response.text
    await release_gig_payment(client, customer, gig_id)

    closed = await client.get(
        f"/api/v1/bitchat/gigs/{gig_id}/session",
        headers=auth(customer["token"]),
    )
    assert closed.status_code == 200
    assert closed.json()["can_send"] is False
    claim = await client.post(
        f"/api/v1/bitchat/gigs/{gig_id}/prekeys/claim",
        headers=auth(customer["token"]),
        json={
            "sender_device_id": customer_device["device_id"],
            "recipient_device_id": worker_device["device_id"],
        },
    )
    assert claim.status_code == 409
    assert customer_identity is not None


async def test_panic_logs_safety_event_and_cryptographically_wipes_device(
    client, session_factory
):
    customer, worker, gig_id = await _active_gig(client, session_factory)
    _identity, customer_device = await _register(client, customer)
    await _register(client, worker)

    # Panic accepts a fixed signal, never free text that could exfiltrate a transcript.
    refused_note = await client.post(
        f"/api/v1/bitchat/gigs/{gig_id}/panic",
        headers=auth(customer["token"]),
        json={
            "device_id": customer_device["device_id"],
            "reason": "copy this message into the safety log",
        },
    )
    assert refused_note.status_code == 422

    response = await client.post(
        f"/api/v1/bitchat/gigs/{gig_id}/panic",
        headers=auth(customer["token"]),
        json={
            "device_id": customer_device["device_id"],
            "reason": "panic_and_wipe",
        },
    )
    assert response.status_code == 200, response.text

    async with session_factory() as db:
        device = await db.get(BitchatDevice, customer_device["device_id"])
        assert device.revoked_at is not None
        panic_count = await db.scalar(
            select(func.count()).select_from(BitchatPanicEvent)
        )
        incident = await db.scalar(select(SafetyIncident))
        assert panic_count == 1
        assert incident.raised_by == customer["user"]["id"]
        assert incident.against_user_id == worker["user_id"]
        assert "transcript" not in incident.note.lower()

    cannot_reuse = await client.post(
        "/api/v1/bitchat/devices",
        headers=auth(customer["token"]),
        json=customer_device,
    )
    assert cannot_reuse.status_code == 409
    assert any(event.type == "bitchat.panic" for event in realtime.published)
