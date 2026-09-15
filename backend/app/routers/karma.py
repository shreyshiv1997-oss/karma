"""Karma ledger read endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, SessionDep
from app.models.user import KarmaEvent, KarmaEventType
from app.schemas import KarmaEventOut, KarmaLedgerOut
from app.services.karma import KarmaLedger, KarmaSnapshot, total_events

router = APIRouter(prefix="/karma", tags=["Karma"])

# One page of ledger history. `truncated` says whether an older page exists (the route reads one
# row past the page to know), and `total_events` is the true row count, so a long ledger is never
# mislabelled by its page size.
PAGE_SIZE = 50

# Neutral labels for the *public* view of somebody's ledger.
#
# The number is public by design -- "transparency is the product's whole strategy" -- but the
# `reason` column is not a number, it is prose assembled from other people's content:
# a completion reads "Completed '<gig title>' on time", and gig titles are free text full of
# street addresses and building names. A dispute or an SOS reason announces an allegation
# against the person. So the public route publishes what moved and by how much, in which
# domain, and keeps the sentences for the owner, who is the only party able to contest them.
_PUBLIC_REASON: dict[str, str] = {
    KarmaEventType.PHONE_VERIFIED.value: "Phone number verified",
    KarmaEventType.KYC_APPROVED.value: "Identity verified",
    KarmaEventType.GIG_COMPLETED.value: "Gig completed",
    KarmaEventType.REVIEW_RECEIVED.value: "Review received",
    KarmaEventType.DISPUTE_FILED.value: "Dispute recorded",
    KarmaEventType.SOS_RAISED.value: "Safety report recorded",
    KarmaEventType.PROOF_PUBLISHED.value: "Proof of work published",
    KarmaEventType.STREAK_DAY.value: "Daily streak",
    KarmaEventType.POST_REPORTED_UPHELD.value: "Report upheld",
    KarmaEventType.CASE_DISMISSED.value: "Case dismissed",
    KarmaEventType.MIGRATION_BACKFILL.value: "Imported history",
}


def _public_event(event: KarmaEvent) -> KarmaEventOut:
    """Project one ledger row for public eyes: the arithmetic, not the narrative."""
    return KarmaEventOut(
        id=event.id,
        event_type=event.event_type,
        domain=event.domain,
        delta=event.delta,
        reason=_PUBLIC_REASON.get(event.event_type, "Ledger entry"),
        created_at=event.created_at,
    )


def _ledger_out(
    snapshot: KarmaSnapshot,
    rows: list[KarmaEvent],
    total: int,
    *,
    limit: int,
    project,
) -> KarmaLedgerOut:
    # The classic over-read: ask for one more row than the page and the extra tells you whether a
    # next page exists. `len(events) == limit` would have been an approximation -- a ledger of
    # exactly `limit` events looks truncated forever -- and `total > len(events)` is simply wrong
    # once a cursor is in play, because the last page of a long ledger would still claim there is
    # more. The row count stays in `total_events` either way, which is what the UI quotes.
    shown = [project(e) for e in rows[:limit]]
    return KarmaLedgerOut(
        blended=snapshot.blended,
        work=snapshot.work,
        social=snapshot.social,
        band=snapshot.band(),
        events=shown,
        total_events=total,
        truncated=len(rows) > limit,
    )


@router.get("/ledger", response_model=KarmaLedgerOut)
async def ledger(
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=PAGE_SIZE, ge=1, le=200),
    before_id: int | None = Query(
        default=None,
        ge=1,
        description="Keyset cursor: return events older than this id. Pass the last id of the "
        "previous page. A short page is the end of the ledger.",
    ),
) -> KarmaLedgerOut:
    """The audit trail behind your karma. Nothing about this number is opaque.

    Paged, because this is the same table the public view exposes and a participant who has used
    the app for a year has more than one page of it -- without a cursor their own oldest entries
    were unreachable while a stranger reading the same ledger could be told more of it.
    """
    service = KarmaLedger(session)
    snapshot = await service.recompute(user.id)
    rows = await service.history(user.id, limit=limit + 1, before_id=before_id)
    total = await total_events(session, user.id)
    return _ledger_out(snapshot, rows, total, limit=limit, project=KarmaEventOut.model_validate)


@router.get("/ledger/{user_id}", response_model=KarmaLedgerOut)
async def public_ledger(
    user_id: int,
    session: SessionDep,
    limit: int = Query(default=PAGE_SIZE, ge=1, le=200),
    before_id: int | None = Query(
        default=None,
        ge=1,
        description="Keyset cursor: return events older than this id.",
    ),
) -> KarmaLedgerOut:
    """Public view of anyone's karma -- transparency is the product's whole strategy.

    The scores and the deltas are public; the free-text reasons are not (see
    ``_PUBLIC_REASON``). Readable without a session on purpose, so a hiring card can cite
    where a number came from.
    """
    service = KarmaLedger(session)
    snapshot = await service.recompute(user_id)
    rows = await service.history(user_id, limit=limit + 1, before_id=before_id)
    total = await total_events(session, user_id)
    return _ledger_out(snapshot, rows, total, limit=limit, project=_public_event)
