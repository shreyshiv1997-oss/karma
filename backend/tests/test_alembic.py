"""The Alembic baseline must actually build a schema the application can run on.

This is a slower test -- it shells out to `alembic upgrade head` and boots the app -- but it
is the only thing standing between "a migration file exists" and "a migration file works".
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

# The tables the models declare. If this list drifts from the models the test should be
# updated deliberately, not by accident.
EXPECTED_TABLES = {
    "bitchat_conversations",
    "bitchat_devices",
    "bitchat_envelopes",
    "bitchat_panic_events",
    "bitchat_prekeys",
    "comments",
    "disputes",
    "follows",
    "gig_bids",
    "gig_payments",
    "gigs",
    "karma_events",
    "ledger_entries",
    "likes",
    "media_objects",
    "posts",
    "reviews",
    "safety_incidents",
    "service_categories",
    "stripe_webhook_events",
    "trusted_contacts",
    "users",
    "verification_submissions",
    "wallets",
    "worker_availability",
    "worker_profiles",
}


def _alembic(args: list[str], db_path: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "PYTHONPATH": str(BACKEND),
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )


def _tables(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def test_upgrade_head_creates_every_table(tmp_path):
    """★ The baseline is the schema. If a model gains a table, this fails."""
    db = str(tmp_path / "up.db")
    result = _alembic(["upgrade", "head"], db)
    assert result.returncode == 0, result.stderr

    found = _tables(db)
    assert found == EXPECTED_TABLES, (
        f"missing: {sorted(EXPECTED_TABLES - found)}; "
        f"unexpected: {sorted(found - EXPECTED_TABLES)}"
    )


def test_downgrade_base_removes_every_table(tmp_path):
    """A baseline that cannot be reversed is not a baseline."""
    db = str(tmp_path / "down.db")
    assert _alembic(["upgrade", "head"], db).returncode == 0
    assert _tables(db) == EXPECTED_TABLES

    result = _alembic(["downgrade", "base"], db)
    assert result.returncode == 0, result.stderr
    assert _tables(db) == set(), "downgrade left tables behind"


def test_baseline_has_no_drift_from_the_models(tmp_path):
    """★ Autogenerate against a migrated database must propose nothing.

    If this fails, a model changed without a migration. That is exactly the failure mode
    Alembic exists to catch, and it is invisible in every other test here.
    """
    db = str(tmp_path / "drift.db")
    assert _alembic(["upgrade", "head"], db).returncode == 0

    result = _alembic(["revision", "--autogenerate", "-m", "drift probe"], db)
    assert result.returncode == 0, result.stderr

    detected = [ln for ln in result.stderr.splitlines() if "Detected " in ln and (
        "added" in ln or "removed" in ln or "changed" in ln
    )]
    # Clean up the probe file it may have written so the tree stays tidy.
    for f in (BACKEND / "alembic" / "versions").glob("*_drift_probe.py"):
        f.unlink()
    assert detected == [], f"schema drifted from the models: {detected}"


@pytest.mark.timeout(120)
def test_application_runs_on_an_alembic_built_schema(tmp_path):
    """★ The end-to-end guarantee: build with Alembic, then actually use the app."""
    db = str(tmp_path / "app.db")
    result = subprocess.run(
        [sys.executable, "scripts/check_alembic.py"],
        cwd=BACKEND,
        env={**os.environ, "KARMA_CHECK_DB": db},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "runs correctly on an Alembic-built schema" in result.stdout
