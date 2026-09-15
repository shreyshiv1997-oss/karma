"""Marketplace domain: service catalogue, worker profiles, availability, gigs, bids.

Derived from Labour Link's ``categories`` / ``laborers`` / ``jobs`` / ``job_bids`` with two
changes: ``laborers`` becomes ``worker_profiles`` (a person is not a labourer until they
choose to work, and may stop), and every money field is a ``Numeric`` handled as ``Decimal``
so fares never float-drift.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.sqlite import JSON as JSONType
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ServiceCategory(Base):
    __tablename__ = "service_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_categories.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), unique=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    emoji: Mapped[str] = mapped_column(String(8), default="🔧")
    base_fare: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal(200))
    per_km_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal(18))
    per_hour_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal(350))
    urgency_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("1.25"))
    night_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("1.15"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkerProfile(Base):
    """1:1 with User. Exists only for people who have opted into working."""

    __tablename__ = "worker_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(ForeignKey("service_categories.id"), index=True)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal(350))
    rating: Mapped[float] = mapped_column(Float, default=5.0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    is_available: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    avg_response_time_seconds: Mapped[int] = mapped_column(Integer, default=900)
    verification_tier: Mapped[str] = mapped_column(String(16), default="bronze")
    background_check_status: Mapped[str] = mapped_column(String(24), default="not_started")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bio: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSONType, default=list)

    # Dev/SQLite location. Postgres deployments use a Geography column `current_location`;
    # GeoPort is the only code that knows which one it is reading.
    lat: Mapped[float | None] = mapped_column(Float, index=True)
    lng: Mapped[float | None] = mapped_column(Float, index=True)
    location_source: Mapped[str | None] = mapped_column(String(16))
    location_accuracy_m: Mapped[float | None] = mapped_column(Float)
    location_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Availability(Base):
    """Weekly recurring availability, ported from Labour Link."""

    __tablename__ = "worker_availability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)  # 0 = Monday
    start_minute: Mapped[int] = mapped_column(Integer)  # minutes from midnight
    end_minute: Mapped[int] = mapped_column(Integer)


class Gig(Base):
    """Labour Link's Job, renamed: a 'job' in a social app means employment, which is not
    what this is. A gig is a single unit of hired work."""

    __tablename__ = "gigs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("service_categories.id"))

    title: Mapped[str] = mapped_column(String(140), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="searching", index=True)
    urgency: Mapped[str] = mapped_column(String(16), default="standard")

    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    address_label: Mapped[str] = mapped_column(String(200), default="")
    # Provenance is explicit: an address search and a device fix are different consent paths.
    location_source: Mapped[str] = mapped_column(
        String(16), default="provided", server_default="provided"
    )
    location_accuracy_m: Mapped[float | None] = mapped_column(Float)
    geocoder: Mapped[str | None] = mapped_column(String(64))

    fare_breakdown: Mapped[dict] = mapped_column(JSONType, default=dict)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal(0))
    estimated_hours: Mapped[float] = mapped_column(Float, default=2.0)
    photos: Mapped[list] = mapped_column(JSONType, default=list)
    proof_photos: Mapped[list] = mapped_column(JSONType, default=list)

    payment_status: Mapped[str] = mapped_column(String(32), default="pending")
    preferred_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GigBid(Base):
    __tablename__ = "gig_bids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gig_id: Mapped[int] = mapped_column(ForeignKey("gigs.id", ondelete="CASCADE"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Allowed gig status transitions -- a state machine, not a free-text field.
GIG_TRANSITIONS: dict[str, set[str]] = {
    "searching": {"assigned", "cancelled"},
    "assigned": {"en_route", "cancelled"},
    "en_route": {"arrived", "cancelled"},
    "arrived": {"in_progress", "cancelled"},
    # The worker submits proof first; only a provider-confirmed customer release may move
    # completion_pending -> completed and publish/credit the irreversible side effects.
    "in_progress": {"completion_pending", "cancelled"},
    "completion_pending": set(),
    "completed": set(),
    "cancelled": set(),
}
