"""Geo port: the two implementations must agree, and the scorer must be sane."""

from __future__ import annotations

import pytest

from app.core.ports import haversine_km
from app.services.matching import compute_score, eta_minutes, explain, rank_candidates


def test_haversine_known_distance():
    """Indore centre to a point ~11 km north."""
    distance = haversine_km(22.7196, 75.8577, 22.8196, 75.8577)
    assert 11.0 < distance < 11.2


def test_haversine_zero_for_same_point():
    assert haversine_km(22.7196, 75.8577, 22.7196, 75.8577) == 0.0


def test_haversine_is_symmetric():
    a = haversine_km(22.7196, 75.8577, 22.75, 75.9)
    b = haversine_km(22.75, 75.9, 22.7196, 75.8577)
    assert abs(a - b) < 1e-9


def test_haversine_agrees_with_independent_formula():
    """Cross-check against the spherical law of cosines -- a different derivation.

    Two independent formulas agreeing to the millimetre is a stronger check than
    comparing against a hand-typed constant, which can simply be wrong.
    """
    import math

    def law_of_cosines(lat1, lon1, lat2, lon2, R=6371.0088):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dlon = math.radians(lon2 - lon1)
        return R * math.acos(
            math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dlon)
        )

    pairs = [
        (22.7196, 75.8577, 22.75, 75.9),        # intra-city
        (22.7196, 75.8577, 22.8196, 75.8577),   # due north
        (19.0760, 72.8777, 28.6139, 77.2090),   # Mumbai -> Delhi
    ]
    for lat1, lon1, lat2, lon2 in pairs:
        ours = haversine_km(lat1, lon1, lat2, lon2)
        reference = law_of_cosines(lat1, lon1, lat2, lon2)
        assert abs(ours - reference) < 1e-6, f"{ours} vs {reference}"


def test_eta_never_zero():
    assert eta_minutes(0.1) == 1
    assert eta_minutes(4.2) == 10


# --- scorer ---------------------------------------------------------------
def _row(**overrides):
    base = dict(
        user_id=1,
        display_name="Test",
        handle="test",
        avatar_url=None,
        rating=5.0,
        hourly_rate=350.0,
        distance_km=1.0,
        total_jobs=50,
        avg_response_time_seconds=300,
        verification_tier="gold",
        karma=90,
        karma_work=90,
        proof_count=3,
    )
    base.update(overrides)
    return base


def test_score_is_bounded_0_to_100():
    best = compute_score(
        distance_km=0,
        rating=5,
        total_jobs=500,
        skill_match=1,
        is_available=True,
        avg_response_time_seconds=0,
        karma=100,
    )
    worst = compute_score(
        distance_km=99,
        rating=0,
        total_jobs=0,
        skill_match=0,
        is_available=False,
        avg_response_time_seconds=99999,
        karma=0,
    )
    assert 0 <= worst <= best <= 100
    assert best == 100.0


def test_out_of_range_inputs_cannot_break_the_scorer():
    """Negative or absurd inputs must clamp, not produce a negative or >100 score."""
    score = compute_score(
        distance_km=-100,
        rating=-5,
        total_jobs=-50,
        skill_match=-1,
        is_available=False,
        avg_response_time_seconds=-1,
        karma=-500,
    )
    assert 0 <= score <= 100


def test_closer_worker_outranks_farther_one():
    near = compute_score(
        distance_km=0.5, rating=4.8, total_jobs=30, skill_match=1,
        is_available=True, avg_response_time_seconds=300, karma=80,
    )
    far = compute_score(
        distance_km=4.5, rating=4.8, total_jobs=30, skill_match=1,
        is_available=True, avg_response_time_seconds=300, karma=80,
    )
    assert near > far


def test_ranking_sorts_descending_and_respects_limit():
    rows = [_row(user_id=i, distance_km=i * 0.5, karma=90 - i * 5) for i in range(1, 6)]
    ranked = rank_candidates(rows, limit=3)
    assert len(ranked) == 3
    scores = [c.score for c in ranked]
    assert scores == sorted(scores, reverse=True)


def test_every_candidate_has_human_readable_reasons():
    """Explainability is the product strategy: no score without reasons."""
    ranked = rank_candidates([_row()], limit=5)
    assert ranked
    assert len(ranked[0].reasons) >= 1
    assert all(isinstance(r, str) and r for r in ranked[0].reasons)
    assert len(ranked[0].reasons) <= 3, "capped at three, per the design manifesto"


