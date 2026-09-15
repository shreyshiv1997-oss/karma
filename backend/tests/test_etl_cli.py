"""The ETL command line.

`amain` is the only part of the migration an operator actually runs, and nothing had ever
called it. The library beneath it is well covered; the argument parsing, the dry-run default,
the exit codes and the printed report were not. A migration that fails at `argv` fails on the
one night it matters.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from etl.runner import _parse_dt, _slugify, amain
from tests.etl_fixtures import build_labourlink, build_tatwamasi

# Only the async tests get the mark; the sync helper tests below opt out explicitly, or
# pytest warns that a non-async function is marked asyncio.
pytestmark = []


def _report(captured: str) -> dict:
    """Pull the JSON report out of the CLI's stdout by matching braces.

    Slicing on a trailing blank line is fragile: `--commit` ends the output with `}` and a
    newline, while an abort appends a sentence after it. Matching the object is robust to both.
    """
    start = captured.index("{")
    depth = 0
    for i, ch in enumerate(captured[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(captured[start : i + 1])
    raise AssertionError("no complete JSON object in the CLI output")


@pytest.fixture
def clean_sources(tmp_path):
    """Both source databases, with referential integrity intact."""
    tat = str(tmp_path / "tatwamasi.db")
    lab = str(tmp_path / "labourlink.db")
    build_tatwamasi(tat)
    build_labourlink(lab)
    return {"tatwamasi": tat, "labourlink": lab, "tmp": tmp_path}


@pytest.fixture
def broken_sources(tmp_path):
    """A source with a post pointing at a user who does not exist."""
    tat = str(tmp_path / "tatwamasi.db")
    lab = str(tmp_path / "labourlink.db")
    build_tatwamasi(tat, orphan_post=True)
    build_labourlink(lab)
    return {"tatwamasi": tat, "labourlink": lab, "tmp": tmp_path}


# ── dry run ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_a_dry_run_writes_nothing_and_exits_zero(clean_sources, capsys):
    """★ The default is a dry run. Running the tool must not be able to touch a database."""
    target = clean_sources["tmp"] / "should_not_exist.db"

    code = await amain(
        [
            "--tatwamasi", clean_sources["tatwamasi"],
            "--labourlink", clean_sources["labourlink"],
            "--target", f"sqlite+aiosqlite:///{target}",
        ]
    )
    assert code == 0

    out = capsys.readouterr().out
    assert "[dry-run]" in out, "the operator must be told nothing was persisted"
    assert "DRY RUN: nothing was written" in out
    assert not target.exists(), "a dry run must not create the target file"


@pytest.mark.asyncio
async def test_a_dry_run_still_prints_the_full_report(clean_sources, capsys):
    """The point of a dry run is to read the numbers before committing to them."""
    await amain(
        [
            "--tatwamasi", clean_sources["tatwamasi"],
            "--labourlink", clean_sources["labourlink"],
        ]
    )
    report = _report(capsys.readouterr().out)

    assert report["users_created"] > 0
    assert report["users_merged"] > 0, "the two sources must actually converge"
    assert report["dry_run"] is True
    assert report["rolled_back"] is False
    assert report["unresolved_foreign_keys"] == 0
    # `committed` describes the transaction, which does commit -- to memory. `persisted`
    # is the field that answers the question the operator is actually asking.
    assert report["persisted"] is False, "a dry run must not claim to have written anything"


# ── commit ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_committing_writes_a_usable_target(clean_sources, capsys):
    target = clean_sources["tmp"] / "karma_migrated.db"

    code = await amain(
        [
            "--tatwamasi", clean_sources["tatwamasi"],
            "--labourlink", clean_sources["labourlink"],
            "--target", f"sqlite+aiosqlite:///{target}",
            "--commit",
        ]
    )
    assert code == 0, capsys.readouterr().out

    db = sqlite3.connect(target)
    try:
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        assert users == 5, f"3 + 4 source users converge to 5 after merges, got {users}"
        # Every migrated user carries a karma projection and a ledger explaining it.
        # Each backfilled user gets one row per domain that contributed a score.
        # `domain` is work/social; the marker that says "this came from the ETL" is the
        # event type, not the domain.
        backfills = db.execute(
            "SELECT COUNT(*) FROM karma_events WHERE event_type='migration_backfill'"
        ).fetchone()[0]
        assert backfills >= users, (
            f"every backfilled user writes at least one migration_backfill row: "
            f"{backfills} rows for {users} users"
        )
        domains = {
            r[0]
            for r in db.execute(
                "SELECT DISTINCT domain FROM karma_events WHERE event_type='migration_backfill'"
            )
        }
        assert domains == {"work", "social"}, (
            "the blend needs both halves, so both must be recorded"
        )
    finally:
        db.close()


@pytest.mark.asyncio
async def test_the_committed_report_says_so(clean_sources, capsys):
    target = clean_sources["tmp"] / "karma_migrated.db"
    await amain(
        [
            "--tatwamasi", clean_sources["tatwamasi"],
            "--labourlink", clean_sources["labourlink"],
            "--target", f"sqlite+aiosqlite:///{target}",
            "--commit",
        ]
    )
    out = capsys.readouterr().out
    report = _report(out)
    assert report["committed"] is True
    assert report["dry_run"] is False
    assert report["persisted"] is True, "the target was really written"
    assert report["rolled_back"] is False
    assert "COMMITTED to" in out


# ── the abort path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unresolved_foreign_key_aborts_with_exit_1(broken_sources, capsys):
    """★ Non-zero exit and a refusal to promote. A CI pipeline must be able to see this."""
    target = broken_sources["tmp"] / "karma_migrated.db"

    code = await amain(
        [
            "--tatwamasi", broken_sources["tatwamasi"],
            "--labourlink", broken_sources["labourlink"],
            "--target", f"sqlite+aiosqlite:///{target}",
            "--commit",
        ]
    )
    assert code == 1, "unresolved foreign keys must be a hard failure"

    out = capsys.readouterr().out
    assert "ABORTED" in out
    assert "unresolved foreign key" in out


@pytest.mark.asyncio
async def test_an_aborted_commit_leaves_an_empty_target(broken_sources, capsys):
    """★ The rollback must be real, not merely reported."""
    target = broken_sources["tmp"] / "karma_migrated.db"

    await amain(
        [
            "--tatwamasi", broken_sources["tatwamasi"],
            "--labourlink", broken_sources["labourlink"],
            "--target", f"sqlite+aiosqlite:///{target}",
            "--commit",
        ]
    )
    capsys.readouterr()

    db = sqlite3.connect(target)
    try:
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        posts = db.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        assert users == 0, f"the rollback must have discarded the users, found {users}"
        assert posts == 0, f"the rollback must have discarded the posts, found {posts}"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_dry_run_over_broken_sources_still_exits_1(broken_sources, capsys):
    """The problem is in the source, not in the decision to commit -- report it either way."""
    code = await amain(
        [
            "--tatwamasi", broken_sources["tatwamasi"],
            "--labourlink", broken_sources["labourlink"],
        ]
    )
    assert code == 1
    assert "ABORTED" in capsys.readouterr().out


# ── argument handling ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_required_sources_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        await amain([])
    assert exc.value.code == 2, "argparse exits 2 on a usage error"
    err = capsys.readouterr().err
    assert "--tatwamasi" in err and "--labourlink" in err


@pytest.mark.asyncio
async def test_a_nonexistent_source_fails_loudly(tmp_path, capsys):
    """★ A typo'd path must never look like a successful migration of nothing.

    Sources are opened read-only (`mode=ro`), so SQLite refuses a path that does not exist
    rather than creating an empty database. The result is a hard failure at open time -- which
    is the right behaviour, but it surfaces as an uncaught `OperationalError` rather than a
    clean exit code. Recorded here so the shape is known rather than discovered at 2am.
    """
    import sqlite3

    with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
        await amain(
            [
                "--tatwamasi", str(tmp_path / "nope.db"),
                "--labourlink", str(tmp_path / "also_nope.db"),
                "--target", f"sqlite+aiosqlite:///{tmp_path / 'out.db'}",
                "--commit",
            ]
        )
    assert capsys.readouterr().out.count('"committed": true') == 0


# ── the small helpers ─────────────────────────────────────────────────────────


def test_slugify_lowercases_and_separates():
    assert _slugify("Home Appliance Repair") == "home-appliance-repair"
    assert _slugify("  AC & Fridge  ") == "ac---fridge"
    assert _slugify("") == ""


def test_slugify_keeps_devanagari_letters():
    """★ Indian-language category names must survive the merge, not be blanked.

    `str.isalnum()` is Unicode-aware, so Devanagari letters pass; the combining vowel signs
    (matras) are not alphanumeric and become separators. The result is uglier but never empty,
    which is what matters for a slug that has to stay unique.
    """
    assert _slugify("बिजली") == "ब-जल"
    assert _slugify("हिंदी") == "ह--द"
    assert _slugify("बिजली") != "", "a Devanagari name must never collapse to an empty slug"


def test_slugify_keeps_digits():
    assert _slugify("24x7 Plumbing") == "24x7-plumbing"


def test_parse_dt_accepts_none():
    assert _parse_dt(None) is None


def test_parse_dt_passes_a_datetime_through():
    from datetime import UTC, datetime

    moment = datetime(2024, 5, 1, 12, 0, tzinfo=UTC)
    assert _parse_dt(moment) is moment


def test_parse_dt_reads_an_iso_string():
    assert _parse_dt("2024-05-01T12:00:00").year == 2024


def test_parse_dt_returns_none_on_garbage():
    """★ A malformed source timestamp must not abort a whole migration."""
    assert _parse_dt("not a date") is None
    assert _parse_dt("") is None
    assert _parse_dt("0000-00-00 00:00:00") is None


def test_parse_dt_handles_a_numeric_timestamp_string():
    assert _parse_dt("1714564800") is None, "epoch integers are not ISO and are skipped, not guessed"
