"""Explainable matching and the service catalogue."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep
from app.core.ports import HaversineGeo, PostgisGeo
from app.models.marketplace import Gig, ServiceCategory, WorkerProfile
from app.models.social import Post
from app.schemas import CandidateOut, CategoryOut, MatchRequest
from app.services.matching import rank_candidates

router = APIRouter(tags=["Matching"])


def _geo():
    return PostgisGeo() if settings.use_postgis else HaversineGeo()


@router.get("/categories", response_model=list[CategoryOut])
async def categories(session: SessionDep) -> list[CategoryOut]:
    rows = (
        await session.execute(
            select(ServiceCategory)
            .where(ServiceCategory.is_active == True)  # noqa: E712
            .order_by(ServiceCategory.name.asc())
        )
    ).scalars().all()
    return [CategoryOut.model_validate(c) for c in rows]


@router.post("/matching/find", response_model=list[CandidateOut])
async def find_matches(
    payload: MatchRequest, session: SessionDep, user: CurrentUser
) -> list[CandidateOut]:
    """Rank available workers for a gig, with reasons shown verbatim in the UI.

    Ranked by **work-weighted karma**, not blended karma, so social popularity cannot buy
    a higher hiring position.
    """
    gig = await session.get(Gig, payload.gig_id)
    if gig is None:
        raise HTTPException(status_code=404, detail="Gig not found")
    if gig.customer_id != user.id and "admin" not in set(user.capabilities or []):
        raise HTTPException(status_code=403, detail="Not your gig")

    rows = await _geo().workers_within(
        session,
        lat=gig.lat,
        lng=gig.lng,
        category_id=gig.category_id,
        radius_km=settings.MATCH_RADIUS_KM,
    )
    candidates = rank_candidates(rows, limit=8)
    return [CandidateOut(**c.__dict__) for c in candidates]


@router.get("/workers/{worker_id}")
async def worker_public_profile(worker_id: int, session: SessionDep) -> dict:
    """The hiring-facing profile: trust signals plus actual proof of work."""
    from app.models.user import User

    profile_user = await session.get(User, worker_id)
    if profile_user is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    worker = await session.get(WorkerProfile, worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="Not a registered worker")

    category = await session.get(ServiceCategory, worker.category_id)
    proofs = (
        await session.execute(
            select(Post)
            .where(Post.author_id == worker_id, Post.kind == "proof")
            .order_by(Post.created_at.desc())
            .limit(12)
        )
    ).scalars().all()

    return {
        "user_id": worker_id,
        "display_name": profile_user.display_name,
        "handle": profile_user.handle,
        "avatar_url": profile_user.avatar_url,
        "bio": worker.bio or profile_user.bio,
        "karma": profile_user.karma,
        "karma_work": profile_user.karma_work,
        "verification_tier": worker.verification_tier,
        "rating": worker.rating,
        "rating_count": worker.rating_count,
        "total_jobs": worker.total_jobs,
        "hourly_rate": float(worker.hourly_rate),
        "is_available": worker.is_available,
        "skills": worker.skills or [],
        "category": category.name if category else None,
        # The fusion payoff: their social proof, right on the hiring card.
        "proofs": [
            {
                "id": p.id,
                "title": p.body,
                "before_url": p.before_url,
                "after_url": p.after_url,
                "rating": p.rating,
                "amount_earned": p.amount_earned,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in proofs
        ],
    }
