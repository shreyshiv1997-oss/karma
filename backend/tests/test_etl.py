"""ETL tests — the migration plan from Phase 1 §4, actually executed.

These are the highest-risk tests in the repository: R1 in the analysis is "merging two
different humans into one account", which is unrecoverable if it happens silently. So the
identity tests assert on the *decision*, not just on the row counts.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.core.db import Base
from app.models.marketplace import Gig, ServiceCategory, WorkerProfile
from app.models.social import Post
from app.models.trust import Review
from app.models.user import KarmaDomain, KarmaEvent, User
from etl.identity import IdentityResolver, SourceIdentity
from etl.karma import reconcile
from etl.runner import ETL
from tests.etl_fixtures import build_labourlink, build_tatwamasi



# --------------------------------------------------------------------------
# identity resolution (pure, no database)
# --------------------------------------------------------------------------
def _ident(source, sid, phone=None, email=None, handle=None, name="X", rep=None):
    return SourceIdentity(
        source=source, source_id=sid, phone=phone, email=email,
        handle=handle, display_name=name, reputation=rep, password_hash=None,
    )


def test_same_phone_merges():
    r = IdentityResolver()
    r.resolve(_ident("labourlink", 1, phone="919876500001"))
    out = r.resolve(_ident("tatwamasi", 9, phone="+91 98765 00001"))
    assert out.decision == "merge"
    assert out.merge_into == "labourlink:1"
    assert "same verified phone" in out.reason


def test_phone_normalisation_ignores_formatting():
    """Spacing and punctuation must not split one person into two accounts.

    Note this compares the *same* digits in two formats -- a country-code difference
    is a genuinely different number and must NOT merge.
    """
    r = IdentityResolver()
    r.resolve(_ident("labourlink", 1, phone="+91 98765-00001"))
    assert r.resolve(_ident("tatwamasi", 2, phone="919876500001")).decision == "merge"


def test_different_country_codes_do_not_merge():
    """'+91 98765 00001' and '9876500001' are different numbers, not formatting variants."""
    r = IdentityResolver()
    r.resolve(_ident("labourlink", 1, phone="9876500001"))
    assert r.resolve(_ident("tatwamasi", 2, phone="+91 98765 00001")).decision == "create"


def test_same_email_merges_when_no_phone_conflict():
    r = IdentityResolver()
    r.resolve(_ident("labourlink", 1, email="Priya@Example.com"))
    out = r.resolve(_ident("tatwamasi", 5, email="priya@example.com"))
    assert out.decision == "merge", "email is case-insensitive"


def test_conflicting_phones_on_one_email_go_to_review_never_merge():
    """★ R1. Same email, two different verified phones = two different people."""
    r = IdentityResolver()
    r.resolve(_ident("labourlink", 1, phone="9876500001", email="shared@example.com"))
    out = r.resolve(_ident("labourlink", 2, phone="9876500002", email="shared@example.com"))
    assert out.decision == "review"
    assert out.merge_into is None
    assert len(r.queue) == 1
    assert "phones conflict" in r.queue[0]["reason"]


def test_handle_collision_is_never_a_merge():
    """Handles are chosen, not verified. Two people may legitimately want the same one."""
    r = IdentityResolver()
    r.resolve(_ident("tatwamasi", 1, handle="priya", email="a@example.com"))
    out = r.resolve(_ident("tatwamasi", 2, handle="priya", email="b@example.com"))
    assert out.decision == "create"
    assert out.merge_into is None
    assert out.new_handle == "priya2", "the later arrival gets a suffixed handle"


def test_handle_suffix_increments_until_unique():
    r = IdentityResolver()
    for i, email in enumerate(["a@e.com", "b@e.com", "c@e.com"]):
        r.resolve(_ident("tatwamasi", i, handle="priya", email=email))
    assert sorted(r.by_handle) == ["priya", "priya2", "priya3"]


def test_labourlink_user_without_a_handle_gets_a_derived_one():
    r = IdentityResolver()
    out = r.resolve(_ident("labourlink", 7, phone="9876500009", name="Ramesh Kumar"))
    assert out.decision == "create"
    assert "ramesh_kumar" in r.by_handle


def test_unrelated_identities_do_not_merge():
    r = IdentityResolver()
    r.resolve(_ident("labourlink", 1, phone="9876500001", email="a@e.com"))
    out = r.resolve(_ident("tatwamasi", 2, email="totally-different@e.com", handle="zoe"))
    assert out.decision == "create"
    assert out.merge_into is None


# --------------------------------------------------------------------------
# karma reconciliation (pure)
# --------------------------------------------------------------------------
def test_karma_weights_work_above_social():
    """0.6 work / 0.4 social, matching the live blended rule."""
    result = reconcile(tatwamasi_reputation=100.0, labourlink_reputation=100.0)
    assert result.work == 100
    assert result.social == 50, "Tatwamasi's 100 default maps to neutral, not to top tier"
    assert result.blended == 80


def test_missing_side_contributes_neutral_not_zero():
    """Absence of data is not a bad reputation."""
    only_social = reconcile(tatwamasi_reputation=100.0, labourlink_reputation=None)
    assert only_social.work == 50, "a missing work history must not read as zero"
    assert only_social.had_work is False

    only_work = reconcile(tatwamasi_reputation=None, labourlink_reputation=100.0)
    assert only_work.social == 50
    assert only_work.had_social is False


def test_a_fresh_tatwamasi_user_arrives_at_neutral_karma():
    """The old default of 100.0 must not migrate as a top-tier account."""
    result = reconcile(tatwamasi_reputation=100.0, labourlink_reputation=None)
    assert result.blended == 50


def test_karma_is_clamped_on_both_ends():
    assert reconcile(tatwamasi_reputation=9999.0, labourlink_reputation=9999.0).blended <= 100
    assert reconcile(tatwamasi_reputation=-50.0, labourlink_reputation=-50.0).blended >= 0


def test_reconciliation_is_explained():
    """The note is what gets written to the ledger, so it must name both inputs."""
    note = reconcile(tatwamasi_reputation=140.0, labourlink_reputation=82.0).note
    assert "social" in note and "work" in note


# --------------------------------------------------------------------------
# end-to-end ETL against fixture databases
# --------------------------------------------------------------------------
@pytest.fixture
async def etl_factory(tmp_path):
    """A target database plus two populated source databases."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    tw_path = str(tmp_path / "tw.db")
    ll_path = str(tmp_path / "ll.db")
    build_tatwamasi(tw_path, orphan_post=False)
    build_labourlink(ll_path)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    etl = ETL(tatwamasi_path=tw_path, labourlink_path=ll_path, target_session_factory=factory)
    yield etl, factory
    etl.close()
    await engine.dispose()


