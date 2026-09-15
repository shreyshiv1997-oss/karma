"""Bitchat: encrypted, ephemeral messaging bound to a real gig.

The server is deliberately an opaque relay. It stores public device material and encrypted
message envelopes, but never receives a message key or plaintext. One-time X25519 prekeys
make an asynchronous first message possible without weakening the client into a shared
server secret. Envelopes expire at the database boundary and are physically swept rather
than merely hidden by the UI.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class BitchatDevice(Base):
    """One client-held identity. Private keys never leave that client."""

    __tablename__ = "bitchat_devices"
    __table_args__ = (Index("ix_bitchat_devices_user_active", "user_id", "revoked_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(80), default="This device")
    identity_key: Mapped[str] = mapped_column(String(44))  # base64 Ed25519 public key
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )


class BitchatPreKey(Base):
    """A signed, one-time X25519 public prekey.

    The matching private key exists only in the device's secure storage. A claim is bound to
    the sender device and gig; the envelope endpoint marks it consumed. The retained row is a
    tombstone: if a recipient registers before downloading its envelope, that old key can
    never accidentally become available again. This preserves the one-time-key guarantee.
    """

    __tablename__ = "bitchat_prekeys"

    device_id: Mapped[str] = mapped_column(
        ForeignKey("bitchat_devices.id", ondelete="CASCADE"), primary_key=True
    )
    key_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_key: Mapped[str] = mapped_column(String(44))
    signature: Mapped[str] = mapped_column(String(88))
    claimed_by_device_id: Mapped[str | None] = mapped_column(String(36), index=True)
    claimed_gig_id: Mapped[int | None] = mapped_column(
        ForeignKey("gigs.id", ondelete="CASCADE"), index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BitchatConversation(Base):
    """A pseudonymous mesh room created lazily for one assigned gig."""

    __tablename__ = "bitchat_conversations"

    gig_id: Mapped[int] = mapped_column(
        ForeignKey("gigs.id", ondelete="CASCADE"), primary_key=True
    )
    room_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=_uuid
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BitchatEnvelope(Base):
    """Ciphertext plus authenticated routing metadata; never plaintext."""

    __tablename__ = "bitchat_envelopes"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "recipient_device_id", name="uq_bitchat_message_recipient"
        ),
        Index(
            "ix_bitchat_envelopes_recipient_expiry",
            "recipient_device_id",
            "expires_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(36), index=True)
    gig_id: Mapped[int] = mapped_column(
        ForeignKey("gigs.id", ondelete="CASCADE"), index=True
    )
    room_id: Mapped[str] = mapped_column(String(36), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sender_device_id: Mapped[str] = mapped_column(
        ForeignKey("bitchat_devices.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_device_id: Mapped[str] = mapped_column(
        ForeignKey("bitchat_devices.id", ondelete="CASCADE"), index=True
    )
    prekey_id: Mapped[int] = mapped_column(Integer)
    ephemeral_key: Mapped[str] = mapped_column(String(44))
    nonce: Mapped[str] = mapped_column(String(16))
    ciphertext: Mapped[str] = mapped_column(Text)
    mac: Mapped[str] = mapped_column(String(24))
    signature: Mapped[str] = mapped_column(String(88))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ttl_seconds: Mapped[int] = mapped_column(Integer)
    max_hops: Mapped[int] = mapped_column(Integer, default=3)
    transport: Mapped[str] = mapped_column(String(16), default="server")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BitchatPanicEvent(Base):
    """Minimal immutable audit that a panic happened; never message content."""

    __tablename__ = "bitchat_panic_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gig_id: Mapped[int] = mapped_column(
        ForeignKey("gigs.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(String(120), default="panic_and_wipe")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
