"""Explainable worker matching.

Labour Link's scorer is the single best-engineered thing in either repository: a
deterministic, transparent 0-100 score with human-readable reasons. It is kept, with one
fusion change -- ``reputation_score`` is replaced by **work-weighted karma**, so a person
cannot inflate their hiring rank with social popularity (risk R2 in the analysis).

The weights are stated as module constants so they can be tuned -- or replaced by a learned
ranker -- without touching the API contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

W_PROXIMITY = 0.25
W_RATING = 0.20
W_EXPERIENCE = 0.15
W_SKILL = 0.10
W_AVAILABILITY = 0.10
W_RESPONSE = 0.10
W_KARMA = 0.10  # was "reputation"; now explicitly the work-weighted karma

MAX_RADIUS_KM = 5.0


@dataclass(frozen=True)
class Candidate:
    user_id: int
    display_name: str
    handle: str
    avatar_url: str | None
    rating: float
    hourly_rate: float
    distance_km: float
    eta_minutes: int
    score: float
    karma: int
    total_jobs: int
    verification_tier: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    proof_count: int = 0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_score(
    *,
    distance_km: float,
    rating: float,
    total_jobs: int,
    skill_match: float,
    is_available: bool,
    avg_response_time_seconds: int,
    karma: int,
) -> float:
    """Transparent 0-100 ranking score."""
    proximity = _clamp01(1.0 - (max(distance_km, 0.0) / MAX_RADIUS_KM))
    norm_rating = _clamp01(rating / 5.0)
    experience = _clamp01(total_jobs / 100.0)
    response = _clamp01(1.0 - (max(avg_response_time_seconds, 0) / 3600.0))
    trust = _clamp01(karma / 100.0)

    score = (
        W_PROXIMITY * proximity
        + W_RATING * norm_rating
        + W_EXPERIENCE * experience
        + W_SKILL * _clamp01(skill_match)
        + W_AVAILABILITY * float(is_available)
        + W_RESPONSE * response
        + W_KARMA * trust
    )
    return round(score * 100, 2)


def explain(
    *, distance_km: float, rating: float, total_jobs: int, tier: str, karma: int, score: float
) -> tuple[str, ...]:
    """Human-readable reasons, capped at three -- shown verbatim in the UI."""
    reasons: list[str] = []
    if distance_km <= 2:
        reasons.append("Very close to the job")
    if rating >= 4.7:
        reasons.append(f"Highly rated ({rating:.1f})")
    if total_jobs >= 25:
        reasons.append("Experienced professional")
    if tier in {"silver", "gold"}:
        reasons.append(f"{tier.title()} verified")
    if karma >= 80:
        reasons.append("Strong work reputation")
    if score >= 80:
        reasons.append("Strong overall match")
    return tuple(reasons[:3])


def eta_minutes(distance_km: float, avg_speed_kmh: float = 25.0) -> int:
    return max(1, int((max(distance_km, 0.0) / avg_speed_kmh) * 60))


def rank_candidates(rows: list[dict], *, limit: int = 5) -> list[Candidate]:
    """Score and sort raw GeoPort rows into ranked candidates."""
    scored: list[Candidate] = []
    for row in rows:
        distance = float(row["distance_km"])
        rating = float(row.get("rating") or 0.0)
        total_jobs = int(row.get("total_jobs") or 0)
        karma = int(row.get("karma_work") or row.get("karma") or 50)
        tier = str(row.get("verification_tier") or "bronze")
        response = int(row.get("avg_response_time_seconds") or 900)

        score = compute_score(
            distance_km=distance,
            rating=rating,
            total_jobs=total_jobs,
            skill_match=1.0,
            is_available=True,
            avg_response_time_seconds=response,
            karma=karma,
        )
        scored.append(
            Candidate(
                user_id=int(row["user_id"]),
                display_name=str(row.get("display_name") or "Worker"),
                handle=str(row.get("handle") or ""),
                avatar_url=row.get("avatar_url"),
                rating=rating,
                hourly_rate=float(row.get("hourly_rate") or 0.0),
                distance_km=round(distance, 2),
                eta_minutes=eta_minutes(distance),
                score=score,
                karma=karma,
                total_jobs=total_jobs,
                verification_tier=tier,
                reasons=explain(
                    distance_km=distance,
                    rating=rating,
                    total_jobs=total_jobs,
                    tier=tier,
                    karma=karma,
                    score=score,
                ),
                proof_count=int(row.get("proof_count") or 0),
            )
        )
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:limit]
