"""Canonical user identity and the Karma Ledger.

This is where the two projects actually become one.

Both source projects put a ``reputation_score`` on ``users``:
    Tatwamasi   Float,      default 100.0
    LabourLink  Numeric(5,2) default 50.00
Two teams, one instinct. KARMA keeps that instinct and makes it rigorous: ``karma`` is a
cached projection of an append-only ``karma_events`` ledger. Nothing writes ``users.karma``
directly -- not the feed, not the marketplace, not an admin patch. The number is always the
sum of its history, which makes it auditable, replayable, and impossible to drift.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

# SQLite has no JSONB; SQLAlchemy's generic JSON maps to JSON on sqlite and we use the
# sqlite-specific type explicitly so the same model file works on both dialects.
JSONType = SQLiteJSON


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class KarmaDomain(str, enum.Enum):
    """Which half of the product an event came from.

    Keeping this on every row is the mitigation for the gaming risk: a user cannot convert
    social popularity into marketplace trust, because the marketplace ranker can (and does)
    weight domains differently.
    """

    TRUST = "trust"
    WORK = "work"
    SOCIAL = "social"
    MIGRATION = "migration"


class KarmaEventType(str, enum.Enum):
    # trust
    PHONE_VERIFIED = "phone_verified"
    KYC_APPROVED = "kyc_approved"
    # work
    GIG_COMPLETED = "gig_completed"
    REVIEW_RECEIVED = "review_received"
    DISPUTE_FILED = "dispute_filed"
    SOS_RAISED = "sos_raised"
    # social
    PROOF_PUBLISHED = "proof_published"
    STREAK_DAY = "streak_day"
    POST_REPORTED_UPHELD = "post_reported_upheld"
    # exoneration: the exact negation of a penalty whose case was dismissed. Not a
    # "happened" event with its own value -- its delta is copied from what it reverses.
    CASE_DISMISSED = "case_dismissed"
    # migration
    MIGRATION_BACKFILL = "migration_backfill"


# Delta table: the single place karma values are decided.
KARMA_DELTAS: dict[KarmaEventType, int] = {
    KarmaEventType.PHONE_VERIFIED: 5,
    KarmaEventType.KYC_APPROVED: 8,  # scaled by tier in the ledger service
    KarmaEventType.GIG_COMPLETED: 3,
    KarmaEventType.REVIEW_RECEIVED: 4,  # scaled by rating in the ledger service
    KarmaEventType.DISPUTE_FILED: -15,
    KarmaEventType.SOS_RAISED: -25,
    KarmaEventType.PROOF_PUBLISHED: 2,
    KarmaEventType.STREAK_DAY: 1,
    KarmaEventType.POST_REPORTED_UPHELD: -10,
    # Zero by construction, like the migration row: the ledger refuses to invent a number for
    # a reversal. It negates whatever the original penalty actually was, so a -15 dispute and a
    # -25 SOS are each undone by their own amount rather than by a constant that could drift
    # away from the penalty it is meant to cancel.
    KarmaEventType.CASE_DISMISSED: 0,
    KarmaEventType.MIGRATION_BACKFILL: 0,
}


class User(Base):
    """One identity. Capabilities are additive -- there is no role-selection screen."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, default=_uuid, index=True)

    # --- identifiers: email (Tatwamasi) OR phone (Labour Link), at least one required ---
    handle: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))

    display_name: Mapped[str] = mapped_column(String(160), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    city: Mapped[str | None] = mapped_column(String(100))

    # --- capabilities (replaces Labour Link's user_type enum) ---
    capabilities: Mapped[list] = mapped_column(
        JSONType, default=lambda: ["can_post", "can_follow", "can_chat"]
    )

    # --- trust ---
    is_verified: Mapped[bool] = mapped_column(default=False)
    verification_tier: Mapped[str] = mapped_column(String(16), default="none")
    is_suspended: Mapped[bool] = mapped_column(default=False)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The session epoch. Every token carries this value as its `ver` claim, so one write here
    # invalidates every token issued before it -- the only way "log out everywhere" can be
    # honest without a row per token. See app/core/revocation.py.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # --- KARMA: the fusion number ---
    karma: Mapped[int] = mapped_column(Integer, default=50, index=True)
    karma_work: Mapped[int] = mapped_column(Integer, default=50)
    karma_social: Mapped[int] = mapped_column(Integer, default=50)
    # Preserved for the matching engine, which historically read this field.
    reputation_score: Mapped[float] = mapped_column(Float, default=50.0)

    # --- social (Tatwamasi) ---
    followers_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    posts_count: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    status_text: Mapped[str | None] = mapped_column(String(100))

    # --- provenance for the migration ETL ---
    external_ids: Mapped[dict] = mapped_column(JSONType, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_now
    )

    karma_events: Mapped[list["KarmaEvent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class KarmaEvent(Base):
    """Append-only. Rows are never updated or deleted -- that is the whole point."""

    __tablename__ = "karma_events"
    __table_args__ = (
        Index("ix_karma_events_user_created", "user_id", "created_at"),
        # An exoneration may be recorded at most once per penalty. `recompute()` sums this table,
        # so a double-dismissed dispute that appended two reversals would pay karma back twice --
        # and the ledger, being append-only, has no later chance to notice. The read-side guard in
        # `KarmaLedger.reverse` keeps the friendly path friendly; this is what makes the
        # invariant true even when two admins click "dismissed" in the same instant.
        Index(
            "uq_karma_reversal_target",
            "ref_type",
            "ref_id",
            unique=True,
            sqlite_where=text("ref_type = 'karma_reversal'"),
            postgresql_where=text("ref_type = 'karma_reversal'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(40))
    domain: Mapped[str] = mapped_column(String(16), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200), default="")
    ref_type: Mapped[str | None] = mapped_column(String(32))  # gig / review / post / kyc
    ref_id: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    user: Mapped[User] = relationship(back_populates="karma_events")


class Follow(Base):
    __tablename__ = "follows"

    follower_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    following_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
