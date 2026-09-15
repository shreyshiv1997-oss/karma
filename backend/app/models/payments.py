"""Stripe-backed payment authorization, capture and webhook idempotency.

Card data and PaymentMethod details never enter KARMA. A PaymentIntent authorizes the fixed gig
amount with Stripe; capture happens only after the worker submits completion and the customer
releases the secured payment. The append-only money ledger is written exactly once when capture
is confirmed.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GigPayment(Base):
    """One immutable-priced Stripe PaymentIntent for one assigned gig."""

    __tablename__ = "gig_payments"
    __table_args__ = (
        UniqueConstraint("gig_id", name="uq_gig_payments_gig"),
        UniqueConstraint(
            "provider_payment_intent_id",
            name="uq_gig_payments_provider_intent",
        ),
        Index("ix_gig_payments_status_updated", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gig_id: Mapped[int] = mapped_column(
        ForeignKey("gigs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="stripe")
    provider_payment_intent_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    provider_charge_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_refund_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_status: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    platform_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    worker_payout: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    last_event_created: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(String(240))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StripeWebhookEvent(Base):
    """Small, content-free receipt that makes Stripe's at-least-once delivery idempotent."""

    __tablename__ = "stripe_webhook_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    provider_created: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    object_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="processing")
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
