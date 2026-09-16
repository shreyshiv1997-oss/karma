"""The merge ETL: two source databases in, one canonical KARMA database out.

Design constraints, all from Phase 1 §4:

  * **Sources are never mutated.** Both are opened read-only. Rollback is therefore
    "point the API back at the old database", not a restore from backup.
  * **IDs are remapped.** Every row gets a new surrogate id; the original primary key is
    preserved in ``users.external_ids`` as ``{"tatwamasi": 4217}``. Nothing downstream may
    depend on a legacy integer surviving.
  * **Dry-run by default.** Nothing is committed unless ``--commit`` is passed.
  * **The report is the sign-off artifact.** Counts per table plus the manual-review queue.
  * **Abort on an unresolved foreign key.** A silently dropped row is worse than a stopped
    migration.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.marketplace import Gig, ServiceCategory, WorkerProfile
from app.models.social import Post, PostKind
from app.models.trust import Review
from app.models.user import KarmaDomain, User
from app.services.karma import KarmaLedger
from etl.karma import NEUTRAL
from etl.identity import IdentityResolver, Resolution, SourceIdentity
from etl.karma import reconcile


@dataclass
class Report:
    users_tatwamasi: int = 0
    users_labourlink: int = 0
    users_created: int = 0
    users_merged: int = 0
    users_queued_for_review: int = 0
    posts_tatwamasi: int = 0
    posts_imported: int = 0
    posts_skipped: int = 0
    workers_imported: int = 0
    categories_imported: int = 0
    gigs_imported: int = 0
    reviews_imported: int = 0
    karma_events_written: int = 0
    # Counted at the login path, not here: the ETL cannot rehash without the
    # plaintext, so legacy bcrypt hashes are carried over and upgraded
    # transparently on the next successful sign-in (see app/core/security.py).
    # Kept in the report so the operator can see where that upgrade will land.
    passwords_rehashed: int = 0
    unresolved_foreign_keys: int = 0
    review_queue: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Set by run(): whether the transaction was committed or rolled back.
    committed: bool = False
    rolled_back: bool = False
    # Set by the CLI. `committed` describes the transaction, not the destination: a dry run
    # commits too, to a throwaway in-memory database. Without this flag the report would claim
    # `committed: true` on a run that wrote nothing, and the whole point of a dry run is that
    # the operator can read it and believe it.
    dry_run: bool = False

    @property
    def persisted(self) -> bool:
        """Whether anything reached a real database."""
        return self.committed and not self.dry_run

    def as_dict(self) -> dict:
        return {**self.__dict__, "persisted": self.persisted}


class ETL:
    def __init__(
        self,
        *,
        tatwamasi_path: str,
        labourlink_path: str,
        target_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.tw = sqlite3.connect(f"file:{tatwamasi_path}?mode=ro", uri=True)
        self.tw.row_factory = sqlite3.Row
        self.ll = sqlite3.connect(f"file:{labourlink_path}?mode=ro", uri=True)
        self.ll.row_factory = sqlite3.Row
        self.factory = target_session_factory
        self.resolver = IdentityResolver()
        self.report = Report()
        # (source, source_id) -> new KARMA user id
        self.user_map: dict[tuple[str, int], int] = {}
        self.category_map: dict[int, int] = {}
        # (source, source_id) -> new gig id
        self.gig_map: dict[tuple[str, int], int] = {}

    def close(self) -> None:
        self.tw.close()
        self.ll.close()

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    async def migrate_users(self, session: AsyncSession) -> None:
        """Labour Link first: it holds the verified phone, the stronger identifier."""
        for row in self.ll.execute("SELECT * FROM users ORDER BY id"):
            self.report.users_labourlink += 1
            await self._import_user(
                session,
                SourceIdentity(
                    source="labourlink",
                    source_id=row["id"],
                    phone=row["phone"],
                    email=row["email"],
                    handle=None,  # Labour Link has no handle; one is derived
                    display_name=row["full_name"] or f"User {row['id']}",
                    reputation=row["reputation_score"],
                    password_hash=row["password_hash"],
                ),
                labourlink_row=row,
            )

        for row in self.tw.execute("SELECT * FROM users ORDER BY id"):
            self.report.users_tatwamasi += 1
            await self._import_user(
                session,
                SourceIdentity(
                    source="tatwamasi",
                    source_id=row["id"],
                    phone=None,  # Tatwamasi never collected a phone number
                    email=row["email"],
                    handle=row["username"],
                    display_name=row["display_name"] or row["username"],
                    reputation=row["reputation_score"],
                    password_hash=row["hashed_password"],
                ),
                tatwamasi_row=row,
            )

    async def _import_user(
        self,
        session: AsyncSession,
        identity: SourceIdentity,
        *,
        labourlink_row: sqlite3.Row | None = None,
        tatwamasi_row: sqlite3.Row | None = None,
    ) -> None:
        resolution: Resolution = self.resolver.resolve(identity)

        if resolution.decision == "merge" and resolution.merge_into:
            target = await self._find_existing(session, resolution.merge_into)
            if target is None:
                self.report.errors.append(
                    f"merge target {resolution.merge_into} vanished; creating instead"
                )
                target = await self._create_user(
                    session, identity, resolution, labourlink_row, tatwamasi_row
                )
            else:
                await self._fold_into(
                    target, identity, labourlink_row, tatwamasi_row, session=session
                )
                self.report.users_merged += 1
            self.user_map[(identity.source, identity.source_id)] = target.id
            await session.flush()
            return

        if resolution.decision == "review":
            # Ambiguous identity: do NOT guess. Create a separate account so no data
            # is lost, and flag it for a human.
            self.report.users_queued_for_review += 1

        user = await self._create_user(
            session, identity, resolution, labourlink_row, tatwamasi_row
        )
        self.user_map[(identity.source, identity.source_id)] = user.id
        await session.flush()

    async def _find_existing(self, session: AsyncSession, canonical_key: str) -> User | None:
        source, _, sid = canonical_key.partition(":")
        new_id = self.user_map.get((source, int(sid)))
        if new_id is None:
            return None
        return await session.get(User, new_id)

    async def _create_user(
        self,
        session: AsyncSession,
        identity: SourceIdentity,
        resolution: Resolution,
        labourlink_row: sqlite3.Row | None,
        tatwamasi_row: sqlite3.Row | None,
    ) -> User:
        karma = reconcile(
            tatwamasi_reputation=tatwamasi_row["reputation_score"] if tatwamasi_row else None,
            labourlink_reputation=labourlink_row["reputation_score"] if labourlink_row else None,
        )

        handle = resolution.new_handle or _norm_handle(identity.handle) or _derive_handle(identity)
        # Legacy bcrypt hashes are carried over verbatim; they cannot be rehashed
        # without the plaintext and the login path upgrades them transparently.
        password_hash = identity.password_hash

        user = User(
            handle=handle,
            display_name=identity.display_name,
            email=identity.email,
            phone=identity.phone,
            password_hash=password_hash or _random_unusable_password(),
            bio=(tatwamasi_row["bio"] if tatwamasi_row and tatwamasi_row["bio"] else ""),
            avatar_url=(
                (tatwamasi_row["photo_url"] if tatwamasi_row else None)
                or (labourlink_row["avatar_url"] if labourlink_row else None)
            ),
            city=(tatwamasi_row["location"] if tatwamasi_row else None),
            capabilities=["can_post", "can_follow", "can_chat"],
            is_verified=bool(
                (labourlink_row["is_verified"] if labourlink_row else False)
                or (tatwamasi_row["is_verified"] if tatwamasi_row else False)
            ),
            karma=karma.blended,
            karma_work=karma.work,
            karma_social=karma.social,
            reputation_score=float(karma.blended),
            followers_count=int(tatwamasi_row["followers_count"] or 0) if tatwamasi_row else 0,
            following_count=int(tatwamasi_row["following_count"] or 0) if tatwamasi_row else 0,
            posts_count=int(tatwamasi_row["posts_count"] or 0) if tatwamasi_row else 0,
            streak=int(tatwamasi_row["streak"] or 0) if tatwamasi_row else 0,
            external_ids={identity.source: identity.source_id},
        )
        session.add(user)
        await session.flush()

        # The backfill is auditable: each half arrives as its own ledger row carrying
        # the delta from neutral. Writing the projection alone would be overwritten the
        # next time the ledger is recomputed.
        ledger = KarmaLedger(session)
        await ledger.record_backfill(
            user.id,
            delta=karma.work - NEUTRAL,
            domain=KarmaDomain.WORK,
            reason=f"Migrated work reputation from {identity.source} ({karma.note})",
            meta={"source": identity.source, "source_id": identity.source_id, "target": karma.work},
        )
        await ledger.record_backfill(
            user.id,
            delta=karma.social - NEUTRAL,
            domain=KarmaDomain.SOCIAL,
            reason=f"Migrated social reputation from {identity.source} ({karma.note})",
            meta={"source": identity.source, "source_id": identity.source_id, "target": karma.social},
        )
        self.report.karma_events_written += 2
        self.report.users_created += 1
        return user

    async def _fold_into(
        self,
        target: User,
        identity: SourceIdentity,
        labourlink_row: sqlite3.Row | None,
        tatwamasi_row: sqlite3.Row | None,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        """Merge a second source row into an existing account without losing either."""
        external = dict(target.external_ids or {})
        external[identity.source] = identity.source_id
        target.external_ids = external

        # Fill gaps only; never overwrite a value the canonical record already has.
        if not target.phone and identity.phone:
            target.phone = identity.phone
        if not target.email and identity.email:
            target.email = identity.email
        if not target.avatar_url:
            target.avatar_url = (
                (tatwamasi_row["photo_url"] if tatwamasi_row else None)
                or (labourlink_row["avatar_url"] if labourlink_row else None)
            )
        if not target.bio and tatwamasi_row and tatwamasi_row["bio"]:
            target.bio = tatwamasi_row["bio"]

        # If the canonical account has no usable password but this row does, adopt it --
        # otherwise a merged user is locked out of an account they can actually sign in to.
        if identity.password_hash and _is_unusable(target.password_hash):
            target.password_hash = identity.password_hash

        # Fold each legacy reputation into its own half, routed through the ledger.
        # Assigning the projection directly would be overwritten on the next recompute.
        if labourlink_row is not None and labourlink_row["reputation_score"] is not None:
            ll_karma = reconcile(
                tatwamasi_reputation=None,
                labourlink_reputation=labourlink_row["reputation_score"],
            )
            delta = ll_karma.work - target.karma_work
            if delta:
                await KarmaLedger(session).record_backfill(
                    target.id,
                    delta=delta,
                    domain=KarmaDomain.WORK,
                    reason=f"Merged marketplace reputation from {identity.source}",
                    meta={"source": identity.source, "source_id": identity.source_id},
                )
                self.report.karma_events_written += 1

        if tatwamasi_row is not None and tatwamasi_row["reputation_score"] is not None:
            tw_karma = reconcile(
                tatwamasi_reputation=tatwamasi_row["reputation_score"],
                labourlink_reputation=None,
            )
            delta = tw_karma.social - target.karma_social
            if delta:
                await KarmaLedger(session).record_backfill(
                    target.id,
                    delta=delta,
                    domain=KarmaDomain.SOCIAL,
                    reason=f"Merged social reputation from {identity.source}",
                    meta={"source": identity.source, "source_id": identity.source_id},
                )
                self.report.karma_events_written += 1

    # ------------------------------------------------------------------
    # catalogue, workers, gigs
    # ------------------------------------------------------------------
    async def migrate_categories(self, session: AsyncSession) -> None:
        rows = list(self.ll.execute("SELECT * FROM categories ORDER BY id"))
        for row in rows:
            cat = ServiceCategory(
                name=row["name"],
                slug=row["slug"] or _slugify(row["name"]),
                description=row["description"] or "",
                base_fare=Decimal(str(row["base_fare"])),
                per_km_rate=Decimal(str(row["per_km_rate"])),
                per_hour_rate=Decimal(str(row["per_minute_rate"] or 0)) * 60
                or Decimal("350"),
                urgency_multiplier=Decimal(str(row["urgency_multiplier"] or "1.25")),
                night_multiplier=Decimal(str(row["night_multiplier"] or "1.15")),
            )
            session.add(cat)
            await session.flush()
            self.category_map[row["id"]] = cat.id
            self.report.categories_imported += 1
        await session.flush()

    async def migrate_workers(self, session: AsyncSession) -> None:
        rows = list(self.ll.execute("SELECT * FROM laborers ORDER BY user_id"))
        for row in rows:
            new_user_id = self.user_map.get(("labourlink", row["user_id"]))
            if new_user_id is None:
                self.report.unresolved_foreign_keys += 1
                self.report.errors.append(
                    f"laborer for labourlink user {row['user_id']} has no mapped user"
                )
                continue
            new_category_id = self.category_map.get(row["category_id"])
            if new_category_id is None:
                self.report.unresolved_foreign_keys += 1
                self.report.errors.append(
                    f"laborer category {row['category_id']} was not migrated"
                )
                continue

            session.add(
                WorkerProfile(
                    user_id=new_user_id,
                    category_id=new_category_id,
                    hourly_rate=Decimal(str(row["hourly_rate"])),
                    rating=float(row["rating"] or 5.0),
                    total_jobs=int(row["total_jobs"] or 0),
                    verification_tier=row["verification_tier"] or "bronze",
                    background_check_status=row["background_check_status"] or "not_started",
                    approved_at=_parse_dt(row["approved_at"]),
                    bio=row["bio"] or "",
                    skills=json.loads(row["skills"]) if row["skills"] else [],
                    avg_response_time_seconds=int(row["avg_response_time_seconds"] or 900),
                )
            )
            user = await session.get(User, new_user_id)
            if user is not None and "can_work" not in set(user.capabilities or []):
                user.capabilities = sorted({*(user.capabilities or []), "can_work"})
            self.report.workers_imported += 1
        await session.flush()

    async def migrate_gigs(self, session: AsyncSession) -> None:
        rows = list(self.ll.execute("SELECT * FROM jobs ORDER BY id"))
        for row in rows:
            customer_id = self.user_map.get(("labourlink", row["customer_id"]))
            if customer_id is None:
                self.report.unresolved_foreign_keys += 1
                self.report.errors.append(f"job {row['id']}: unmapped customer")
                continue
            category_id = self.category_map.get(row["category_id"])
            if category_id is None:
                self.report.unresolved_foreign_keys += 1
                self.report.errors.append(f"job {row['id']}: unmapped category")
                continue

            worker_id = None
            if row["laborer_id"] is not None:
                worker_id = self.user_map.get(("labourlink", row["laborer_id"]))
                if worker_id is None:
                    self.report.unresolved_foreign_keys += 1
                    self.report.errors.append(f"job {row['id']}: unmapped laborer")
                    continue

            location = json.loads(row["pickup_location"]) if row["pickup_location"] else {}
            fare = json.loads(row["fare_breakdown"]) if row["fare_breakdown"] else {}

            gig = Gig(
                customer_id=customer_id,
                worker_id=worker_id,
                category_id=category_id,
                title=(json.loads(row["job_details"]).get("title") if row["job_details"] else "")
                or f"Migrated job #{row['id']}",
                description=json.loads(row["job_details"]).get("description", "")
                if row["job_details"]
                else "",
                status=row["status"] or "searching",
                urgency=row["urgency"] or "standard",
                lat=float(location.get("lat") or 0.0),
                lng=float(location.get("lng") or 0.0),
                address_label=location.get("address", "") or "",
                fare_breakdown=fare,
                total=Decimal(str(fare.get("total") or 0)),
                photos=json.loads(row["photos"]) if row["photos"] else [],
                payment_status=row["payment_status"] or "pending",
                created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
                completed_at=_parse_dt(row["completed_at"]),
            )
            session.add(gig)
            await session.flush()
            self.gig_map[("labourlink", row["id"])] = gig.id
            self.report.gigs_imported += 1
        await session.flush()

    async def migrate_reviews(self, session: AsyncSession) -> None:
        rows = list(self.ll.execute("SELECT * FROM reviews ORDER BY id"))
        for row in rows:
            gig_id = self.gig_map.get(("labourlink", row["job_id"]))
            reviewer = self.user_map.get(("labourlink", row["reviewer_id"]))
            reviewee = self.user_map.get(("labourlink", row["reviewee_id"]))
            if None in (gig_id, reviewer, reviewee):
                self.report.unresolved_foreign_keys += 1
                self.report.errors.append(f"review {row['id']}: unresolved foreign key")
                continue
            session.add(
                Review(
                    gig_id=gig_id,
                    reviewer_id=reviewer,
                    reviewee_id=reviewee,
                    rating=int(row["rating"] or 5),
                    punctuality=row["punctuality"],
                    quality=row["quality"],
                    communication=row["communication"],
                    comment=row["comment"] or "",
                    created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
                )
            )
            self.report.reviews_imported += 1
        await session.flush()

    # ------------------------------------------------------------------
    # content: four Tatwamasi tables -> one posts table
    # ------------------------------------------------------------------
    async def migrate_posts(self, session: AsyncSession) -> None:
        """Collapse posts/reels/stories/tweets into one table with a kind discriminator.

        They were ~90% identical columns in the source; keeping them apart is exactly the
        Frankenstein seam the merge exists to remove.
        """
        mapping = [
            ("posts", PostKind.POST.value, "content", "media_urls"),
            ("reels", PostKind.REEL.value, "caption", None),
            ("tweets", PostKind.PULSE.value, "content", None),
        ]
        for table, kind, body_col, media_col in mapping:
            if not _table_exists(self.tw, table):
                continue
            rows = list(self.tw.execute(f"SELECT * FROM {table} ORDER BY id"))
            self.report.posts_tatwamasi += len(rows)
            for row in rows:
                new_author = self.user_map.get(("tatwamasi", row["user_id"]))
                if new_author is None:
                    self.report.unresolved_foreign_keys += 1
                    self.report.posts_skipped += 1
                    self.report.errors.append(
                        f"{table} {row['id']}: author not migrated"
                    )
                    continue

                media: list[str] = []
                if media_col and row[media_col]:
                    media = json.loads(row[media_col])
                elif table == "reels" and row["video_url"]:
                    media = [row["video_url"]]

                body = row[body_col] if body_col in row.keys() else ""
                hashtags = json.loads(row["hashtags"]) if "hashtags" in row.keys() and row["hashtags"] else []

                session.add(
                    Post(
                        author_id=new_author,
                        kind=kind,
                        body=body or "",
                        media_urls=media,
                        hashtags=hashtags,
                        likes_count=int(row["likes_count"] or 0) if "likes_count" in row.keys() else 0,
                        comments_count=int(row["comments_count"] or 0) if "comments_count" in row.keys() else 0,
                        created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
                    )
                )
                self.report.posts_imported += 1
            await session.flush()

    # ------------------------------------------------------------------
    async def run(self) -> Report:
        """Run the whole migration inside ONE transaction.

        A migration that half-applies is worse than one that does not apply at all: the
        operator is left with a database they cannot trust and cannot easily distinguish
        from a good one. So every stage shares a session, and an unresolved foreign key
        rolls the lot back rather than leaving orphans behind.
        """
        async with self.factory() as session:
            await self.migrate_users(session)
            await self.migrate_categories(session)
            await self.migrate_workers(session)
            await self.migrate_gigs(session)
            await self.migrate_reviews(session)
            await self.migrate_posts(session)

            if self.report.unresolved_foreign_keys:
                await session.rollback()
                self.report.rolled_back = True
            else:
                await session.commit()
                self.report.committed = True

        self.report.review_queue = list(self.resolver.queue)
        return self.report


# ── helpers -----------------------------------------------------------------
def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _norm_handle(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip().lower().replace(" ", "_")
    return cleaned or None


def _derive_handle(identity: SourceIdentity) -> str:
    from etl.identity import _derive_handle as derive

    return derive(identity)


def _slugify(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")


def _parse_dt(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _is_unusable(password_hash: str | None) -> bool:
    return not password_hash or password_hash.startswith("!unusable-")


def _random_unusable_password() -> str:
    """A source row with no password gets a hash nobody can reproduce.

    Better than NULL: a NULL hash would make ``verify_password`` return False anyway, but
    an unusable hash makes the intent explicit and survives any future NOT NULL change.
    """
    import secrets

    return f"!unusable-{secrets.token_urlsafe(24)}"


async def create_target_schema(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge Tatwamasi + LabourLink into KARMA")
    parser.add_argument("--tatwamasi", required=True, help="Path to the Tatwamasi SQLite/PG dump")
    parser.add_argument("--labourlink", required=True, help="Path to the LabourLink SQLite/PG dump")
    parser.add_argument(
        "--target", default="sqlite+aiosqlite:///./karma_migrated.db", help="Target database URL"
    )
    parser.add_argument(
        "--commit", action="store_true", help="Actually write. Without this, nothing is persisted."
    )
    args = parser.parse_args(argv)

    if args.commit:
        factory = await create_target_schema(args.target)
    else:
        # Dry run against a throwaway in-memory database: same code path, no side effects.
        factory = await create_target_schema("sqlite+aiosqlite:///:memory:")
        print("[dry-run] writing to an in-memory database; nothing is persisted\n")

    etl = ETL(
        tatwamasi_path=args.tatwamasi, labourlink_path=args.labourlink, target_session_factory=factory
    )
    try:
        report = await etl.run()
    finally:
        etl.close()

    report.dry_run = not args.commit
    print(json.dumps(report.as_dict(), indent=2, default=str))

    if report.unresolved_foreign_keys:
        print(
            f"\nABORTED: {report.unresolved_foreign_keys} unresolved foreign key(s). "
            "Nothing should be promoted until these are explained."
        )
        return 1
    if report.review_queue:
        print(f"\n{len(report.review_queue)} identity conflict(s) need a human decision.")

    # Say plainly whether anything reached a database. `committed: true` alone would be read
    # as "the target was written" even on a dry run, which commits to memory and discards it.
    if report.persisted:
        print(f"\nCOMMITTED to {args.target}")
    else:
        print("\nDRY RUN: nothing was written. Re-run with --commit to persist.")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
