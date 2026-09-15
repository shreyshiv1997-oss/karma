# FIXED: Nothing writes users.karma except the KarmaLedger._refresh path — a KYC
# submission can now be decided exactly once, so re-approval cannot ratchet karma.
"""Trust, verification and safety.

Carried from Labour Link essentially intact. Per the merge risk assessment these endpoints
cannot be feature-flagged off: they are the reason a stranger may be let into a home.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.core.ports import build_cache
from app.models.marketplace import Gig, ServiceCategory, WorkerProfile
from app.models.social import Post
from app.models.trust import (
    Dispute,
    OPEN_DISPUTE_STATUSES,
    SafetyIncident,
    TrustedContact,
    VerificationSubmission,
)
from app.models.user import KarmaEvent, KarmaEventType, User
from app.schemas import (
    EmergencyRequest,
    Message,
    TrustedContactCreate,
    TrustedContactOut,
    VerificationCreate,
    VerificationOut,
)
from app.schemas.media import WorkerLocationUpdate
from app.services.karma import KarmaLedger

router = APIRouter(tags=["Trust & Safety"])
_cache = build_cache()

MAX_TRUSTED_CONTACTS = 3


# --------------------------------------------------------------------------
# verification / KYC
# --------------------------------------------------------------------------
@router.post("/verification/submit", response_model=VerificationOut, status_code=201)
async def submit_verification(
    payload: VerificationCreate, user: CurrentUser, session: SessionDep
) -> VerificationOut:
    """Submit a document reference for review.

    Only a masked reference is stored -- never the document number itself.

    One submission may be in flight per account. Without this a user could queue any number
    of copies of the same document, and each one an admin approved paid the KYC credit again:
    the review guard is per submission, so the ledger was told the same fact N times and the
    append-only design has no way to take it back.
    """
    in_flight = await session.scalar(
        select(VerificationSubmission.id)
        .where(
            VerificationSubmission.user_id == user.id,
            VerificationSubmission.status == "pending",
        )
        .limit(1)
    )
    if in_flight is not None:
        raise HTTPException(
            status_code=409,
            detail="A submission is already with the review team; it must be decided first.",
        )

    row = VerificationSubmission(
        user_id=user.id,
        document_type=payload.document_type,
        document_ref=_mask(payload.document_ref),
        status="pending",
    )
    session.add(row)
    await session.flush()
    return VerificationOut.model_validate(row)


def _mask(ref: str) -> str:
    """Keep only the last four characters of any document reference."""
    ref = ref.strip()
    return f"XXXX{ref[-4:]}" if len(ref) > 4 else "XXXX"


@router.get("/verification/me", response_model=list[VerificationOut])
async def my_verifications(user: CurrentUser, session: SessionDep) -> list[VerificationOut]:
    rows = (
        await session.execute(
            select(VerificationSubmission)
            .where(VerificationSubmission.user_id == user.id)
            .order_by(VerificationSubmission.created_at.desc())
        )
    ).scalars().all()
    return [VerificationOut.model_validate(r) for r in rows]


# --------------------------------------------------------------------------
# worker onboarding -- this is what grants `can_work`
# --------------------------------------------------------------------------
@router.post("/workers/register", response_model=Message, status_code=201)
async def register_as_worker(
    body: dict, user: CurrentUser, session: SessionDep
) -> Message:
    """Open a worker profile. Requires an approved KYC submission first."""
    approved = await session.scalar(
        select(VerificationSubmission).where(
            VerificationSubmission.user_id == user.id,
            VerificationSubmission.status == "approved",
        )
    )
    if approved is None:
        raise HTTPException(
            status_code=403,
            detail="An approved verification is required before you can take work.",
        )

    category_id = int(body.get("category_id", 0))
    category = await session.get(ServiceCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    existing = await session.get(WorkerProfile, user.id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="You already have a worker profile")

    session.add(
        WorkerProfile(
            user_id=user.id,
            category_id=category_id,
            hourly_rate=float(body.get("hourly_rate", 350)),
            bio=str(body.get("bio", ""))[:2000],
            skills=list(body.get("skills", []))[:20],
            # The best tier the account has earned, not whichever row the `select` happened to
            # return first: an account approved for Aadhaar then registering with a PAN-looking
            # row pending would otherwise open a bronze profile and price itself below its own
            # verification. (`document_type and … or "bronze"` was also a trap — it returned
            # "bronze" for any falsy-but-present value.)
            verification_tier=_best_tier(
                *[
                    _tier_for(row)
                    for row in (
                        await session.execute(
                            select(VerificationSubmission).where(
                                VerificationSubmission.user_id == user.id,
                                VerificationSubmission.status == "approved",
                            )
                        )
                    )
                    .scalars()
                    .all()
                ]
            ),
            approved_at=datetime.now(UTC),
        )
    )
    caps = set(user.capabilities or [])
    caps.add("can_work")
    user.capabilities = sorted(caps)
    await session.flush()
    return Message(detail="Worker profile created. Toggle availability to receive requests.")


# Ordered weakest -> strongest. The rank is explicit because "higher tier" is a claim the
# matcher, the fare multiplier and the hiring card all act on.
TIER_RANK: dict[str, int] = {"none": 0, "bronze": 1, "silver": 2, "gold": 3}


def _tier_for_document(document_type: str) -> str:
    return {"aadhaar": "gold", "pan": "silver", "govt_id": "bronze"}.get(document_type, "bronze")


def _tier_for(submission: VerificationSubmission) -> str:
    return _tier_for_document(submission.document_type)


def _best_tier(*tiers: str) -> str:
    """The strongest tier a user has actually been approved for.

    Verification used to write this account's tier straight from whichever submission the
    admin happened to decide. Approving a `govt_id` after an `aadhaar` therefore *demoted* a
    gold account to bronze -- and `gigs.assign_worker` feeds `verification_tier` into the
    skill-tier fare multiplier, so a reviewer's routine second click silently re-priced a
    worker's pay. A verification decision may only ever improve someone's standing.
    """
    return max(tiers, key=lambda tier: TIER_RANK.get(tier, 0), default="none")


@router.patch("/workers/me/location")
async def set_location(
    body: WorkerLocationUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> Message:
    worker = await session.get(WorkerProfile, user.id)
    if worker is None:
        raise HTTPException(status_code=404, detail="No worker profile")

    has_lat = body.lat is not None
    has_lng = body.lng is not None
    if has_lat != has_lng:
        raise HTTPException(status_code=422, detail="lat and lng must be provided together")
    has_coordinates = has_lat and has_lng
    if has_coordinates and (not body.location_consent or body.location_source != "device"):
        raise HTTPException(
            status_code=422,
            detail="Explicit device-location consent is required when coordinates are sent",
        )
    if body.is_available is True and not has_coordinates:
        raise HTTPException(
            status_code=422,
            detail="A fresh consented device location is required before going online",
        )
    if not has_coordinates and (
        body.location_source is not None or body.accuracy_m is not None or body.location_consent
    ):
        raise HTTPException(status_code=422, detail="Location metadata requires coordinates")
    if not has_coordinates and body.is_available is None:
        raise HTTPException(status_code=422, detail="No location or availability change supplied")

    if has_coordinates:
        worker.lat = body.lat
        worker.lng = body.lng
        worker.location_source = "device"
        worker.location_accuracy_m = body.accuracy_m
        worker.location_updated_at = datetime.now(UTC)
    if body.is_available is not None:
        worker.is_available = body.is_available
    await session.flush()
    return Message(detail="Location and availability updated")


@router.get("/workers/me/profile")
async def my_worker_profile(user: CurrentUser, session: SessionDep) -> dict:
    worker = await session.get(WorkerProfile, user.id)
    if worker is None:
        raise HTTPException(status_code=404, detail="No worker profile")
    category = await session.get(ServiceCategory, worker.category_id)
    return {
        "category": category.name if category else None,
        "hourly_rate": float(worker.hourly_rate),
        "rating": worker.rating,
        "rating_count": worker.rating_count,
        "total_jobs": worker.total_jobs,
        "is_available": worker.is_available,
        "verification_tier": worker.verification_tier,
        "lat": worker.lat,
        "lng": worker.lng,
        "location_source": worker.location_source,
        "location_accuracy_m": worker.location_accuracy_m,
        "location_updated_at": (
            worker.location_updated_at.isoformat() if worker.location_updated_at else None
        ),
        "skills": worker.skills or [],
    }


# --------------------------------------------------------------------------
# trusted contacts
# --------------------------------------------------------------------------
@router.get("/safety/trusted-contacts", response_model=list[TrustedContactOut])
async def list_contacts(user: CurrentUser, session: SessionDep) -> list[TrustedContactOut]:
    rows = (
        await session.execute(
            select(TrustedContact).where(TrustedContact.user_id == user.id)
        )
    ).scalars().all()
    return [TrustedContactOut.model_validate(c) for c in rows]


@router.post("/safety/trusted-contacts", response_model=TrustedContactOut, status_code=201)
async def add_contact(
    payload: TrustedContactCreate, user: CurrentUser, session: SessionDep
) -> TrustedContactOut:
    count = await session.scalar(
        select(func.count()).select_from(TrustedContact).where(TrustedContact.user_id == user.id)
    )
    if (count or 0) >= MAX_TRUSTED_CONTACTS:
        raise HTTPException(status_code=409, detail=f"Maximum {MAX_TRUSTED_CONTACTS} contacts")

    contact = TrustedContact(
        user_id=user.id,
        name=payload.name,
        phone=payload.phone,
        relationship=payload.relationship,
    )
    session.add(contact)
    await session.flush()
    return TrustedContactOut.model_validate(contact)


@router.delete("/safety/trusted-contacts/{contact_id}", response_model=Message)
async def remove_contact(contact_id: int, user: CurrentUser, session: SessionDep) -> Message:
    contact = await session.get(TrustedContact, contact_id)
    if contact is None or contact.user_id != user.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    await session.delete(contact)
    await session.flush()
    return Message(detail="Contact removed")


# --------------------------------------------------------------------------
# SOS
# --------------------------------------------------------------------------
@router.post("/safety/emergency", status_code=201)
async def emergency(
    payload: EmergencyRequest, request: Request, user: CurrentUser, session: SessionDep
) -> dict:
    """Rate-limited SOS. Requires an active gig when one is cited.

    Keyed on user id rather than raw client IP, so an attacker cannot rotate IPs to bypass
    it and an entire apartment block on one NAT cannot be locked out by a neighbour.
    """
    key = f"karma:rl:sos:{user.id}"
    hits = await _cache.incr_window(key, settings.SOS_WINDOW)
    if hits > settings.SOS_LIMIT:
        raise HTTPException(status_code=429, detail="Too many SOS signals. Help is already alerted.")

    against: int | None = None
    if payload.gig_id is not None:
        gig = await session.get(Gig, payload.gig_id)
        if gig is None:
            raise HTTPException(status_code=404, detail="Gig not found")
        if user.id not in {gig.customer_id, gig.worker_id}:
            raise HTTPException(status_code=403, detail="Not your gig")
        if gig.status in {"completed", "cancelled"}:
            raise HTTPException(status_code=409, detail="SOS requires an active gig")
        against = gig.worker_id if user.id == gig.customer_id else gig.customer_id

    incident = SafetyIncident(
        raised_by=user.id,
        against_user_id=against,
        gig_id=payload.gig_id,
        lat=payload.lat,
        lng=payload.lng,
        note=payload.note,
    )
    session.add(incident)
    await session.flush()

    if against is not None:
        await KarmaLedger(session).record(
            against,
            KarmaEventType.SOS_RAISED,
            reason="Emergency signal raised against you",
            ref_type="incident",
            ref_id=incident.id,
        )

    return {
        "detail": "Emergency signal sent to your trusted contacts and the safety team.",
        "incident_id": incident.id,
    }


# --------------------------------------------------------------------------
# disputes
# --------------------------------------------------------------------------
@router.post("/gigs/{gig_id}/dispute", response_model=Message, status_code=201)
async def raise_dispute(
    gig_id: int, body: dict, user: CurrentUser, session: SessionDep
) -> Message:
    # Serialize with payment release, which locks the same gig before checking open disputes.
    gig = await session.scalar(select(Gig).where(Gig.id == gig_id).with_for_update())
    if gig is None:
        raise HTTPException(status_code=404, detail="Gig not found")
    if user.id not in {gig.customer_id, gig.worker_id}:
        raise HTTPException(status_code=403, detail="Not your gig")

    reason = str(body.get("reason", "")).strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A reason is required")

    # One open case per party per gig. Filing is not a free speech act in this product: each
    # dispute costs the other party 15 karma on the spot and freezes their payout until an admin
    # decides it. Without this guard a complainant could restate one grievance indefinitely -- a
    # live run took a verified worker from work 100 to 33 with five 201s -- and every reversal an
    # exoneration grants (see KarmaLedger.reverse) pays back exactly one of those penalties, so the
    # victim owed the review team a click per fabrication. Two parties filing is legitimate and
    # stays possible; so is re-filing after a dismissal, because a problem that came back is real.
    open_case = await session.scalar(
        select(Dispute.id).where(
            Dispute.gig_id == gig_id,
            Dispute.raised_by == user.id,
            Dispute.status.in_(OPEN_DISPUTE_STATUSES),
        )
    )
    if open_case is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have a case open on this gig; it must be decided first",
        )

    dispute = Dispute(gig_id=gig_id, raised_by=user.id, reason=reason[:2000])
    session.add(dispute)
    await session.flush()

    against = gig.worker_id if user.id == gig.customer_id else gig.customer_id
    if against is not None:
        await KarmaLedger(session).record(
            against,
            KarmaEventType.DISPUTE_FILED,
            reason="A dispute was filed against this gig",
            ref_type="dispute",
            ref_id=dispute.id,
        )
    return Message(detail="Dispute opened. Our team will review it.")


# --------------------------------------------------------------------------
# admin
# --------------------------------------------------------------------------
admin = APIRouter(prefix="/admin", tags=["Admin"])


@admin.get("/verifications")
async def pending_verifications(admin_user: AdminUser, session: SessionDep) -> list[dict]:
    rows = (
        await session.execute(
            select(VerificationSubmission, User.display_name, User.handle)
            .join(User, User.id == VerificationSubmission.user_id)
            .where(VerificationSubmission.status == "pending")
            .order_by(VerificationSubmission.created_at.asc())
        )
    ).all()
    return [
        {
            "id": s.id,
            "user_id": s.user_id,
            "display_name": name,
            "handle": handle,
            "document_type": s.document_type,
            "document_ref": s.document_ref,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s, name, handle in rows
    ]


@admin.patch("/verifications/{submission_id}")
async def review_verification(
    submission_id: int, body: dict, admin_user: AdminUser, session: SessionDep
) -> Message:
    decision = str(body.get("decision", "")).strip().lower()
    if decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=422, detail="decision must be approved or rejected")

    submission = await session.get(VerificationSubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    # A decision is final. Re-approving an already-approved submission appended another
    # KYC_APPROVED row every time, and because the ledger is append-only and never
    # deducts, karma ratcheted upward with each replay -- +8 to +20 per click from a
    # single document. The ledger is the source of truth precisely so it cannot be told
    # the same thing twice.
    if submission.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"This submission was already {submission.status}",
        )

    # An admin approving their own identity document is the reviewer and the reviewed at
    # once, which removes the second pair of eyes the review exists to provide.
    if submission.user_id == admin_user.id:
        raise HTTPException(
            status_code=403, detail="You cannot review your own verification submission"
        )

    submission.status = decision
    submission.reviewed_at = datetime.now(UTC)
    submission.reviewer_note = str(body.get("note", ""))[:500]

    if decision == "approved":
        user = await session.get(User, submission.user_id)
        if user is not None:
            approved_types = (
                await session.execute(
                    select(VerificationSubmission.document_type).where(
                        VerificationSubmission.user_id == user.id,
                        VerificationSubmission.status == "approved",
                    )
                )
            ).scalars().all()
            tier = _best_tier(
                user.verification_tier or "none",
                *(_tier_for_document(name) for name in approved_types),
            )
            profile = await session.get(WorkerProfile, user.id)
            if (
                profile is not None
                and TIER_RANK.get(tier, 0) > TIER_RANK.get(profile.verification_tier, 0)
            ):
                # The hiring card and the skill-tier fare multiplier read the *profile* tier,
                # so an upgrade that only lands on `users` leaves the two halves disagreeing.
                profile.verification_tier = tier
            # The karma is a one-time credit for having been identity-verified at all: it
            # keys on the person, not on how many submissions an admin clicked approve on.
            # Keying it per submission meant N copies of one Aadhaar paid N times over, which
            # the append-only ledger can never undo.
            credited_before = await session.scalar(
                select(KarmaEvent.id)
                .where(
                    KarmaEvent.user_id == user.id,
                    KarmaEvent.event_type == KarmaEventType.KYC_APPROVED.value,
                )
                .limit(1)
            )
            user.verification_tier = tier
            user.is_verified = True
            if credited_before is None:
                await KarmaLedger(session).record(
                    user.id,
                    KarmaEventType.KYC_APPROVED,
                    reason=f"Identity verified — {tier.title()} tier",
                    ref_type="kyc",
                    ref_id=submission.id,
                    tier=tier,
                )
    await session.flush()
    return Message(detail=f"Verification {decision}")


@admin.get("/safety/incidents")
async def incidents(admin_user: AdminUser, session: SessionDep) -> list[dict]:
    raiser = aliased(User)
    against = aliased(User)
    rows = (
        await session.execute(
            select(SafetyIncident, raiser.display_name, raiser.handle,
                   against.display_name, against.handle)
            .join(raiser, raiser.id == SafetyIncident.raised_by)
            .outerjoin(against, against.id == SafetyIncident.against_user_id)
            .order_by(SafetyIncident.created_at.desc()).limit(100)
        )
    ).all()
    return [
        {
            "id": incident.id,
            "raised_by": incident.raised_by,
            "raised_by_name": raised_by_name,
            "raised_by_handle": raised_by_handle,
            "against_user_id": incident.against_user_id,
            "against_user_name": against_user_name,
            "against_user_handle": against_user_handle,
            "gig_id": incident.gig_id,
            "lat": incident.lat,
            "lng": incident.lng,
            "note": incident.note,
            "status": incident.status,
            "created_at": incident.created_at.isoformat() if incident.created_at else None,
        }
        for (incident, raised_by_name, raised_by_handle,
             against_user_name, against_user_handle) in rows
    ]


@admin.patch("/safety/incidents/{incident_id}", response_model=Message)
async def update_incident(
    incident_id: int, body: dict, admin_user: AdminUser, session: SessionDep
) -> Message:
    incident = await session.get(SafetyIncident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Safety incident not found")
    incident.status = _next_case_status(incident.status, body)
    restored = False
    if incident.status == "dismissed":
        restored = await _restore_on_dismissal(
            session,
            event_type=KarmaEventType.SOS_RAISED,
            ref_type="incident",
            ref_id=incident.id,
            reason="Emergency signal dismissed — no wrongdoing found",
        )
    await session.flush()
    return Message(
        detail=f"Safety incident marked {incident.status}"
        + (" and karma restored" if restored else "")
    )


@admin.get("/disputes")
async def disputes(admin_user: AdminUser, session: SessionDep) -> list[dict]:
    raiser = aliased(User)
    rows = (
        await session.execute(
            select(Dispute, raiser.display_name, raiser.handle, Gig.title)
            .join(raiser, raiser.id == Dispute.raised_by)
            .join(Gig, Gig.id == Dispute.gig_id)
            .order_by(Dispute.created_at.desc()).limit(100)
        )
    ).all()
    return [
        {
            "id": dispute.id,
            "gig_id": dispute.gig_id,
            "gig_title": gig_title,
            "raised_by": dispute.raised_by,
            "raised_by_name": raised_by_name,
            "raised_by_handle": raised_by_handle,
            "reason": dispute.reason,
            "status": dispute.status,
            "created_at": dispute.created_at.isoformat() if dispute.created_at else None,
        }
        for dispute, raised_by_name, raised_by_handle, gig_title in rows
    ]


@admin.patch("/disputes/{dispute_id}", response_model=Message)
async def update_dispute(
    dispute_id: int, body: dict, admin_user: AdminUser, session: SessionDep
) -> Message:
    dispute = await session.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=404, detail="Dispute not found")
    dispute.status = _next_case_status(dispute.status, body)
    restored = False
    if dispute.status == "dismissed":
        restored = await _restore_on_dismissal(
            session,
            event_type=KarmaEventType.DISPUTE_FILED,
            ref_type="dispute",
            ref_id=dispute.id,
            reason="Dispute dismissed — no wrongdoing found",
        )
    await session.flush()
    return Message(
        detail=f"Dispute marked {dispute.status}"
        + (" and karma restored" if restored else "")
    )


async def _restore_on_dismissal(
    session,
    *,
    event_type: KarmaEventType,
    ref_type: str,
    ref_id: int,
    reason: str,
) -> bool:
    """Give back the karma an unfounded allegation cost, if it ever cost any.

    Only a *dismissal* restores anything. `resolved` means the concern was real and has been
    settled between the parties, which is not the same as the accusation falling away -- paying
    karma back for that would make disputes free. Idempotent by design: a console that retries a
    lost response must not credit twice, so the second call reverses nothing.
    """
    reversal = await KarmaLedger(session).reverse(
        event_type=event_type, ref_type=ref_type, ref_id=ref_id, reason=reason
    )
    return reversal is not None


def _next_case_status(current: str, body: dict) -> str:
    requested = str(body.get("status", "")).strip().lower()
    transitions = {
        "open": {"in_review", "resolved", "dismissed"},
        "in_review": {"resolved", "dismissed"},
        "resolved": set(),
        "dismissed": set(),
    }
    if requested not in {"in_review", "resolved", "dismissed"}:
        raise HTTPException(
            status_code=422, detail="status must be in_review, resolved or dismissed"
        )
    # Safe retries are idempotent: a lost response must not turn a successful
    # resolution into a conflict when the console repeats the same mutation.
    if requested == current:
        return current
    if requested not in transitions.get(current, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move case from '{current}' to '{requested}'",
        )
    return requested


@admin.get("/analytics")
async def analytics(admin_user: AdminUser, session: SessionDep) -> dict:
    users = await session.scalar(select(func.count()).select_from(User)) or 0
    workers = await session.scalar(select(func.count()).select_from(WorkerProfile)) or 0
    gigs = await session.scalar(select(func.count()).select_from(Gig)) or 0
    completed = (
        await session.scalar(select(func.count()).select_from(Gig).where(Gig.status == "completed"))
        or 0
    )
    posts = await session.scalar(select(func.count()).select_from(Post)) or 0
    proofs = (
        await session.scalar(
            select(func.count()).select_from(Post).where(Post.kind == "proof")
        )
        or 0
    )
    # Only proofs that actually came out of a gig. Counting every proof post against the
    # completed-gig count would include seed/imported content with no gig behind it and
    # produce a "rate" above 1 -- a nonsense number on the one metric that is supposed to
    # say whether the merger is working.
    linked_proofs = (
        await session.scalar(
            select(func.count())
            .select_from(Post)
            .where(Post.kind == "proof", Post.gig_id.is_not(None))
        )
        or 0
    )
    pending_verifications = (
        await session.scalar(
            select(func.count()).select_from(VerificationSubmission)
            .where(VerificationSubmission.status == "pending")
        ) or 0
    )
    open_incidents = (
        await session.scalar(
            select(func.count()).select_from(SafetyIncident)
            .where(SafetyIncident.status.in_(("open", "in_review")))
        ) or 0
    )
    open_disputes = (
        await session.scalar(
            select(func.count()).select_from(Dispute)
            .where(Dispute.status.in_(("open", "in_review")))
        ) or 0
    )
    return {
        "users": int(users),
        "workers": int(workers),
        "gigs": int(gigs),
        "gigs_completed": int(completed),
        "posts": int(posts),
        "proof_posts": int(proofs),
        "proof_posts_from_gigs": int(linked_proofs),
        "pending_verifications": int(pending_verifications),
        "open_incidents": int(open_incidents),
        "open_disputes": int(open_disputes),
        # The single number that says whether the merger is working: what fraction of
        # completed work actually published proof. Bounded 0..1 by construction.
        "proof_rate": round(min(int(linked_proofs), int(completed)) / int(completed), 3)
        if completed
        else 0.0,
    }
