"""Bitchat: end-to-end encrypted, expiring gig communication.

The API is a key directory and opaque relay, not a chat cryptographic endpoint. Encryption,
decryption and private-key storage stay in Flutter. The backend's responsibilities are strict:
authorise both gig parties, verify signed public material, consume each one-time prekey once,
expire ciphertext, and record a panic without ever receiving transcript plaintext.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select

from app.core.deps import SessionDep, require_capability
from app.models.marketplace import Gig
from app.models.messaging import (
    BitchatConversation,
    BitchatDevice,
    BitchatEnvelope,
    BitchatPanicEvent,
    BitchatPreKey,
)
from app.models.trust import SafetyIncident
from app.models.user import User
from app.schemas import Message
from app.schemas.messaging import (
    BitchatClaimedPreKey,
    BitchatDeviceOut,
    BitchatDeviceRegister,
    BitchatEnvelopeIn,
    BitchatEnvelopeOut,
    BitchatPanicIn,
    BitchatPreKeyClaim,
    BitchatSessionOut,
    envelope_signed_bytes,
    prekey_signed_bytes,
)
from app.services.bitchat import purge_expired
from app.services.realtime import Event, queue_event

router = APIRouter(prefix="/bitchat", tags=["Bitchat"])
ChatUser = Annotated[User, require_capability("can_chat")]

_SENDABLE_GIG_STATES = frozenset({"assigned", "en_route", "arrived", "in_progress"})
_CLOCK_SKEW = timedelta(minutes=5)
_ALIAS_ADJECTIVES = (
    "Amber",
    "Calm",
    "Cedar",
    "Copper",
    "Indigo",
    "Quiet",
    "River",
    "Saffron",
)
_ALIAS_NOUNS = (
    "Crane",
    "Heron",
    "Kite",
    "Lotus",
    "Myna",
    "Peacock",
    "Sparrow",
    "Weaver",
)


async def _gig_for(session, gig_id: int, user: User) -> Gig:
    gig = await session.get(Gig, gig_id)
    if gig is None or user.id not in {gig.customer_id, gig.worker_id}:
        # Do not let an authenticated stranger enumerate somebody else's work.
        raise HTTPException(status_code=404, detail="Conversation not found")
    if gig.worker_id is None:
        raise HTTPException(
            status_code=409, detail="Chat opens after a worker is assigned"
        )
    return gig


def _peer_id(gig: Gig, user_id: int) -> int:
    return gig.worker_id if user_id == gig.customer_id else gig.customer_id


def _alias(room_id: str, user_id: int) -> str:
    digest = hashlib.sha256(f"{room_id}:{user_id}".encode()).digest()
    return (
        f"{_ALIAS_ADJECTIVES[digest[0] % len(_ALIAS_ADJECTIVES)]} "
        f"{_ALIAS_NOUNS[digest[1] % len(_ALIAS_NOUNS)]}"
    )


def _verify(public_key: str, signature: str, message: bytes) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(
            base64.b64decode(signature), message
        )
    except (InvalidSignature, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="Invalid Ed25519 signature"
        ) from exc


async def _owned_device(
    session,
    device_id: str,
    user_id: int,
    *,
    allow_revoked: bool = False,
    lock: bool = False,
) -> BitchatDevice:
    device = await session.get(BitchatDevice, device_id, with_for_update=lock)
    if (
        device is None
        or device.user_id != user_id
        or (device.revoked_at is not None and not allow_revoked)
    ):
        raise HTTPException(status_code=404, detail="Bitchat device not found")
    return device


async def _lock_exchange_devices(session, first_id: str, second_id: str) -> None:
    """Lock both device rows in stable order so panic cannot race a send/claim."""
    await session.execute(
        select(BitchatDevice.id)
        .where(BitchatDevice.id.in_({first_id, second_id}))
        .order_by(BitchatDevice.id.asc())
        .with_for_update()
    )


def _envelope_out(row: BitchatEnvelope, identity_key: str) -> BitchatEnvelopeOut:
    return BitchatEnvelopeOut(
        message_id=row.message_id,
        gig_id=row.gig_id,
        room_id=row.room_id,
        sender_device_id=row.sender_device_id,
        sender_identity_key=identity_key,
        recipient_device_id=row.recipient_device_id,
        prekey_id=row.prekey_id,
        ephemeral_key=row.ephemeral_key,
        nonce=row.nonce,
        ciphertext=row.ciphertext,
        mac=row.mac,
        signature=row.signature,
        sent_at=row.sent_at,
        expires_at=row.expires_at,
        ttl_seconds=row.ttl_seconds,
        max_hops=row.max_hops,
        transport=row.transport,
    )


@router.post("/devices", response_model=BitchatDeviceOut)
async def register_device(
    payload: BitchatDeviceRegister,
    user: ChatUser,
    session: SessionDep,
) -> BitchatDeviceOut:
    """Register public identity material and replenish signed one-time prekeys."""
    await purge_expired(session)
    device_id = str(payload.device_id)
    device = await session.get(BitchatDevice, device_id, with_for_update=True)
    if device is None:
        device = BitchatDevice(
            id=device_id,
            user_id=user.id,
            label=payload.label.strip(),
            identity_key=payload.identity_key,
            last_seen_at=datetime.now(UTC),
        )
        session.add(device)
        await session.flush()
    else:
        if device.user_id != user.id:
            raise HTTPException(
                status_code=409, detail="Device id is already registered"
            )
        if device.revoked_at is not None:
            raise HTTPException(
                status_code=409,
                detail="This device was wiped; create a new device identity",
            )
        if device.identity_key != payload.identity_key:
            raise HTTPException(
                status_code=409, detail="A device identity key cannot be replaced"
            )
        device.label = payload.label.strip()
        device.last_seen_at = datetime.now(UTC)

    key_ids = [item.key_id for item in payload.prekeys]
    if len(key_ids) != len(set(key_ids)):
        raise HTTPException(status_code=422, detail="prekey ids must be unique")

    for item in payload.prekeys:
        _verify(
            device.identity_key,
            item.signature,
            prekey_signed_bytes(device.id, item),
        )
        existing = await session.get(BitchatPreKey, (device.id, item.key_id))
        if existing is not None:
            if (
                existing.public_key != item.public_key
                or existing.signature != item.signature
            ):
                raise HTTPException(
                    status_code=409, detail=f"Prekey {item.key_id} cannot be replaced"
                )
            continue
        session.add(
            BitchatPreKey(
                device_id=device.id,
                key_id=item.key_id,
                public_key=item.public_key,
                signature=item.signature,
            )
        )

    await session.flush()
    available = await session.scalar(
        select(func.count())
        .select_from(BitchatPreKey)
        .where(
            BitchatPreKey.device_id == device.id,
            BitchatPreKey.claimed_at.is_(None),
        )
    )
    return BitchatDeviceOut(
        device_id=device.id,
        label=device.label,
        identity_key=device.identity_key,
        prekeys_available=int(available or 0),
    )


@router.delete("/devices/{device_id}", response_model=Message)
async def revoke_device(
    device_id: str,
    user: ChatUser,
    session: SessionDep,
) -> Message:
    device = await _owned_device(session, device_id, user.id, lock=True)
    device.revoked_at = datetime.now(UTC)
    await session.execute(
        delete(BitchatPreKey).where(BitchatPreKey.device_id == device.id)
    )
    await session.execute(
        delete(BitchatEnvelope).where(
            or_(
                BitchatEnvelope.sender_device_id == device.id,
                BitchatEnvelope.recipient_device_id == device.id,
            )
        )
    )
    return Message(detail="Device identity revoked and queued ciphertext erased")


@router.get("/gigs/{gig_id}/session", response_model=BitchatSessionOut)
async def get_session(
    gig_id: int,
    user: ChatUser,
    session: SessionDep,
) -> BitchatSessionOut:
    await purge_expired(session)
    gig = await _gig_for(session, gig_id, user)
    conversation = await session.get(BitchatConversation, gig.id)
    if conversation is None:
        # Both gig parties can open chat for the first time concurrently. Serialize lazy room
        # creation on the existing gig row, then re-check after taking the lock; otherwise two
        # valid requests can race to insert the same conversation primary key and one gets 500.
        await session.execute(
            select(Gig.id).where(Gig.id == gig.id).with_for_update()
        )
        conversation = await session.get(BitchatConversation, gig.id)
        if conversation is None:
            conversation = BitchatConversation(gig_id=gig.id)
            session.add(conversation)
            await session.flush()

    peer_id = _peer_id(gig, user.id)
    devices = (
        (
            await session.execute(
                select(BitchatDevice)
                .where(
                    BitchatDevice.user_id == peer_id,
                    BitchatDevice.revoked_at.is_(None),
                )
                .order_by(BitchatDevice.created_at.asc())
                .limit(8)
            )
        )
        .scalars()
        .all()
    )
    output: list[BitchatDeviceOut] = []
    for device in devices:
        count = await session.scalar(
            select(func.count())
            .select_from(BitchatPreKey)
            .where(
                BitchatPreKey.device_id == device.id,
                BitchatPreKey.claimed_at.is_(None),
            )
        )
        output.append(
            BitchatDeviceOut(
                device_id=device.id,
                label=device.label,
                identity_key=device.identity_key,
                prekeys_available=int(count or 0),
            )
        )

    return BitchatSessionOut(
        gig_id=gig.id,
        room_id=conversation.room_id,
        peer_alias=_alias(conversation.room_id, peer_id),
        can_send=gig.status in _SENDABLE_GIG_STATES,
        peer_devices=output,
    )


@router.post(
    "/gigs/{gig_id}/prekeys/claim",
    response_model=BitchatClaimedPreKey,
)
async def claim_prekey(
    gig_id: int,
    payload: BitchatPreKeyClaim,
    user: ChatUser,
    session: SessionDep,
) -> BitchatClaimedPreKey:
    """Atomically reserve one peer prekey for the caller's device."""
    await purge_expired(session)
    gig = await _gig_for(session, gig_id, user)
    if gig.status not in _SENDABLE_GIG_STATES:
        raise HTTPException(status_code=409, detail="This conversation is read-only")

    sender_id = str(payload.sender_device_id)
    recipient_id = str(payload.recipient_device_id)
    await _lock_exchange_devices(session, sender_id, recipient_id)
    sender_device = await _owned_device(session, sender_id, user.id)
    peer_id = _peer_id(gig, user.id)
    recipient = await _owned_device(session, recipient_id, peer_id)
    row = await session.scalar(
        select(BitchatPreKey)
        .where(
            BitchatPreKey.device_id == recipient.id,
            BitchatPreKey.claimed_at.is_(None),
        )
        .order_by(BitchatPreKey.key_id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        raise HTTPException(
            status_code=409,
            detail="The peer needs to open secure chat and replenish one-time keys",
        )
    row.claimed_by_device_id = sender_device.id
    row.claimed_gig_id = gig.id
    row.claimed_at = datetime.now(UTC)
    await session.flush()
    return BitchatClaimedPreKey(
        recipient_device_id=recipient.id,
        recipient_identity_key=recipient.identity_key,
        key_id=row.key_id,
        public_key=row.public_key,
        signature=row.signature,
    )


@router.post(
    "/gigs/{gig_id}/messages",
    response_model=BitchatEnvelopeOut,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    gig_id: int,
    payload: BitchatEnvelopeIn,
    user: ChatUser,
    session: SessionDep,
) -> BitchatEnvelopeOut:
    """Relay a signed ciphertext envelope after consuming its reserved prekey."""
    await purge_expired(session)
    gig = await _gig_for(session, gig_id, user)
    if gig.status not in _SENDABLE_GIG_STATES:
        raise HTTPException(status_code=409, detail="This conversation is read-only")

    sender_id = str(payload.sender_device_id)
    recipient_id = str(payload.recipient_device_id)
    await _lock_exchange_devices(session, sender_id, recipient_id)
    sender = await _owned_device(session, sender_id, user.id)
    peer_id = _peer_id(gig, user.id)
    recipient = await _owned_device(session, recipient_id, peer_id)
    conversation = await session.get(BitchatConversation, gig.id)
    if conversation is None or conversation.room_id != str(payload.room_id):
        raise HTTPException(status_code=409, detail="Conversation room has changed")

    existing = await session.scalar(
        select(BitchatEnvelope).where(
            BitchatEnvelope.message_id == str(payload.message_id),
            BitchatEnvelope.recipient_device_id == recipient.id,
        )
    )
    if existing is not None:
        if existing.sender_device_id != sender.id or existing.gig_id != gig.id:
            raise HTTPException(status_code=409, detail="Message id is already in use")
        return _envelope_out(existing, sender.identity_key)

    now = datetime.now(UTC)
    sent_at = payload.sent_at.astimezone(UTC)
    if abs(now - sent_at) > _CLOCK_SKEW:
        raise HTTPException(
            status_code=422, detail="sent_at is outside the allowed clock skew"
        )
    expires_at = sent_at + timedelta(seconds=payload.ttl_seconds)
    if expires_at <= now:
        raise HTTPException(status_code=410, detail="Message already expired")

    prekey = await session.get(
        BitchatPreKey, (recipient.id, payload.prekey_id), with_for_update=True
    )
    if (
        prekey is None
        or prekey.claimed_by_device_id != sender.id
        or prekey.claimed_gig_id != gig.id
        or prekey.claimed_at is None
        or prekey.consumed_at is not None
    ):
        raise HTTPException(status_code=409, detail="One-time prekey was not reserved")

    _verify(sender.identity_key, payload.signature, envelope_signed_bytes(payload))
    row = BitchatEnvelope(
        message_id=str(payload.message_id),
        gig_id=gig.id,
        room_id=conversation.room_id,
        sender_id=user.id,
        sender_device_id=sender.id,
        recipient_id=peer_id,
        recipient_device_id=recipient.id,
        prekey_id=payload.prekey_id,
        ephemeral_key=payload.ephemeral_key,
        nonce=payload.nonce,
        ciphertext=payload.ciphertext,
        mac=payload.mac,
        signature=payload.signature,
        sent_at=sent_at,
        expires_at=expires_at,
        ttl_seconds=payload.ttl_seconds,
        max_hops=payload.max_hops,
        transport=payload.transport,
    )
    session.add(row)
    # Keep a consumed tombstone. The recipient may register again before it has
    # downloaded/decrypted this envelope; deleting the row would republish the same
    # client-held private key as "available" and break the one-time-key guarantee.
    prekey.consumed_at = now
    prekey.claimed_by_device_id = None
    prekey.claimed_gig_id = None
    await session.flush()
    queue_event(
        session,
        Event.of(
            "bitchat.message",
            gig.id,
            message_id=row.message_id,
            recipient_device_id=recipient.id,
            expires_at=expires_at.isoformat(),
        ),
    )
    return _envelope_out(row, sender.identity_key)


@router.get("/gigs/{gig_id}/inbox", response_model=list[BitchatEnvelopeOut])
async def inbox(
    gig_id: int,
    user: ChatUser,
    session: SessionDep,
    device_id: str = Query(min_length=36, max_length=36),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[BitchatEnvelopeOut]:
    """Return only unexpired ciphertext addressed to this caller's device."""
    await purge_expired(session)
    await _gig_for(session, gig_id, user)
    device = await _owned_device(session, device_id, user.id)
    device.last_seen_at = datetime.now(UTC)
    rows = (
        await session.execute(
            select(BitchatEnvelope, BitchatDevice.identity_key)
            .join(
                BitchatDevice,
                BitchatDevice.id == BitchatEnvelope.sender_device_id,
            )
            .where(
                BitchatEnvelope.gig_id == gig_id,
                BitchatEnvelope.recipient_device_id == device.id,
                BitchatEnvelope.expires_at > datetime.now(UTC),
            )
            .order_by(BitchatEnvelope.sent_at.asc())
            .limit(limit)
        )
    ).all()
    return [_envelope_out(row, identity_key) for row, identity_key in rows]


@router.post("/gigs/{gig_id}/panic", response_model=Message)
async def panic_and_wipe(
    gig_id: int,
    payload: BitchatPanicIn,
    user: ChatUser,
    session: SessionDep,
) -> Message:
    """Raise a safety incident, erase queued ciphertext, and revoke this key identity."""
    gig = await _gig_for(session, gig_id, user)
    device = await _owned_device(session, str(payload.device_id), user.id, lock=True)
    peer_id = _peer_id(gig, user.id)

    session.add(
        BitchatPanicEvent(
            gig_id=gig.id,
            user_id=user.id,
            device_id=device.id,
            reason=payload.reason,
        )
    )
    session.add(
        SafetyIncident(
            raised_by=user.id,
            against_user_id=peer_id,
            gig_id=gig.id,
            lat=gig.lat,
            lng=gig.lng,
            note="Bitchat panic and cryptographic wipe requested",
            status="open",
        )
    )
    device.revoked_at = datetime.now(UTC)
    await session.execute(
        delete(BitchatPreKey).where(BitchatPreKey.device_id == device.id)
    )
    await session.execute(
        delete(BitchatEnvelope).where(
            or_(
                BitchatEnvelope.sender_device_id == device.id,
                BitchatEnvelope.recipient_device_id == device.id,
            )
        )
    )
    await session.flush()
    queue_event(
        session,
        Event.of("bitchat.panic", gig.id, raised_by=user.id),
    )
    return Message(
        detail="Panic recorded, safety team alerted, and this device identity wiped"
    )
