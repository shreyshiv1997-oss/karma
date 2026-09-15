"""Transparent fare estimation, ported from Labour Link.

The original's contract is preserved exactly -- every multiplier is returned so the customer
can see why the number is what it is. The one thing deliberately *not* carried over is
``compute_match_score``, which Labour Link kept around as "legacy... for clients/tests" with
an inverted (lower-is-better) polarity from its replacement. Two scorers with opposite
polarities in one codebase is how a future contributor silently books the worst worker.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.core.config import settings

SKILL_TIER_MULTIPLIERS: dict[str, float] = {"bronze": 1.0, "silver": 1.08, "gold": 1.18}


def money(value: float | Decimal) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_night_time(starts_at: datetime | None, tz: ZoneInfo | None = None) -> bool:
    """The 22:00-06:00 window **in marketplace time**.

    Labour Link's original read ``starts_at.hour`` straight off whatever the client sent.
    ``preferred_start_at`` is an ISO-8601 string off the wire, so the same instant arrives
    legitimately as either ``23:30+05:30`` or ``18:00Z`` -- and the surcharge then depended on
    which serialisation the sender chose rather than on when the work starts. One side of that
    pair pays the ``night_multiplier`` and the other does not, so the same job was priced two
    different ways by two different clients.

    So the instant is converted into the marketplace's own timezone before the window is
    judged. A naive datetime is read as *already* marketplace-local, which is what stored
    values and hand-written tests mean by ``datetime(2026, 8, 27, 22, 0)``.

    ``tz`` exists so the policy is testable without editing settings.
    """
    if starts_at is None:
        return False
    local = starts_at.astimezone(tz or ZoneInfo(settings.FARE_TIMEZONE)) if starts_at.tzinfo else starts_at
    return local.hour >= 22 or local.hour < 6


def estimate_fare(
    *,
    base_fare: float,
    per_km_rate: float,
    per_hour_rate: float,
    distance_km: float,
    estimated_hours: float,
    platform_fee_rate: float,
    urgency: str = "standard",
    skill_tier: str = "bronze",
    category_urgency_multiplier: float = 1.25,
    category_night_multiplier: float = 1.15,
    starts_at: datetime | None = None,
) -> dict[str, float]:
    """Explainable pre-booking estimate.

    Multipliers apply only to the service subtotal; the platform fee is then computed from
    that subtotal, so the arithmetic the customer sees is the arithmetic that runs.
    """
    distance_fare = per_km_rate * max(distance_km, 0.0)
    time_fare = per_hour_rate * max(estimated_hours, 0.0)
    subtotal_raw = base_fare + distance_fare + time_fare

    skill_multiplier = SKILL_TIER_MULTIPLIERS.get(skill_tier, 1.0)
    urgency_multiplier = category_urgency_multiplier if urgency == "urgent" else 1.0
    night_multiplier = category_night_multiplier if is_night_time(starts_at) else 1.0

    subtotal = subtotal_raw * skill_multiplier * urgency_multiplier * night_multiplier
    platform_fee = subtotal * platform_fee_rate

    return {
        "base_fare": money(base_fare),
        "distance_fare": money(distance_fare),
        "time_fare": money(time_fare),
        "subtotal": money(subtotal),
        "skill_multiplier": skill_multiplier,
        "urgency_multiplier": urgency_multiplier,
        "night_multiplier": night_multiplier,
        "platform_fee": money(platform_fee),
        "total": money(subtotal + platform_fee),
    }


def custom_price_breakdown(
    *, custom_price: float, platform_fee_rate: float
) -> dict[str, float | str]:
    """A poster-set price, in exactly the shape ``estimate_fare`` returns.

    The customer names what the work is worth; the platform fee is computed on top of
    precisely that number, so the arithmetic stays the arithmetic the customer can see.
    Every multiplier is neutral by definition: a price a person set themselves cannot be
    surcharged by a worker's tier, the clock, or an urgency flag. ``pricing_mode`` rides
    inside the JSON breakdown so the rest of the lifecycle (assignment, payment, payout)
    can tell a poster-set price apart from an estimated one without a schema migration.
    """
    subtotal = money(custom_price)
    fee = money(subtotal * platform_fee_rate)
    return {
        "base_fare": subtotal,
        "distance_fare": 0.0,
        "time_fare": 0.0,
        "subtotal": subtotal,
        "skill_multiplier": 1.0,
        "urgency_multiplier": 1.0,
        "night_multiplier": 1.0,
        "platform_fee": fee,
        "total": money(subtotal + fee),
        "pricing_mode": "custom",
    }


def is_custom_priced(breakdown: dict | None) -> bool:
    """True when a gig's fare carries a price its poster set themselves."""
    return isinstance(breakdown, dict) and breakdown.get("pricing_mode") == "custom"


def split_payout(total: float, platform_fee_rate: float) -> dict[str, float]:
    """Worker payout and platform cut, from an already-agreed total."""
    fee = total * platform_fee_rate
    return {
        "total": money(total),
        "platform_fee": money(fee),
        "worker_payout": money(total - fee),
    }