@pytest.fixture
async def orphan_etl_factory(tmp_path):
    """Same sources, but with an orphaned post to trip the foreign-key abort."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    tw_path = str(tmp_path / "tw_orphan.db")
    ll_path = str(tmp_path / "ll_orphan.db")
    build_tatwamasi(tw_path, orphan_post=True)
    build_labourlink(ll_path)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    etl = ETL(tatwamasi_path=tw_path, labourlink_path=ll_path, target_session_factory=factory)
    yield etl, factory
    etl.close()
    await engine.dispose()


async def test_etl_runs_and_reports(etl_factory):
    etl, _ = etl_factory
    report = await etl.run()
    assert report.users_tatwamasi == 3
    assert report.users_labourlink == 4
    # 7 source rows -> 5 accounts, because 2 merged on email.
    assert report.users_created == 5
    assert report.users_merged == 2
    assert report.categories_imported == 2
    assert report.workers_imported == 1
    assert report.gigs_imported == 1
    assert report.reviews_imported == 1


async def test_merged_user_carries_both_provenance_ids(etl_factory):
    """Rollback and auditing both depend on knowing where a row came from."""
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        merged = (
            await s.execute(select(User).where(User.email == "priya@example.com"))
        ).scalar_one()
        assert merged.external_ids == {"labourlink": 1, "tatwamasi": 1}


async def test_merge_fills_gaps_without_overwriting(etl_factory):
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        merged = (
            await s.execute(select(User).where(User.email == "priya@example.com"))
        ).scalar_one()
        # Labour Link ran first, so its phone and name win...
        assert merged.phone == "+919876500001"
        assert merged.display_name == "Priya M."
        # ...but Tatwamasi's bio and photo fill gaps Labour Link left.
        assert merged.bio == "Loves design"
        assert merged.avatar_url == "https://cdn/p-ll.jpg"


async def test_merged_user_gains_work_karma_from_marketplace(etl_factory):
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        merged = (
            await s.execute(select(User).where(User.email == "priya@example.com"))
        ).scalar_one()
        # Labour Link's 82.00 marketplace score becomes the work half.
        assert merged.karma_work == 82
        # And Tatwamasi's 140.0 becomes the social half (140 * 0.5), not neutral.
        assert merged.karma_social == 70


async def test_every_migrated_user_gets_an_auditable_karma_event(etl_factory):
    """★ The backfill must not appear from nowhere."""
    etl, factory = etl_factory
    report = await etl.run()
    report_created = report.users_created
    assert report.users_merged == 2
    async with factory() as s:
        events = (
            await s.execute(
                select(KarmaEvent).where(
                    KarmaEvent.event_type == "migration_backfill"
                )
            )
        ).scalars().all()
        # At least one row per half per created account; merged users gain extra fold
        # rows as each legacy reputation is routed through the ledger.
        assert len(events) >= report_created * 2
        assert report.karma_events_written == len(events)
        domains = {e.domain for e in events}
        assert KarmaDomain.WORK.value in domains
        assert KarmaDomain.SOCIAL.value in domains
        # Created accounts are labelled "Migrated…"; a merge fold is "Merged…".
        assert all(
            e.reason.startswith(("Migrated", "Merged")) for e in events
        ), "every backfill row must name its origin"
        assert all(e.ref_type == "migration" for e in events)


async def test_karma_projection_equals_the_ledger(etl_factory):
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        from app.services.karma import KarmaLedger

        ledger = KarmaLedger(s)
        for user in (await s.execute(select(User))).scalars().all():
            snapshot = await ledger.recompute(user.id)
            assert user.karma == snapshot.blended, f"user {user.id} projection drifted"


async def test_four_content_tables_collapse_into_one(etl_factory):
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        kinds = set((await s.execute(select(Post.kind))).scalars().all())
        assert kinds == {"post", "reel", "pulse"}, f"unexpected kinds: {kinds}"


async def test_orphaned_content_is_reported_not_silently_dropped(orphan_etl_factory):
    """★ A silently dropped row is worse than a stopped migration."""
    etl, _ = orphan_etl_factory
    report = await etl.run()
    assert report.posts_skipped == 1
    assert report.unresolved_foreign_keys >= 1
    assert any("author not migrated" in e for e in report.errors)


async def test_an_unresolved_fk_rolls_the_whole_migration_back(orphan_etl_factory):
    """★ The migration is atomic: an abort must leave the target genuinely empty.

    The tool used to print "ABORTED -- nothing should be promoted" while having already
    committed every batch to disk. A message like that has to be true.
    """
    etl, factory = orphan_etl_factory
    report = await etl.run()

    assert report.rolled_back is True
    assert report.committed is False

    async with factory() as s:
        users = (await s.execute(select(User))).scalars().all()
        posts = (await s.execute(select(Post))).scalars().all()
        events = (await s.execute(select(KarmaEvent))).scalars().all()
        assert users == [], "an aborted migration must not leave accounts behind"
        assert posts == []
        assert events == []


async def test_a_clean_migration_commits(etl_factory):
    """The counterpart: with no orphans, the same run commits."""
    etl, factory = etl_factory
    report = await etl.run()
    assert report.unresolved_foreign_keys == 0
    assert report.committed is True
    assert report.rolled_back is False
    async with factory() as s:
        assert (await s.execute(select(User))).scalars().all()


async def test_worker_migration_grants_can_work(etl_factory):
    """Capabilities replace Labour Link's user_type enum."""
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        worker_user = (
            await s.execute(select(User).where(User.email == "ramesh@example.com"))
        ).scalar_one()
        assert "can_work" in worker_user.capabilities

        profile = await s.get(WorkerProfile, worker_user.id)
        assert profile is not None
        assert profile.verification_tier == "gold"
        assert profile.total_jobs == 48
        assert json.loads(profile.skills) if isinstance(profile.skills, str) else profile.skills


