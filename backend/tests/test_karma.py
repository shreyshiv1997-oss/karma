"""★ Karma Ledger invariants — the fusion core.

If these fail, the two halves of the product can disagree about who a user is, and the
merge is cosmetic rather than real.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.user import KarmaDomain, KarmaEvent, KarmaEventType, User
from app.services.karma import KarmaLedger, compute_delta


@pytest.fixture
async def user(db):
    u = User(handle="ledgeruser", display_name="Ledger User", email="l@example.com")
    db.add(u)
    await db.flush()
    return u


@pytest.mark.asyncio
async def test_starts_at_neutral(db, user):
    snapshot = await KarmaLedger(db).recompute(user.id)
    assert snapshot.blended == settings.KARMA_START
    assert snapshot.work == settings.KARMA_START
    assert snapshot.social == settings.KARMA_START


@pytest.mark.asyncio
async def test_recompute_is_idempotent(db, user):
    """Running recompute twice must not change the number."""
    ledger = KarmaLedger(db)
    await ledger.record(user.id, KarmaEventType.GIG_COMPLETED, reason="job done")

    first = await ledger.recompute(user.id)
    second = await ledger.recompute(user.id)
    third = await ledger.recompute(user.id)
    assert first == second == third


@pytest.mark.asyncio
async def test_ledger_is_append_only(db, user):
    """Events accumulate; recording more never removes rows."""
    ledger = KarmaLedger(db)
    await ledger.record(user.id, KarmaEventType.GIG_COMPLETED)
    await ledger.record(user.id, KarmaEventType.PROOF_PUBLISHED)
    await ledger.record(user.id, KarmaEventType.REVIEW_RECEIVED, rating=5)

    rows = (
        await db.execute(select(func.count()).select_from(KarmaEvent).where(KarmaEvent.user_id == user.id))
    ).scalar()
    assert rows == 3


@pytest.mark.asyncio
async def test_karma_floors_at_zero(db, user):
    """The ledger is cumulative and append-only: penalties cannot be 'undone' by
    piling on positives, so the floor is what protects the number."""
    ledger = KarmaLedger(db)
    for _ in range(20):
        await ledger.record(user.id, KarmaEventType.SOS_RAISED)
    low = await ledger.recompute(user.id)
    # Work karma floors at 0. Social is untouched by work events, so the blended
    # figure sits at 0.6*0 + 0.4*50 = 20 rather than 0 -- by design, not by accident.
    assert low.work == 0
    assert low.social == settings.KARMA_START
    assert low.blended == 20


@pytest.mark.asyncio
async def test_karma_caps_at_one_hundred(db):
    """A separate user, so the ceiling is what is under test."""
    u = User(handle="highflyer", display_name="High Flyer", email="hf@example.com")
    db.add(u)
    await db.flush()

    ledger = KarmaLedger(db)
    for _ in range(80):
        await ledger.record(u.id, KarmaEventType.GIG_COMPLETED)
    high = await ledger.recompute(u.id)
    assert high.work == 100
    assert high.social == settings.KARMA_START
    assert high.blended == 80, "0.6*100 + 0.4*50"



@pytest.mark.asyncio
async def test_every_event_carries_its_domain(db, user):
    """Domain tagging is what stops social karma from being spent as work trust."""
    ledger = KarmaLedger(db)
    await ledger.record(user.id, KarmaEventType.GIG_COMPLETED)
    await ledger.record(user.id, KarmaEventType.PROOF_PUBLISHED)
    await ledger.record(user.id, KarmaEventType.KYC_APPROVED, tier="gold")

    domains = set(
        (await db.execute(select(KarmaEvent.domain).where(KarmaEvent.user_id == user.id)))
        .scalars()
        .all()
    )
    assert KarmaDomain.WORK.value in domains
    assert KarmaDomain.SOCIAL.value in domains
    assert KarmaDomain.TRUST.value in domains


@pytest.mark.asyncio
async def test_social_popularity_does_not_inflate_work_karma(db, user):
    """★ The gaming mitigation.

    Farming social events must raise social karma but must NOT raise work karma, because
    the match ranker reads work karma.
    """
    ledger = KarmaLedger(db)
    before = await ledger.recompute(user.id)

    for _ in range(10):
        await ledger.record(user.id, KarmaEventType.PROOF_PUBLISHED)

    after = await ledger.recompute(user.id)
    assert after.social > before.social, "social karma should rise"
    assert after.work == before.work, "work karma must be untouched by social events"


@pytest.mark.asyncio
async def test_work_events_do_not_inflate_social_karma(db, user):
    ledger = KarmaLedger(db)
    before = await ledger.recompute(user.id)
    for _ in range(5):
        await ledger.record(user.id, KarmaEventType.GIG_COMPLETED)
    after = await ledger.recompute(user.id)
    assert after.work > before.work
    assert after.social == before.social


@pytest.mark.asyncio
async def test_record_updates_cached_projection(db, user):
    """users.karma must always equal the ledger sum."""
    ledger = KarmaLedger(db)
    await ledger.record(user.id, KarmaEventType.GIG_COMPLETED)
    await db.refresh(user)
    snapshot = await ledger.recompute(user.id)
    assert user.karma == snapshot.blended
    assert user.karma_work == snapshot.work
    assert user.karma_social == snapshot.social


@pytest.mark.asyncio
async def test_low_rating_penalises(db, user):
    ledger = KarmaLedger(db)
    before = await ledger.recompute(user.id)
    await ledger.record(user.id, KarmaEventType.REVIEW_RECEIVED, rating=1)
    after = await ledger.recompute(user.id)
    assert after.work < before.work


# --- pure function -------------------------------------------------------
@pytest.mark.parametrize(
    "event,kwargs,expected",
    [
        (KarmaEventType.GIG_COMPLETED, {}, 3),
        (KarmaEventType.PHONE_VERIFIED, {}, 5),
        (KarmaEventType.KYC_APPROVED, {"tier": "bronze"}, 8),
        (KarmaEventType.KYC_APPROVED, {"tier": "silver"}, 14),
        (KarmaEventType.KYC_APPROVED, {"tier": "gold"}, 20),
        (KarmaEventType.DISPUTE_FILED, {}, -15),
        (KarmaEventType.SOS_RAISED, {}, -25),
        (KarmaEventType.PROOF_PUBLISHED, {}, 2),
        (KarmaEventType.REVIEW_RECEIVED, {"rating": 5}, 4),
        (KarmaEventType.REVIEW_RECEIVED, {"rating": 3}, 0),
        (KarmaEventType.REVIEW_RECEIVED, {"rating": 1}, -6),
    ],
)
def test_compute_delta_table(event, kwargs, expected):
    assert compute_delta(event, **kwargs) == expected


def test_bands_from_manifesto():
    from app.services.karma import KarmaSnapshot

    assert KarmaSnapshot(95, 95, 95).band() == "proven"
    assert KarmaSnapshot(75, 75, 75).band() == "trusted"
    assert KarmaSnapshot(50, 50, 50).band() == "building"
    assert KarmaSnapshot(10, 10, 10).band() == "dormant"


@pytest.mark.asyncio
async def test_recompute_agrees_with_a_python_row_sum_over_every_domain(db, user):
    """The database conditional aggregation must be exactly the old row loop.

    `recompute` no longer fetches the rows into Python, so pin the arithmetic with an
    independent Python sum over a seeded, unseeded-random mix of all four domains and
    wildly varying (including negative and clamping) deltas.
    """
    import random

    from app.services.karma import _clamp, _neutral

    random.seed(20260916)
    deltas_by_domain: dict[str, int] = {}
    for i in range(120):
        domain = random.choice(
            [
                KarmaDomain.WORK,
                KarmaDomain.SOCIAL,
                KarmaDomain.TRUST,
                KarmaDomain.MIGRATION,
            ]
        ).value
        delta = random.randint(-30, 35)
        db.add(
            KarmaEvent(
                user_id=user.id,
                event_type=KarmaEventType.STREAK_DAY.value,
                domain=domain,
                delta=delta,
                reason="equivalence probe",
                ref_type="test",
                ref_id=i,
            )
        )
        deltas_by_domain[domain] = deltas_by_domain.get(domain, 0) + delta
    await db.flush()

    snapshot = await KarmaLedger(db).recompute(user.id)

    # The original algorithm, run here by hand over the raw rows:
    neutral = _neutral()
    trust_total = deltas_by_domain.get(KarmaDomain.TRUST.value, 0) + deltas_by_domain.get(
        KarmaDomain.MIGRATION.value, 0
    )
    work_total = _clamp(neutral + deltas_by_domain.get(KarmaDomain.WORK.value, 0) + trust_total)
    social_total = _clamp(
        neutral + deltas_by_domain.get(KarmaDomain.SOCIAL.value, 0) + trust_total
    )
    blended = _clamp(int(round(0.6 * work_total + 0.4 * social_total)))
    assert (snapshot.blended, snapshot.work, snapshot.social) == (
        blended,
        work_total,
        social_total,
    )
