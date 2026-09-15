"""Trust, safety and money.

Trust and safety come from Labour Link essentially intact -- it is the more careful of the
two projects and its safety apparatus is the reason the merged product can exist at all.
Per the risk assessment, these routers cannot be feature-flagged off.

The ledger tables are new and are what let Tatwamasi's KshamCoin-style wallet and Labour
Link's platform-fee Transaction coexist as one money story instead of two.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.sqlite import JSON as JSONType
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


# A dispute counts as "open" for exactly two decisions, and they must agree: while one exists the
# gig's payout is frozen (``payment_workflows.release_gig_payment``), and the same party cannot
# file another (``trust.raise_dispute``). Kept as one constant because the two rules drifting apart
# is the whole exploit -- a freeze that ignores a status the filing limit honours lets a complainant
# hold money hostage by restating a grievance, and a filing limit that ignores the freeze lets them
# do it without ever being stopped.
OPEN_DISPUTE_STATUSES: tuple[str, ...] = ("open", "in_review")

# --------------------------------------------------------------------------
# Trust & verification (Labour Link)
# --------------------------------------------------------------------------
class VerificationSubmission(Base):
    __tablename__ = "verification_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_type: Mapped[str] = mapped_column(String(32))  # aadhaar | pan | govt_id
    # Only a masked reference is stored -- never the document number itself.
    document_ref: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    reviewer_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrustedContact(Base):
    __tablename__ = "trusted_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32))
    relationship: Mapped[str] = mapped_column(String(40), default="")


class SafetyIncident(Base):
    __tablename__ = "safety_incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raised_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    against_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    gig_id: Mapped[int | None] = mapped_column(ForeignKey("gigs.id"), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Dispute(Base):
    """One party's complaint about one gig.

    Deliberately without a unique constraint on ``(gig_id, raised_by)``. A party whose case was
    dismissed must be able to complain again later, so any index here would have to be partial, and
    building a partial index over existing databases means deciding what to do with duplicates whose
    penalties are already in the karma ledger -- collapsing them silently would leave somebody paying
    for a case that no longer exists. ``raise_dispute`` serialises on the gig row instead, which is
    the same lock the payment release and the completion path take.
    """

    __tablename__ = "disputes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gig_id: Mapped[int] = mapped_column(ForeignKey("gigs.id", ondelete="CASCADE"), index=True)
    raised_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --------------------------------------------------------------------------
# Reviews (Labour Link's multi-dimensional review, unchanged in shape)
# --------------------------------------------------------------------------
class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gig_id: Mapped[int] = mapped_column(ForeignKey("gigs.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reviewee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    punctuality: Mapped[int | None] = mapped_column(Integer)
    quality: Mapped[int | None] = mapped_column(Integer)
    communication: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --------------------------------------------------------------------------
# Money: one wallet, one ledger
# --------------------------------------------------------------------------
class LedgerEntry(Base):
    """Every movement of money. Platform fees, payouts, tips, refunds -- one table.

    Tatwamasi's KshamCoin and Labour Link's Transaction were two incompatible money stories;
    a single append-only ledger with an ``entry_type`` discriminator is the merged one.
    """

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    entry_type: Mapped[str] = mapped_column(String(32), index=True)  # payout|fee|tip|refund
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    gig_id: Mapped[int | None] = mapped_column(ForeignKey("gigs.id"), index=True)
    # Nullable for imported history; provider-backed movements always carry a unique reference.
    # This is the database-level backstop against a webhook and API response paying twice.
    external_reference: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True
    )
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Wallet(Base):
    __tablename__ = "wallets"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    lifetime_earned: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    lifetime_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