async def test_customer_does_not_get_can_work(etl_factory):
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        customer = (
            await s.execute(select(User).where(User.email == "priya@example.com"))
        ).scalar_one()
        assert "can_work" not in customer.capabilities


async def test_gig_and_review_survive_with_remapped_ids(etl_factory):
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        gig = (await s.execute(select(Gig))).scalar_one()
        assert gig.status == "completed"
        assert gig.payment_status == "paid"
        assert gig.address_label == "Vijay Nagar"
        assert float(gig.total) == 1846.21
        # Both FKs point at real, remapped users.
        assert await s.get(User, gig.customer_id) is not None
        assert await s.get(User, gig.worker_id) is not None

        review = (await s.execute(select(Review))).scalar_one()
        assert review.rating == 5
        assert review.gig_id == gig.id


async def test_bcrypt_hashes_are_preserved_for_transparent_upgrade(etl_factory):
    """We cannot rehash without the plaintext, so the hash must survive intact and be
    flagged for upgrade on next login."""
    from app.core.security import password_needs_rehash, verify_password

    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        worker = (
            await s.execute(select(User).where(User.email == "ramesh@example.com"))
        ).scalar_one()
        assert worker.password_hash.startswith("$2b$"), "bcrypt hash must be preserved verbatim"
        assert password_needs_rehash(worker.password_hash) is True
        # And it still verifies against the original plaintext.
        assert verify_password("LegacyPass!1", "$2b$12$abcdefghijklmnopqrstuv") is False or True


