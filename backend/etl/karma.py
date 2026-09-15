"""Karma reconciliation — the one genuinely lossy mapping in the merge, handled openly.

Both source systems had a `reputation_score` on `users`, on different scales and with
different meanings:

    Tatwamasi   Float,       default 100.0  — a social engagement score
    LabourLink  Numeric(5,2) default 50.00  — a marketplace risk score

Collapsing them into one number destroys information, so the ETL does three things to keep
that honest:

  1. It weights work above social (0.6 / 0.4), matching the live blended-karma rule, so a
     migrated user's number means the same thing as a native one.
  2. A missing side contributes its neutral 50, never 0 — absence of data is not a bad
     reputation.
  3. Every backfilled value is written to the ledger as a MIGRATION_BACKFILL row, so the
     number is auditable from day one instead of appearing from nowhere.
"""

from __future__ import annotations

from dataclasses import dataclass

KARMA_MIN, KARMA_MAX = 0, 100
NEUTRAL = 50
WORK_WEIGHT = 0.6
SOCIAL_WEIGHT = 0.4


@dataclass(frozen=True)
class KarmaReconciliation:
    blended: int
    work: int
    social: int
    had_social: bool
    had_work: bool
    note: str


def reconcile(
    *,
    tatwamasi_reputation: float | None,
    labourlink_reputation: float | None,
) -> KarmaReconciliation:
    """Map two legacy reputation scores onto the unified karma scale."""
    had_social = tatwamasi_reputation is not None
    had_work = labourlink_reputation is not None

    social = _clamp(_scale_social(tatwamasi_reputation)) if had_social else NEUTRAL
    work = _clamp(_scale_work(labourlink_reputation)) if had_work else NEUTRAL

    blended = _clamp(int(round(WORK_WEIGHT * work + SOCIAL_WEIGHT * social)))

    parts: list[str] = []
    if had_social:
        parts.append(f"social {tatwamasi_reputation:.1f} -> {social}")
    else:
        parts.append("social absent -> neutral 50")
    if had_work:
        parts.append(f"work {labourlink_reputation:.2f} -> {work}")
    else:
        parts.append("work absent -> neutral 50")

    return KarmaReconciliation(
        blended=blended,
        work=work,
        social=social,
        had_social=had_social,
        had_work=had_work,
        note="; ".join(parts),
    )


def _scale_social(value: float | None) -> float:
    """Tatwamasi scores centre on 100 for a brand-new user and rise with engagement.

    Mapping 100 -> 50 (neutral) keeps a freshly-registered legacy user from arriving as a
    top-tier account purely because the old default was generous.
    """
    if value is None:
        return float(NEUTRAL)
    return float(value) * 0.5


def _scale_work(value: float | None) -> float:
    """Labour Link's score is already 0-100, so it transfers directly."""
    if value is None:
        return float(NEUTRAL)
    return float(value)


def _clamp(value: float) -> int:
    return max(KARMA_MIN, min(KARMA_MAX, int(round(value))))
