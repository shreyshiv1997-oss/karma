"""★ THE FUSION CORE — the Karma Ledger.

One append-only ledger, two domains, one number.

Every consequential action in the merged product -- a completed gig, a five-star review, a
published proof post, an approved KYC, a filed dispute -- writes a row here. ``users.karma``
is a cached projection of those rows and nothing else writes it. That single rule is what
makes "zero Frankenstein seams" an architectural fact rather than a slogan: the social half
and the marketplace half cannot disagree about who someone is, because they are reading the
same table.

Invariants (all asserted in tests/test_karma.py):
  1. Rows are append-only -- never updated, never deleted.
  2. ``recompute`` is idempotent: running it twice yields the same value.
  3. Karma is clamped to [0, 100].
  4. Every row carries its source domain, so marketplace rank can be weighted
     independently of social popularity.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import (
    KARMA_DELTAS,
    KarmaDomain,
    KarmaEvent,
    KarmaEventType,
    User,
)

KARMA_MIN, KARMA_MAX = 0, 100

# Verification tier bonus, applied on top of the base KYC delta.
TIER_BONUS: dict[str, int] = {"bronze": 0, "silver": 6, "gold": 12}

# How strongly each rating band moves karma for a received review.
RATING_WEIGHT: dict[int, float] = {1: -1.5, 2: -0.75, 3: 0.0, 4: 0.5, 5: 1.0}


@dataclass(frozen=True)
class KarmaSnapshot:
    blended: int
    work: int
    social: int

    def band(self) -> str:
        """The karma gradient from the design manifesto."""
        if self.blended >= 85:
            return "proven"
        if self.blended >= 70:
            return "trusted"
        if self.blended >= 40:
            return "building"
        return "dormant"


def compute_delta(
    event_type: KarmaEventType,
    *,
    tier: str | None = None,
    rating: int | None = None,
) -> int:
    """Pure function: event -> signed karma delta. No I/O, fully unit-testable."""
    base = KARMA_DELTAS[event_type]

    if event_type is KarmaEventType.KYC_APPROVED and tier:
        base += TIER_BONUS.get(tier, 0)

    if event_type is KarmaEventType.REVIEW_RECEIVED and rating is not None:
        weight = RATING_WEIGHT.get(max(1, min(5, rating)), 0.0)
        return int(round(base * weight))

    return base


class KarmaLedger:
    """The only code path permitted to change a user's karma."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        user_id: int,
        event_type: KarmaEventType,
        *,
        reason: str = "",
        ref_type: str | None = None,
        ref_id: int | None = None,
        tier: str | None = None,
        rating: int | None = None,
        meta: dict | None = None,
    ) -> KarmaEvent:
        """Append an event and refresh the user's cached projection.

        Deliberately does *not* commit -- the caller's transaction owns atomicity, so a
        completed gig publishes its proof post and its karma event together or not at all.
        """
        delta = compute_delta(event_type, tier=tier, rating=rating)
        domain = _domain_for(event_type)

        event = KarmaEvent(
            user_id=user_id,
            event_type=event_type.value,
            domain=domain.value,
            delta=delta,
            reason=reason or event_type.value.replace("_", " "),
            ref_type=ref_type,
            ref_id=ref_id,
            meta=meta or {},
        )
        self.session.add(event)
        await self.session.flush()

        await self._refresh(user_id)
        return event

    async def record_backfill(
        self,
        user_id: int,
        *,
        delta: int,
        domain: KarmaDomain,
        reason: str,
        meta: dict | None = None,
    ) -> KarmaEvent:
        """Append a migration backfill row carrying an explicit delta.

        Ordinary events derive their delta from ``KARMA_DELTAS``. Migration is the one
        legitimate exception: the value comes from a legacy system, not from this table,
        so it must be stated rather than looked up.

        One row per domain, because a single row cannot express two different target
        values for the work and social halves.
        """
        event = KarmaEvent(
            user_id=user_id,
            event_type=KarmaEventType.MIGRATION_BACKFILL.value,
            domain=domain.value,
            delta=delta,
            reason=reason,
            ref_type="migration",
            meta=meta or {},
        )
        self.session.add(event)
        await self.session.flush()
        await self._refresh(user_id)
        return event

    async def reverse(
        self,
        *,
        event_type: KarmaEventType,
        ref_type: str,
        ref_id: int,
        reason: str,
    ) -> KarmaEvent | None:
        """Undo a recorded penalty, exactly once, by its own amount.

        Filing a dispute (-15) or raising an SOS (-25) moves karma *immediately*, because the
        allegation has to bite before anyone can investigate it. That was only half a design: an
        admin could then dismiss the case and the number stayed broken, so an unfounded
        accusation cost a worker their standing permanently. This is the other half -- an
        append that negates the original, since history is never edited.

        The delta is copied from the row being reversed rather than looked up in
        ``KARMA_DELTAS``, so the penalty and its exoneration cannot drift apart when someone
        retunes the table. Returns ``None`` when there is nothing to reverse, and never
        re-reverses: the ledger is the source of truth, so it must not be told twice.
        """
        original = (
            await self.session.execute(
                select(KarmaEvent)
                .where(
                    KarmaEvent.event_type == event_type.value,
                    KarmaEvent.ref_type == ref_type,
                    KarmaEvent.ref_id == ref_id,
                    KarmaEvent.delta < 0,
                )
                .order_by(KarmaEvent.id.asc())
            )
        ).scalars().first()
        if original is None:
            return None

        already_reversed = await self.session.scalar(
            select(KarmaEvent.id)
            .where(
                KarmaEvent.ref_type == "karma_reversal",
                KarmaEvent.ref_id == original.id,
            )
            .limit(1)
        )
        if already_reversed is not None:
            return None

        reversal = KarmaEvent(
            user_id=original.user_id,
            event_type=KarmaEventType.CASE_DISMISSED.value,
            domain=original.domain,
            delta=-original.delta,
            reason=reason,
            ref_type="karma_reversal",
            ref_id=original.id,
            meta={"reversal_of": original.id, "reversed_delta": original.delta},
        )
        self.session.add(reversal)
        await self.session.flush()
        await self._refresh(original.user_id)
        return reversal

    async def _refresh(self, user_id: int) -> None:
        snapshot = await self.recompute(user_id)
        user = await self.session.get(User, user_id)
        if user is not None:
            user.karma = snapshot.blended
            user.karma_work = snapshot.work
            user.karma_social = snapshot.social
            # reputation_score is preserved for the matching engine's historical contract.
            user.reputation_score = float(snapshot.blended)
            # Flush so the cached projection is visible to the rest of this transaction
            # (the match ranker reads it in the same request that completes a gig).
            await self.session.flush()

    async def recompute(self, user_id: int) -> KarmaSnapshot:
        """Rebuild karma from the ledger. Idempotent by construction."""
        rows = (
            await self.session.execute(
                select(KarmaEvent.domain, KarmaEvent.delta).where(KarmaEvent.user_id == user_id)
            )
        ).all()

        work = _neutral()
        social = _neutral()
        trust_total = 0

        for domain, delta in rows:
            if domain == KarmaDomain.WORK.value:
                work += delta
            elif domain == KarmaDomain.SOCIAL.value:
                social += delta
            else:  # TRUST and MIGRATION count toward both halves
                trust_total += delta

        work_total = _clamp(work + trust_total)
        social_total = _clamp(social + trust_total)

        # Blended: work is weighted higher than social, because trusting someone in your
        # home should depend more on their work record than on their popularity.
        blended = _clamp(int(round(0.6 * work_total + 0.4 * social_total)))
        return KarmaSnapshot(blended=blended, work=work_total, social=social_total)

    async def history(
        self, user_id: int, limit: int = 50, before_id: int | None = None
    ) -> list[KarmaEvent]:
        # Keyset paging, for the reason the feed has it (see feed.list_posts): a ledger is being
        # appended to while somebody reads it, and OFFSET would hand them the same row twice or skip
        # one. Ids are assigned in insert order, so `id <` agrees with `created_at DESC`, and the
        # `id DESC` tiebreaker keeps same-instant rows in a stable order.
        stmt = (
            select(KarmaEvent)
            .where(KarmaEvent.user_id == user_id)
            .order_by(KarmaEvent.created_at.desc(), KarmaEvent.id.desc())
            .limit(limit)
        )
        if before_id is not None:
            stmt = stmt.where(KarmaEvent.id < before_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)


