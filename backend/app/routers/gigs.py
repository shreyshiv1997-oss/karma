# FIXED: can_work cannot be self-granted / wallet ledger updates must be atomic — a
# customer can no longer hire, complete, review or pay themselves, an assignee must
# actually hold can_work, and the payout is a single atomic UPDATE.
"""★ Gigs — where the two products become one.

The fusion seam is ``complete_gig``. When a gig reaches ``completed``:
  1. a **proof post** is published to the worker's profile and their followers' feeds,
  2. a ``GIG_COMPLETED`` karma event is appended to the ledger,
  3. the worker's marketplace stats are updated,
  4. the wallet ledger records the payout and the platform fee.

All four happen inside the caller's transaction, so they succeed together or not at all.
If the two halves of this product were merely co-located rather than merged, step 1 could
not exist -- there would be no audience to publish to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, func, Numeric, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep, require_capability
from app.core.ports import HaversineGeo, PostgisGeo
from app.models.marketplace import (
    GIG_TRANSITIONS,
    Gig,
    ServiceCategory,
    WorkerProfile,
)
from app.models.social import Post, PostKind
from app.models.trust import LedgerEntry, Review, Wallet
from app.models.user import KarmaEventType, User
from app.routers.media import validate_media_references
from app.schemas import (
    EstimateRequest,
    GigCreate,
    GigOut,
    GigStatusUpdate,
    ReviewCreate,
    ReviewOut,
)
from app.services.fare import custom_price_breakdown, estimate_fare, is_custom_priced, split_payout
from app.services.karma import KarmaLedger
from app.services.payment_workflows import cancel_gig_authorization, lock_payment
from app.services.payments import PaymentGateway, get_payment_gateway
from app.services.realtime import Event, queue_event

router = APIRouter(prefix="/gigs", tags=["Gigs"])


def _geo():
    return PostgisGeo() if settings.use_postgis else HaversineGeo()


async def _get_gig(session, gig_id: int, *, for_update: bool = False) -> Gig:
    gig = (
        await session.scalar(select(Gig).where(Gig.id == gig_id).with_for_update())
        if for_update
        else await session.get(Gig, gig_id)
    )
    if gig is None:
        raise HTTPException(status_code=404, detail="Gig not found")
    return gig


# --------------------------------------------------------------------------
# pricing
# --------------------------------------------------------------------------
@router.post("/estimate")
async def estimate(payload: EstimateRequest, session: SessionDep) -> dict:
    """Transparent pre-booking estimate. Every multiplier is returned."""
    category = await session.get(ServiceCategory, payload.category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    # A poster who names their own price gets the platform fee on top of exactly that
    # number -- the same contract POST /gigs will honour when it stores the gig.
    if payload.custom_price is not None:
        return custom_price_breakdown(
            custom_price=payload.custom_price,
            platform_fee_rate=settings.PLATFORM_FEE_RATE,
        )

    return estimate_fare(
        base_fare=float(category.base_fare),
        per_km_rate=float(category.per_km_rate),
        per_hour_rate=float(category.per_hour_rate),
        distance_km=0.0,  # unknown until a worker is matched
        estimated_hours=payload.estimated_hours,
        platform_fee_rate=settings.PLATFORM_FEE_RATE,
        urgency=payload.urgency,
        skill_tier=payload.skill_tier,
        category_urgency_multiplier=float(category.urgency_multiplier),
        category_night_multiplier=float(category.night_multiplier),
        starts_at=payload.starts_at,
    )


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------
@router.post("", response_model=GigOut, status_code=201)
async def create_gig(
    payload: GigCreate,
    session: SessionDep,
    user: Annotated[User, require_capability("can_hire")],
) -> GigOut:
    category = await session.get(ServiceCategory, payload.category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    photos = await validate_media_references(
        session,
        owner_id=user.id,
        references=payload.photos,
        purposes={"gig"},
    )

    # The poster names the price or lets the marketplace compute one. A poster-set price
    # is stored verbatim (fee on top) and, unlike an estimated one, is never recomputed
    # at assignment -- the worker's tier and distance cannot re-price a number the
    # customer already agreed with themselves.
    if payload.custom_price is not None:
        breakdown = custom_price_breakdown(
            custom_price=payload.custom_price,
            platform_fee_rate=settings.PLATFORM_FEE_RATE,
        )
    else:
        breakdown = estimate_fare(
            base_fare=float(category.base_fare),
            per_km_rate=float(category.per_km_rate),
            per_hour_rate=float(category.per_hour_rate),
            distance_km=0.0,
            estimated_hours=payload.estimated_hours,
            platform_fee_rate=settings.PLATFORM_FEE_RATE,
            urgency=payload.urgency,
            category_urgency_multiplier=float(category.urgency_multiplier),
            category_night_multiplier=float(category.night_multiplier),
            starts_at=payload.preferred_start_at,
        )

    gig = Gig(
        customer_id=user.id,
        category_id=payload.category_id,
        title=payload.title,
        description=payload.description,
        urgency=payload.urgency,
        lat=payload.lat,
        lng=payload.lng,
        address_label=payload.address_label,
        location_source=payload.location_source,
        location_accuracy_m=payload.location_accuracy_m,
        geocoder=payload.geocoder,
        fare_breakdown=breakdown,
        total=Decimal(str(breakdown["total"])),
        estimated_hours=payload.estimated_hours,
        photos=photos,
        preferred_start_at=payload.preferred_start_at,
    )
    session.add(gig)
    await session.flush()
    return GigOut.model_validate(gig)


@router.get("/mine", response_model=list[GigOut])
async def my_gigs(
    session: SessionDep,
    user: CurrentUser,
    role: str = Query(default="customer", pattern="^(customer|worker)$"),
) -> list[GigOut]:
    column = Gig.customer_id if role == "customer" else Gig.worker_id
    rows = (
        await session.execute(
            select(Gig).where(column == user.id).order_by(Gig.created_at.desc()).limit(50)
        )
    ).scalars().all()
    return [GigOut.model_validate(g) for g in rows]


@router.get("/{gig_id}", response_model=GigOut)
async def get_gig(gig_id: int, session: SessionDep, user: CurrentUser) -> GigOut:
    gig = await _get_gig(session, gig_id)
    if user.id not in {gig.customer_id, gig.worker_id} and "admin" not in set(
        user.capabilities or []
    ):
        raise HTTPException(status_code=403, detail="Not your gig")
    return GigOut.model_validate(gig)


@router.post("/{gig_id}/assign", response_model=GigOut)
async def assign_worker(
    gig_id: int, worker_id: int, user: CurrentUser, session: SessionDep
) -> GigOut:
    gig = await _get_gig(session, gig_id, for_update=True)
    if gig.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Only the customer can assign")
    if gig.status != "searching":
        raise HTTPException(status_code=409, detail=f"Gig is already {gig.status}")

    # A gig is a transaction between two parties. If they are the same account it is not
    # work, it is a self-issued payout: the completion path credits the wallet, appends
    # GIG_COMPLETED + PROOF_PUBLISHED karma, and then the same person can post a 5-star
    # review of themselves. Karma and money are both mintable in a loop without it.
    if worker_id == gig.customer_id:
        raise HTTPException(
            status_code=400, detail="You cannot assign yourself to your own gig"
        )

    worker = await session.get(WorkerProfile, worker_id)
    if worker is None or not worker.is_available or worker.approved_at is None:
        raise HTTPException(status_code=400, detail="Worker is not available")
    if worker.category_id != gig.category_id:
        raise HTTPException(status_code=400, detail="Worker does not serve this category")

    # The WorkerProfile row is history; `can_work` is the live permission, and it is the
    # capability KYC actually grants. Checking only `approved_at` meant a worker whose
    # capability had been revoked -- KYC withdrawn, safety hold -- stayed assignable
    # because their old profile row was still sitting there marked available.
    worker_user = await session.get(User, worker_id)
    if worker_user is None or worker_user.is_suspended:
        raise HTTPException(status_code=400, detail="Worker is not available")
    if "can_work" not in set(worker_user.capabilities or []):
        raise HTTPException(
            status_code=400, detail="Worker is not approved to take work"
        )

    gig.worker_id = worker_id
    gig.status = "assigned"
    # The amount is fixed below, then the customer authorizes it through PaymentSheet.
    # Work cannot begin until Stripe reports ``requires_capture``.
    gig.payment_status = "requires_payment"
    gig.accepted_at = datetime.now(UTC)

    # Recompute the fare now that we know the worker's distance and tier -- unless the
    # poster set the price themselves. A poster-set price is a promise made at posting
    # time: recomputing it here would let the worker's tier or a location fix change
    # what the customer is about to authorize after they have already read the number.
    if not is_custom_priced(gig.fare_breakdown):
        category = await session.get(ServiceCategory, gig.category_id)
        from app.core.ports import haversine_km

        distance = 0.0
        if worker.lat is not None and worker.lng is not None:
            distance = haversine_km(gig.lat, gig.lng, worker.lat, worker.lng)

        breakdown = estimate_fare(
            base_fare=float(category.base_fare),
            per_km_rate=float(category.per_km_rate),
            per_hour_rate=float(category.per_hour_rate),
            distance_km=distance,
            estimated_hours=max(0.25, float(gig.estimated_hours or 2.0)),
            platform_fee_rate=settings.PLATFORM_FEE_RATE,
            urgency=gig.urgency,
            skill_tier=worker.verification_tier,
            category_urgency_multiplier=float(category.urgency_multiplier),
            category_night_multiplier=float(category.night_multiplier),
            starts_at=gig.preferred_start_at,
        )
        gig.fare_breakdown = breakdown
        gig.total = Decimal(str(breakdown["total"]))
    await session.flush()

    queue_event(
        session,
        Event.of(
            "gig.assigned",
            gig.id,
            status="assigned",
            worker_id=worker_id,
            total=float(gig.total),
        ),
    )
    return GigOut.model_validate(gig)


@router.post("/{gig_id}/status", response_model=GigOut)
async def update_status(
    gig_id: int,
    payload: GigStatusUpdate,
    user: CurrentUser,
    session: SessionDep,
    gateway: Annotated[PaymentGateway, Depends(get_payment_gateway)],
) -> GigOut:
    gig = await _get_gig(session, gig_id, for_update=True)

    # `assigned` is not an editable status, it is the *outcome* of hiring. Only
    # POST /gigs/{id}/assign may enter it, because that is where the worker is chosen, the
    # fare is recomputed from the worker's distance and tier, and the payment authorization is
    # opened. Accepting it here let a customer jump searching -> assigned with `worker_id`
    # still NULL -- and that gig was then unrecoverable: /assign refuses a non-searching gig,
    # /payments refuses a gig with no worker, and every worker transition is 403 because
    # there is no assigned worker to authorise them. Cancellation was the only way out.
    if payload.status == "assigned":
        raise HTTPException(
            status_code=409,
            detail=f"Assigning a worker is not a status edit; use POST /gigs/{gig_id}/assign.",
        )

    # Authorisation BEFORE state validation. Checking the transition first would return
    # 409 to someone with no right to act on this gig, leaking its current state to them.
    # Check *who* before *what*.
    worker_moves = {
        "en_route",
        "arrived",
        "in_progress",
        "completion_pending",
        "completed",  # invalid as a direct move, but still worker-authorized before state checks
    }
    if payload.status in worker_moves and gig.worker_id != user.id:
        raise HTTPException(status_code=403, detail="Only the assigned worker can do that")
    if payload.status == "cancelled" and user.id not in {gig.customer_id, gig.worker_id}:
        raise HTTPException(status_code=403, detail="Not your gig")

    allowed = GIG_TRANSITIONS.get(gig.status, set())
    if payload.status not in allowed:
        raise HTTPException(
            status_code=409, detail=f"Cannot move from '{gig.status}' to '{payload.status}'"
        )

    if payload.status == "en_route":
        payment = await lock_payment(session, gig.id)
        if payment is None or payment.status not in {"authorized", "captured"}:
            raise HTTPException(
                status_code=409,
                detail="The customer must authorize the secured payment before work begins",
            )

    now = datetime.now(UTC)
    previous = gig.status
    if payload.status == "en_route" and gig.started_at is None:
        gig.started_at = now
    if payload.status == "completion_pending":
        # Persist proof before any capture. The customer's separate release request can now be
        # retried safely, and a delayed signed webhook has enough durable state to reconcile.
        if payload.proof_photos:
            if len(payload.proof_photos) != 2:
                raise HTTPException(
                    status_code=422,
                    detail="Completion proof must contain one before and one after image",
                )
            gig.proof_photos = await validate_media_references(
                session,
                owner_id=user.id,
                references=payload.proof_photos,
                purpose_sequence=["proof_before", "proof_after"],
            )
        # Assign only what was actually sent, the same guard `_complete_gig` uses below. Writing
        # the validated-but-empty list unconditionally is harmless while `completion_pending` is
        # terminal -- the transition table refuses to re-enter it, so there is nothing yet to
        # overwrite -- and quietly destructive the moment anyone allows a resubmission while a
        # customer sits on the approval: the retry a dropped connection invites would arrive
        # photo-less, erase the evidence, and publish a "proof" post with no proof in it.
        #
        # What this does NOT do is require images. Proof is optional on completion today, so a
        # customer who never releases the payment can be shown an empty "proof" post; closing
        # that means changing what every photo-less status loop in the suite is asserting, which
        # is a product decision about what completion proves, not a bug fix.
    elif payload.status == "cancelled":
        try:
            await cancel_gig_authorization(session, gig, gateway)
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(
                status_code=502,
                detail="The payment authorization could not be cancelled; gig unchanged",
            ) from exc
        gig.completed_at = now
    gig.status = payload.status

    await session.flush()

    # Queued, not published: the session dependency flushes this only if the commit below
    # succeeds. A transition that rolls back is never announced.
    queue_event(
        session,
        Event.of(
            "gig.status_changed",
            gig.id,
            status=payload.status,
            previous=previous,
            payment_status=gig.payment_status,
            actor=user.id,
        ),
    )
    return GigOut.model_validate(gig)


async def _credit_wallet(session, user_id: int, amount: Decimal) -> None:
    """Credit a wallet with a single atomic UPDATE.

    The previous code was a read-modify-write::

        wallet.balance = Decimal(str(wallet.balance)) + payout

    which loses money under concurrency. Two gigs completing for the same worker at the
    same instant both read the old balance and both write ``old + their own payout``:
    whichever commits second overwrites the first, and one payout vanishes with no error
    anywhere. The LedgerEntry rows still record both, so the wallet silently stops
    agreeing with its own ledger -- exactly the drift the append-only design exists to
    prevent.

    ``balance = balance + :amount`` is evaluated by the database inside the row lock the
    UPDATE already takes, so concurrent credits serialise and compose.
    """
    result = await session.execute(
        update(Wallet)
        .where(Wallet.user_id == user_id)
        .values(
            balance=Wallet.balance + amount,
            lifetime_earned=Wallet.lifetime_earned + amount,
        )
    )
    if result.rowcount == 0:
        # First payout for this worker: no wallet row yet. Create it already carrying the
        # amount rather than creating-then-incrementing, so there is still exactly one
        # write.
        #
        # The insert runs inside a SAVEPOINT. A concurrent creator can win the primary-key
        # race, and the resulting IntegrityError must roll back *only this insert* -- a
        # plain session.rollback() here would discard the caller's entire transaction,
        # taking the gig completion, the karma events and the proof post with it.
        try:
            async with session.begin_nested():
                session.add(
                    Wallet(user_id=user_id, balance=amount, lifetime_earned=amount)
                )
        except IntegrityError:
            # The other writer created the row; fold this payout into theirs.
            await session.execute(
                update(Wallet)
                .where(Wallet.user_id == user_id)
                .values(
                    balance=Wallet.balance + amount,
                    lifetime_earned=Wallet.lifetime_earned + amount,
                )
            )

    # The ORM may hold a stale copy from earlier in this transaction; drop it so any later
    # read in the same request sees the value the database now holds.
    stale = await session.get(Wallet, user_id)
    if stale is not None:
        await session.refresh(stale)


async def _complete_gig(
    gig: Gig,
    proof_photos: list[str],
    session,
    *,
    payment_reference: str,
) -> None:
    """THE FUSION SEAM, entered only after provider-confirmed capture."""
    if not payment_reference:
        raise HTTPException(status_code=409, detail="Captured payment reference required")
    now = datetime.now(UTC)
    gig.status = "completed"
    gig.completed_at = now
    gig.payment_status = "paid"
    if proof_photos:
        gig.proof_photos = proof_photos

    worker = await session.get(User, gig.worker_id)
    profile = await session.get(WorkerProfile, gig.worker_id)
    category = await session.get(ServiceCategory, gig.category_id)
    total = float(gig.total)

    # (1) marketplace stats
    if profile is not None:
        profile.total_jobs = (profile.total_jobs or 0) + 1

    # (2) money: payout minus platform fee, in one append-only ledger
    split = split_payout(total, settings.PLATFORM_FEE_RATE)
    payout = Decimal(str(split["worker_payout"]))
    await _credit_wallet(session, gig.worker_id, payout)
    session.add(
        LedgerEntry(
            user_id=gig.worker_id,
            entry_type="payout",
            amount=Decimal(str(split["worker_payout"])),
            gig_id=gig.id,
            external_reference=f"stripe:{payment_reference}:worker_payout",
            note=f"Captured payout for gig #{gig.id}",
        )
    )
    session.add(
        LedgerEntry(
            user_id=gig.customer_id,
            entry_type="fee",
            amount=Decimal(str(split["platform_fee"])),
            gig_id=gig.id,
            external_reference=f"stripe:{payment_reference}:platform_fee",
            note=f"Captured platform fee for gig #{gig.id}",
        )
    )

    # (3) THE PROOF POST -- a completed, paid gig becomes social content, automatically.
    # Assert the precondition rather than assume it. This function is the only writer of
    # kind="proof", so this is the line that makes "proof posts are unfakeable" true; the
    # matching CHECK constraint in models/social.py enforces the other half at the schema
    # level, for any writer that is not this one.
    if gig.payment_status != "paid" or gig.id is None:
        raise HTTPException(
            status_code=409,
            detail="A proof post requires a paid gig",
        )
    before = proof_photos[0] if proof_photos else None
    after = proof_photos[1] if len(proof_photos) > 1 else (proof_photos[0] if proof_photos else None)
    proof = Post(
        author_id=gig.worker_id,
        kind=PostKind.PROOF.value,
        body=gig.title,
        media_urls=proof_photos,
        hashtags=[category.slug] if category else [],
        gig_id=gig.id,
        before_url=before,
        after_url=after,
        category_name=category.name if category else None,
        amount_earned=split["worker_payout"],
    )
    session.add(proof)
    await session.flush()
    if worker is not None:
        # Counted in SQL, for the same reason the wallet and the like counter are: a
        # read-modify-write here races a second completion (or the worker's own
        # POST /feed/posts) and silently drops one of the two increments.
        await session.execute(
            update(User).where(User.id == worker.id).values(posts_count=User.posts_count + 1)
        )
        await session.refresh(worker)

    # (4) karma -- one ledger, both domains update from this single event
    ledger = KarmaLedger(session)
    await ledger.record(
        gig.worker_id,
        KarmaEventType.GIG_COMPLETED,
        reason=f"Completed '{gig.title}' on time",
        ref_type="gig",
        ref_id=gig.id,
        meta={"amount": split["worker_payout"]},
    )
    await ledger.record(
        gig.worker_id,
        KarmaEventType.PROOF_PUBLISHED,
        reason="Published proof of work",
        ref_type="post",
        ref_id=proof.id,
    )


# --------------------------------------------------------------------------
# reviews -- the second half of the seam
# --------------------------------------------------------------------------
@router.post("/{gig_id}/review", response_model=ReviewOut, status_code=201)
async def review_gig(
    gig_id: int, payload: ReviewCreate, user: CurrentUser, session: SessionDep
) -> ReviewOut:
    gig = await _get_gig(session, gig_id, for_update=True)
    if gig.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Only the customer can review")
    if gig.status != "completed":
        raise HTTPException(status_code=409, detail="Gig must be completed first")
    # Defence in depth: assignment already refuses a self-assigned gig, but a review is
    # what moves work karma and the public rating, so it refuses independently. A rating
    # you awarded yourself is not evidence of anything.
    if gig.worker_id is None or gig.worker_id == user.id:
        raise HTTPException(status_code=403, detail="You cannot review your own work")

    already = await session.scalar(select(Review).where(Review.gig_id == gig_id))
    if already is not None:
        raise HTTPException(status_code=409, detail="This gig has already been reviewed")

    review = Review(
        gig_id=gig_id,
        reviewer_id=user.id,
        reviewee_id=gig.worker_id,
        rating=payload.rating,
        punctuality=payload.punctuality,
        quality=payload.quality,
        communication=payload.communication,
        comment=payload.comment,
    )
    session.add(review)
    await session.flush()

    # Update the worker's rolling rating, in one statement.
    #
    # The gig row is locked above, which is what makes "this gig has already been reviewed" hold,
    # but that lock is on the *gig* while the rating lives on the *worker*: two customers reviewing
    # two different gigs of the same worker in the same breath both read (rating, rating_count), and
    # the slower write discards the faster one -- a lost rating and a count that no longer matches
    # the rows in the table. This is the wallet's bug and the wallet's fix. `round` is applied to a
    # numeric cast because PostgreSQL has no two-argument round() for float8.
    profile = await session.get(WorkerProfile, gig.worker_id)
    if profile is not None:
        prior = func.coalesce(WorkerProfile.rating_count, 0)
        await session.execute(
            update(WorkerProfile)
            .where(WorkerProfile.user_id == gig.worker_id)
            .values(
                rating_count=prior + 1,
                # Both sides of the division are cast before it happens: `float / int` would be
                # integer division in PostgreSQL if the profile had no rating yet.
                rating=func.round(
                    cast(
                        func.coalesce(WorkerProfile.rating, 0) * prior + payload.rating,
                        Numeric,
                    )
                    / cast(prior + 1, Numeric),
                    2,
                ),
            )
        )
        await session.refresh(profile)

    # Karma: the same review moves the marketplace half AND the blended number.
    await KarmaLedger(session).record(
        gig.worker_id,
        KarmaEventType.REVIEW_RECEIVED,
        reason=f"{payload.rating}-star review received",
        ref_type="review",
        ref_id=review.id,
        rating=payload.rating,
    )

    queue_event(
        session,
        Event.of(
            "gig.reviewed",
            gig_id,
            rating=payload.rating,
            reviewer_id=user.id,
            reviewee_id=gig.worker_id,
        ),
    )
    return ReviewOut.model_validate(review)


@router.get("/{gig_id}/reviews", response_model=list[ReviewOut])
async def gig_reviews(gig_id: int, session: SessionDep, user: CurrentUser) -> list[ReviewOut]:
    """The reviews on one gig, for the two people who wrote them (and for admin).

    Every other gig read requires authentication, and this one used to require nothing --
    gig ids are sequential, so the internet could page through them and read each party's
    comment about the other. What stays public by design is the worker's *aggregate* rating
    and count, on the hiring-facing profile in the matching router.
    """
    gig = await _get_gig(session, gig_id)
    if user.id not in {gig.customer_id, gig.worker_id} and "admin" not in set(
        user.capabilities or []
    ):
        raise HTTPException(status_code=403, detail="Not your gig")

    rows = (
        await session.execute(select(Review).where(Review.gig_id == gig_id))
    ).scalars().all()
    return [ReviewOut.model_validate(r) for r in rows]


@router.get("/stats/summary")
async def summary(session: SessionDep, user: CurrentUser) -> dict:
    """Headline numbers for the dashboard."""
    total = await session.scalar(select(func.count()).select_from(Gig)) or 0
    completed = (
        await session.scalar(
            select(func.count()).select_from(Gig).where(Gig.status == "completed")
        )
        or 0
    )
    wallet = await session.get(Wallet, user.id)
    return {
        "gigs_total": int(total),
        "gigs_completed": int(completed),
        "wallet_balance": float(wallet.balance) if wallet else 0.0,
        "lifetime_earned": float(wallet.lifetime_earned) if wallet else 0.0,
    }