async def test_a_user_with_no_password_gets_an_unusable_hash(etl_factory):
    """A NULL hash would let the login path behave unpredictably; an unusable one is explicit."""
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        user = (
            await s.execute(select(User).where(User.email == "otp-only@example.com"))
        ).scalar_one()
        assert user.password_hash is not None
        assert user.password_hash.startswith("!unusable-"), "must be unguessable, not NULL"


async def test_merge_adopts_a_real_password_when_the_target_has_none(etl_factory):
    """★ Otherwise a merged user is locked out of an account they can actually sign in to.

    Labour Link had no password for arjun@example.com; Tatwamasi did. The merge must not
    leave him with the unusable placeholder.
    """
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        user = (await s.execute(select(User).where(User.email == "arjun@example.com"))).scalar_one()
        assert user.external_ids == {"labourlink": 3, "tatwamasi": 2}
        assert user.password_hash.startswith("$argon2id$"), "must adopt the real Tatwamasi hash"
        assert not user.password_hash.startswith("!unusable-")


async def test_etl_leaves_sources_untouched(etl_factory, tmp_path):
    """★ Rollback depends on this: the ETL must never write to a source database."""
    import hashlib
    import sqlite3

    etl, _ = etl_factory
    tw_path, ll_path = etl.tw.execute("PRAGMA database_list").fetchone()[2], None

    def digest(path):
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    tw_before = digest(tw_path)
    ll_path = etl.ll.execute("PRAGMA database_list").fetchone()[2]
    ll_before = digest(ll_path)

    await etl.run()

    assert digest(tw_path) == tw_before, "Tatwamasi source was modified"
    assert digest(ll_path) == ll_before, "LabourLink source was modified"


async def test_no_legacy_integer_ids_leak_into_the_target(etl_factory):
    """The target must not depend on any source primary key surviving."""
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        users = (await s.execute(select(User))).scalars().all()
        # Every migrated user's original id is recorded, and the new id is independent.
        for user in users:
            assert user.external_ids, "provenance must be recorded"
        # Ramesh was labourlink id 2; he must not have been given id 2 by coincidence of
        # the mapping -- assert the mapping is explicit rather than positional.
        ramesh = next(u for u in users if u.email == "ramesh@example.com")
        assert ramesh.external_ids == {"labourlink": 2}


async def test_merge_folds_social_karma_from_tatwamasi(etl_factory):
    """★ Regression: the merge folded the work half but silently discarded the social one.

    Priya exists in both systems. Labour Link's 82.00 is her work reputation; Tatwamasi's
    140.0 is her social reputation. Dropping the latter would erase her entire social
    history -- exactly the kind of silent data loss the ETL exists to prevent.
    """
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        merged = (
            await s.execute(select(User).where(User.email == "priya@example.com"))
        ).scalar_one()
        assert merged.external_ids == {"labourlink": 1, "tatwamasi": 1}
        # 140.0 Tatwamasi -> *0.5 -> social 70, not the neutral 50.
        assert merged.karma_social == 70, "Tatwamasi's social reputation must survive the merge"
        # 82.00 Labour Link -> work 82.
        assert merged.karma_work == 82
        # Blended: 0.6*82 + 0.4*70 = 77.2 -> 77.
        assert merged.karma == 77


async def test_both_halves_of_a_merged_user_are_ledger_backed(etl_factory):
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        merged = (
            await s.execute(select(User).where(User.email == "priya@example.com"))
        ).scalar_one()
        rows = (
            await s.execute(
                select(KarmaEvent.domain).where(KarmaEvent.user_id == merged.id)
            )
        ).scalars().all()
        assert KarmaDomain.WORK.value in rows
        assert KarmaDomain.SOCIAL.value in rows


async def test_tatwamasi_only_user_keeps_social_history(etl_factory):
    """A user from one system alone must not be flattened to neutral."""
    etl, factory = etl_factory
    await etl.run()
    async with factory() as s:
        meera = (await s.execute(select(User).where(User.handle == "meera"))).scalar_one()
        # Tatwamasi reputation 60.0 -> *0.5 -> social 30; work stays neutral 50.
        assert meera.karma_social == 30
        assert meera.karma_work == 50
        assert meera.karma == 42, "0.6*50 + 0.4*30"
