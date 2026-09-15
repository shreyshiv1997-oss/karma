# FIXED: Proof posts are unfakeable (kind=proof requires gig_id) — schema-level
# CHECK constraint so every writer is bound, not just the request schema.
"""proof posts require a gig

Revision ID: 7c1e4b2af903
Revises: 50dc766b719f
Create Date: 2026-09-01

Closes the "proof posts are unfakeable" loophole at the schema level.

Before this, `kind='proof'` was constrained only by a regex on the `PostCreate` request
schema. That guards exactly one code path. Every other writer -- the seed script (which
did exactly this), an ETL backfill, a future endpoint, an operator at a psql prompt --
could insert a proof post with no gig behind it, and the feed rendered it identically to
real evidence of paid work. Proof is the product's trust primitive; it belongs in the
schema, where every writer has to pass through it.

The `payment_status='paid'` half of the invariant is cross-table and stays in
`gigs._complete_gig`, which is now the sole writer of `kind='proof'`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "7c1e4b2af903"
down_revision: str | None = "50dc766b719f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "ck_posts_proof_requires_gig"
CONDITION = "kind <> 'proof' OR gig_id IS NOT NULL"


def upgrade() -> None:
    # Any pre-existing unbacked proof post would make the constraint unaddable. They are
    # not evidence of anything -- there is no gig and therefore no payment behind them --
    # so they are demoted to ordinary posts rather than deleted, which preserves the
    # author's content and their post count while removing the false trust signal.
    op.execute(
        f"UPDATE posts SET kind = 'post' WHERE kind = 'proof' AND gig_id IS NULL"
    )

    # SQLite cannot ALTER TABLE ADD CONSTRAINT; batch mode rebuilds the table.
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.create_check_constraint(CONSTRAINT_NAME, CONDITION)


def downgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_="check")
