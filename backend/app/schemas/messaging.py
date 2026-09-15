"""Strict wire contracts for Bitchat's opaque encrypted relay."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

ALLOWED_TTLS = frozenset({10, 60, 3_600, 86_400, 604_800})


def _b64(value: str, *, size: int, field: str) -> str:
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError(f"{field} must be canonical base64") from exc
    if len(raw) != size:
        raise ValueError(f"{field} must decode to {size} bytes")
    if base64.b64encode(raw).decode("ascii") != value:
        raise ValueError(f"{field} must be canonical base64")
    return value


class BitchatPreKeyIn(BaseModel):
    key_id: int = Field(ge=1, le=2_147_483_647)
    public_key: str = Field(min_length=44, max_length=44)
    signature: str = Field(min_length=88, max_length=88)

    @field_validator("public_key")
    @classmethod
    def _public_key(cls, value: str) -> str:
        return _b64(value, size=32, field="public_key")

    @field_validator("signature")
    @classmethod
    def _signature(cls, value: str) -> str:
        return _b64(value, size=64, field="signature")


class BitchatDeviceRegister(BaseModel):
    device_id: UUID
    label: str = Field(default="This device", min_length=1, max_length=80)
    identity_key: str = Field(min_length=44, max_length=44)
    prekeys: list[BitchatPreKeyIn] = Field(default_factory=list, max_length=50)

    @field_validator("identity_key")
    @classmethod
    def _identity_key(cls, value: str) -> str:
        return _b64(value, size=32, field="identity_key")


class BitchatDeviceOut(BaseModel):
    device_id: str
    label: str
    identity_key: str
    prekeys_available: int


class BitchatSessionOut(BaseModel):
    gig_id: int
    room_id: str
    peer_alias: str
    can_send: bool
    mesh_mode: str = "hybrid"
    ttl_options: list[int] = Field(default_factory=lambda: sorted(ALLOWED_TTLS))
    peer_devices: list[BitchatDeviceOut]


class BitchatPreKeyClaim(BaseModel):
    sender_device_id: UUID
    recipient_device_id: UUID


class BitchatClaimedPreKey(BaseModel):
    recipient_device_id: str
    recipient_identity_key: str
    key_id: int
    public_key: str
    signature: str


class BitchatEnvelopeIn(BaseModel):
    message_id: UUID
    room_id: UUID
    sender_device_id: UUID
    recipient_device_id: UUID
    prekey_id: int = Field(ge=1, le=2_147_483_647)
    ephemeral_key: str = Field(min_length=44, max_length=44)
    nonce: str = Field(min_length=16, max_length=16)
    ciphertext: str = Field(min_length=4, max_length=5_500)
    mac: str = Field(min_length=24, max_length=24)
    signature: str = Field(min_length=88, max_length=88)
    sent_at: datetime
    ttl_seconds: int
    max_hops: int = Field(default=3, ge=0, le=7)
    transport: str = Field(default="server", pattern="^(server|hybrid)$")

    @field_validator("ephemeral_key")
    @classmethod
    def _ephemeral_key(cls, value: str) -> str:
        return _b64(value, size=32, field="ephemeral_key")

    @field_validator("nonce")
    @classmethod
    def _nonce(cls, value: str) -> str:
        return _b64(value, size=12, field="nonce")

    @field_validator("mac")
    @classmethod
    def _mac(cls, value: str) -> str:
        return _b64(value, size=16, field="mac")

    @field_validator("signature")
    @classmethod
    def _signature(cls, value: str) -> str:
        return _b64(value, size=64, field="signature")

    @field_validator("ciphertext")
    @classmethod
    def _ciphertext(cls, value: str) -> str:
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("ciphertext must be canonical base64") from exc
        if not raw or len(raw) > 4_096:
            raise ValueError("ciphertext must decode to 1..4096 bytes")
        if base64.b64encode(raw).decode("ascii") != value:
            raise ValueError("ciphertext must be canonical base64")
        return value

    @field_validator("ttl_seconds")
    @classmethod
    def _ttl(cls, value: int) -> int:
        if value not in ALLOWED_TTLS:
            raise ValueError("ttl_seconds must be 10, 60, 3600, 86400 or 604800")
        return value

    @field_validator("sent_at")
    @classmethod
    def _sent_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("sent_at must include a timezone")
        return value


class BitchatEnvelopeOut(BaseModel):
    message_id: str
    gig_id: int
    room_id: str
    sender_device_id: str
    sender_identity_key: str
    recipient_device_id: str
    prekey_id: int
    ephemeral_key: str
    nonce: str
    ciphertext: str
    mac: str
    signature: str
    sent_at: datetime
    expires_at: datetime
    ttl_seconds: int
    hop_count: int = 0
    max_hops: int
    transport: str


class BitchatPanicIn(BaseModel):
    device_id: UUID
    # Deliberately not free text: panic must never become a transcript exfiltration path.
    reason: Literal["panic_and_wipe"] = "panic_and_wipe"


def envelope_aad(
    *,
    message_id: str,
    room_id: str,
    sender_device_id: str,
    recipient_device_id: str,
    prekey_id: int,
    ephemeral_key: str,
    sent_at: datetime,
    ttl_seconds: int,
    max_hops: int,
) -> str:
    """Canonical associated data shared with the Flutter cryptographic boundary."""
    return "\n".join(
        (
            "KARMA-BITCHAT-AAD-V1",
            message_id,
            room_id,
            sender_device_id,
            recipient_device_id,
            str(prekey_id),
            ephemeral_key,
            str(int(sent_at.timestamp())),
            str(ttl_seconds),
            str(max_hops),
        )
    )


def envelope_signed_bytes(payload: BitchatEnvelopeIn) -> bytes:
    aad = envelope_aad(
        message_id=str(payload.message_id),
        room_id=str(payload.room_id),
        sender_device_id=str(payload.sender_device_id),
        recipient_device_id=str(payload.recipient_device_id),
        prekey_id=payload.prekey_id,
        ephemeral_key=payload.ephemeral_key,
        sent_at=payload.sent_at,
        ttl_seconds=payload.ttl_seconds,
        max_hops=payload.max_hops,
    )
    return f"{aad}\n{payload.nonce}\n{payload.ciphertext}\n{payload.mac}".encode()


def prekey_signed_bytes(device_id: str, key: BitchatPreKeyIn) -> bytes:
    return (
        f"KARMA-BITCHAT-PREKEY-V1\n{device_id}\n{key.key_id}\n{key.public_key}"
    ).encode()
