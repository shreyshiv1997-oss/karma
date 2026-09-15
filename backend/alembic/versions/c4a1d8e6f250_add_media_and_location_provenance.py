"""add media objects and explicit location provenance

Revision ID: c4a1d8e6f250
Revises: 9f3c2a7d1b40
Create Date: 2026-09-14

Media bytes live in local/S3 object storage; this table records immutable metadata, ownership,
and purpose. Gig and worker coordinates record whether they came from a consented device fix or
an explicitly selected geocoder result rather than an invented service-area centre.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a1d8e6f250"
down_revision: str | None = "9f3c2a7d1b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_objects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_media_objects_owner_id", "media_objects", ["owner_id"])
    op.create_index("ix_media_objects_purpose", "media_objects", ["purpose"])
    op.create_index("ix_media_objects_status", "media_objects", ["status"])
    op.create_index(
        "ix_media_objects_owner_created",
        "media_objects",
        ["owner_id", "created_at"],
    )

    op.add_column(
        "gigs",
        sa.Column(
            "location_source",
            sa.String(length=16),
            server_default="provided",
            nullable=False,
        ),
    )
    op.add_column("gigs", sa.Column("location_accuracy_m", sa.Float(), nullable=True))
    op.add_column("gigs", sa.Column("geocoder", sa.String(length=64), nullable=True))

    op.add_column(
        "worker_profiles",
        sa.Column("location_source", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "worker_profiles",
        sa.Column("location_accuracy_m", sa.Float(), nullable=True),
    )
    op.add_column(
        "worker_profiles",
        sa.Column("location_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("worker_profiles", "location_updated_at")
    op.drop_column("worker_profiles", "location_accuracy_m")
    op.drop_column("worker_profiles", "location_source")

    op.drop_column("gigs", "geocoder")
    op.drop_column("gigs", "location_accuracy_m")
    op.drop_column("gigs", "location_source")

    op.drop_index("ix_media_objects_owner_created", table_name="media_objects")
    op.drop_index("ix_media_objects_status", table_name="media_objects")
    op.drop_index("ix_media_objects_purpose", table_name="media_objects")
    op.drop_index("ix_media_objects_owner_id", table_name="media_objects")
    op.drop_table("media_objects")