def _neutral() -> int:
    return settings.KARMA_START


def _clamp(value: int) -> int:
    return max(KARMA_MIN, min(KARMA_MAX, value))


_EVENT_DOMAINS: dict[KarmaEventType, KarmaDomain] = {
    KarmaEventType.PHONE_VERIFIED: KarmaDomain.TRUST,
    KarmaEventType.KYC_APPROVED: KarmaDomain.TRUST,
    KarmaEventType.GIG_COMPLETED: KarmaDomain.WORK,
    KarmaEventType.REVIEW_RECEIVED: KarmaDomain.WORK,
    KarmaEventType.DISPUTE_FILED: KarmaDomain.WORK,
    KarmaEventType.SOS_RAISED: KarmaDomain.WORK,
    KarmaEventType.PROOF_PUBLISHED: KarmaDomain.SOCIAL,
    KarmaEventType.STREAK_DAY: KarmaDomain.SOCIAL,
    KarmaEventType.POST_REPORTED_UPHELD: KarmaDomain.SOCIAL,
    # Only consulted by `record()`; `reverse()` takes the domain from the row it undoes so a
    # reversal always lands on the same half of the number as the penalty did.
    KarmaEventType.CASE_DISMISSED: KarmaDomain.WORK,
    KarmaEventType.MIGRATION_BACKFILL: KarmaDomain.MIGRATION,
}


def _domain_for(event_type: KarmaEventType) -> KarmaDomain:
    return _EVENT_DOMAINS[event_type]


async def total_events(session: AsyncSession, user_id: int) -> int:
    """Audit helper: how many rows the ledger holds for a user."""
    return int(
        await session.scalar(
            select(func.count()).select_from(KarmaEvent).where(KarmaEvent.user_id == user_id)
        )
        or 0
    )
