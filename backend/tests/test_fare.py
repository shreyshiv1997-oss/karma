"""Fare engine — the contract is preserved exactly from Labour Link."""

from __future__ import annotations

from datetime import datetime

from app.services.fare import estimate_fare, is_night_time, money, split_payout


def test_money_rounds_half_up_to_two_places():
    assert money(1.005) == 1.01
    assert money(10) == 10.0
    assert money(1.999) == 2.0


def test_night_window_boundaries():
    assert is_night_time(datetime(2026, 8, 27, 22, 0)) is True
    assert is_night_time(datetime(2026, 8, 27, 5, 59)) is True
    assert is_night_time(datetime(2026, 8, 27, 6, 0)) is False
    assert is_night_time(datetime(2026, 8, 27, 21, 59)) is False
    assert is_night_time(None) is False


def test_base_estimate_matches_hand_arithmetic():
    """base 200 + (18/km x 4.2) + (350/h x 2h) = 1175.6, +15% fee."""
    result = estimate_fare(
        base_fare=200,
        per_km_rate=18,
        per_hour_rate=350,
        distance_km=4.2,
        estimated_hours=2.0,
        platform_fee_rate=0.15,
    )
    assert result["base_fare"] == 200.0
    assert result["distance_fare"] == 75.6
    assert result["time_fare"] == 700.0
    assert result["subtotal"] == 975.6
    assert result["platform_fee"] == 146.34
    assert result["total"] == 1121.94


def test_multipliers_apply_only_to_subtotal():
    """The platform fee must be computed from the multiplied subtotal, not the raw one."""
    base = estimate_fare(
        base_fare=200,
        per_km_rate=0,
        per_hour_rate=100,
        distance_km=0,
        estimated_hours=1,
        platform_fee_rate=0.15,
    )
    urgent = estimate_fare(
        base_fare=200,
        per_km_rate=0,
        per_hour_rate=100,
        distance_km=0,
        estimated_hours=1,
        platform_fee_rate=0.15,
        urgency="urgent",
        category_urgency_multiplier=1.25,
    )
    assert base["subtotal"] == 300.0
    assert urgent["subtotal"] == 375.0
    # 375 * 0.15 = 56.25 -- fee tracks the multiplied subtotal.
    assert urgent["platform_fee"] == 56.25
    assert urgent["total"] == 431.25


def test_gold_tier_costs_more_than_bronze():
    common = dict(
        base_fare=200,
        per_km_rate=0,
        per_hour_rate=100,
        distance_km=0,
        estimated_hours=1,
        platform_fee_rate=0.15,
    )
    assert estimate_fare(**common, skill_tier="bronze")["total"] < estimate_fare(
        **common, skill_tier="gold"
    )["total"]


def test_night_and_urgent_stack():
    result = estimate_fare(
        base_fare=100,
        per_km_rate=0,
        per_hour_rate=100,
        distance_km=0,
        estimated_hours=1,
        platform_fee_rate=0.0,
        urgency="urgent",
        category_urgency_multiplier=1.25,
        category_night_multiplier=1.15,
        starts_at=datetime(2026, 8, 27, 23, 30),
    )
    # 200 * 1.25 * 1.15 = 287.5
    assert result["subtotal"] == 287.5


def test_negative_inputs_are_clamped_not_credited():
    result = estimate_fare(
        base_fare=100,
        per_km_rate=18,
        per_hour_rate=350,
        distance_km=-5,
        estimated_hours=-3,
        platform_fee_rate=0.15,
    )
    assert result["distance_fare"] == 0.0
    assert result["time_fare"] == 0.0


def test_payout_split_is_exact():
    split = split_payout(1000.0, 0.15)
    assert split["platform_fee"] == 150.0
    assert split["worker_payout"] == 850.0
    assert round(split["platform_fee"] + split["worker_payout"], 2) == split["total"]
