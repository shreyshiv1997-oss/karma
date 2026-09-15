"""add users.token_version and one-reversal-per-penalty on the karma ledger

Revision ID: b7f3d1c4a9e8
Revises: c4a1d8e6f250
Create Date: 2026-09-14 00:00:00.000000+00:00

Two independent additions, one revision, because both are "the ledger and the session can no
longer be told the same thing twice":

* ``users.token_version`` is the session epoch. Every token now carries it as its ``ver`` claim,
  so advancing it invalidates every token issued before the bump. That is how
  ``POST /auth/logout-all`` ends all sessions in one write, without a revocation table that grows
  with logins. ``server_default='0'`` is load-bearing twice over: existing rows need a value, and
  tokens minted before this claim existed read as version 0 -- so the migration cannot log
  anybody out, and a live session survives its own upgrade until an actual logout.
* a partial unique index on ``karma_events`` makes "an exoneration reverses a penalty at most
  once" a database fact. ``recompute()`` sums the table, so a double-dismissed dispute that
  appended two reversals would credit karma back twice with nothing downstream able to notice.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b7f3d1c4a9e8"
down_revision: str | None = "c4a1d8e6f250"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "token_version",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )

    op.create_index(
        "uq_karma_reversal_target",
        "karma_events",
        ["ref_type", "ref_id"],
        unique=True,
        sqlite_where=sa.text("ref_type = 'karma_reversal'"),
        postgresql_where=sa.text("ref_type = 'karma_reversal'"),
    )


def downgrade() -> None:
    op.drop_index("uq_karma_reversal_target", table_name="karma_events")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_version")