def test_reasons_reflect_the_inputs():
    """Reasons are ordered by salience and capped at three, per the design manifesto."""
    reasons = explain(
        distance_km=1.0, rating=4.9, total_jobs=40, tier="gold", karma=90, score=85
    )
    assert len(reasons) == 3
    assert reasons[0] == "Very close to the job"
    assert "Highly rated" in reasons[1]

    # With proximity and experience out of the way, the tier survives the cap.
    sparse = explain(
        distance_km=4.0, rating=3.5, total_jobs=2, tier="gold", karma=40, score=30
    )
    assert any("gold" in r.lower() for r in sparse)


def test_ranker_uses_work_karma_not_blended():
    """★ Social popularity must not buy a higher hiring rank."""
    popular = _row(user_id=1, karma=99, karma_work=50, distance_km=2.0)
    proven = _row(user_id=2, karma=55, karma_work=95, distance_km=2.0)
    ranked = rank_candidates([popular, proven], limit=2)
    assert ranked[0].user_id == 2, "the worker with real work karma must rank first"


# ── GeoPort parity ────────────────────────────────────────────────────────────
#
# `HaversineGeo` (dev/SQLite) and `PostgisGeo` (prod/Postgres) are interchangeable
# implementations of one port. Nothing in the type system enforces that they return the same
# keys or even read the same columns -- a mismatch shows up only as degraded behaviour in
# production, which is exactly where it is hardest to notice. These tests are the guardrail.

import inspect
import re

from app.core.db import Base
from app.core.ports import HaversineGeo, PostgisGeo


def _sql_of(impl) -> str:
    return inspect.getsource(impl.workers_within)


def _aliases(sql: str) -> set[str]:
    """The output column names a query promises (its `AS x` list)."""
    return set(re.findall(r"\bAS\s+([a-z_]+)\b", sql))


def _table_refs(sql: str) -> set[tuple[str, str]]:
    """Every `alias.column` the query touches."""
    alias = {"u": "users", "w": "worker_profiles", "p": "posts"}
    return {(alias[a], c) for a, c in re.findall(r"\b([uwp])\.([a-z_]+)", sql)}


def test_both_geo_implementations_promise_the_same_columns():
    """★ The scorer reads karma_work, not karma, so social reach cannot buy a hiring rank.

    If the PostGIS port dropped karma_work the matcher would silently fall back to blended
    karma -- the exact invariant the fusion exists to protect -- and no other test would fail.

    `distance_km` is excluded from the comparison because the two implementations legitimately
    produce it differently: PostGIS computes it in SQL via ST_Distance, Haversine computes it in
    Python after a bounding-box prefilter. Both end up on the returned dict, which is what the
    caller sees.
    """
    hav = _aliases(_sql_of(HaversineGeo)) - {"distance_km"}
    pg = _aliases(_sql_of(PostgisGeo)) - {"distance_km"}
    assert hav == pg, f"PostgisGeo is missing {sorted(hav - pg)}; extra {sorted(pg - hav)}"


def test_geo_ports_expose_the_keys_the_matcher_reads():
    """The contract is defined by the consumer, not by the implementer."""
    required = {
        "user_id",
        "karma",
        "karma_work",
        "reputation_score",
        "display_name",
        "handle",
        "avatar_url",
        "rating",
        "hourly_rate",
        "total_jobs",
        "avg_response_time_seconds",
        "verification_tier",
        "proof_count",
        "distance_km",
    }
    hav = _aliases(_sql_of(HaversineGeo))
    pg = _aliases(_sql_of(PostgisGeo))
    # HaversineGeo computes distance_km in Python and injects it, so it is not in the SQL.
    assert (hav | {"distance_km"}) >= required, f"HaversineGeo lacks {sorted(required - hav)}"
    assert pg >= required, f"PostgisGeo lacks {sorted(required - pg)}"


def test_geo_ports_reference_only_columns_that_exist():
    """★ PostgisGeo once queried `worker_profiles.current_location`, a column the models never had.

    It could not fail in CI -- only in production, on the first hire. Raw SQL has no compiler,
    so this assertion is the compiler.
    """
    for impl in (HaversineGeo, PostgisGeo):
        for table, column in sorted(_table_refs(_sql_of(impl))):
            assert column in Base.metadata.tables[table].columns, (
                f"{impl.__name__} references {table}.{column}, which does not exist"
            )


def test_geo_ports_use_the_same_filters():
    """A worker visible in dev must be visible in prod."""
    hav = _sql_of(HaversineGeo)
    pg = _sql_of(PostgisGeo)
    for clause in ("category_id", "is_available", "approved_at IS NOT NULL", "is_suspended"):
        assert clause in hav and clause in pg, f"filter {clause!r} missing from one implementation"
