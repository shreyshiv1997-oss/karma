"""add Bitchat ephemeral mesh relay

Revision ID: 4e7b1c9d2a10
Revises: 7c1e4b2af903
Create Date: 2026-09-13

Only public keys, routing metadata and authenticated ciphertext enter these tables. Message
keys and plaintext remain on clients. ``expires_at`` is indexed because expiry is enforced by
a physical sweeper, not merely hidden at read time.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4e7b1c9d2a10"
down_revision: str | None = "7c1e4b2af903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bitchat_devices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("identity_key", sa.String(length=44), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bitchat_devices_last_seen_at",
        "bitchat_devices",
        ["last_seen_at"],
        unique=False,
    )
    op.create_index(
        "ix_bitchat_devices_revoked_at",
        "bitchat_devices",
        ["revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_bitchat_devices_user_active",
        "bitchat_devices",
        ["user_id", "revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_bitchat_devices_user_id",
        "bitchat_devices",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "bitchat_conversations",
        sa.Column("gig_id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["gig_id"], ["gigs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("gig_id"),
    )
    op.create_index(
        "ix_bitchat_conversations_room_id",
        "bitchat_conversations",
        ["room_id"],
        unique=True,
    )

    op.create_table(
        "bitchat_prekeys",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("public_key", sa.String(length=44), nullable=False),
        sa.Column("signature", sa.String(length=88), nullable=False),
        sa.Column("claimed_by_device_id", sa.String(length=36), nullable=True),
        sa.Column("claimed_gig_id", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["bitchat_devices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["claimed_gig_id"], ["gigs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id", "key_id"),
    )
    op.create_index(
        "ix_bitchat_prekeys_claimed_at",
        "bitchat_prekeys",
        ["claimed_at"],
        unique=False,
    )
    op.create_index(
        "ix_bitchat_prekeys_claimed_by_device_id",
        "bitchat_prekeys",
        ["claimed_by_device_id"],
        unique=False,
    )
    op.create_index(
        "ix_bitchat_prekeys_claimed_gig_id",
        "bitchat_prekeys",
        ["claimed_gig_id"],
        unique=False,
    )
    op.create_index(
        "ix_bitchat_prekeys_consumed_at",
        "bitchat_prekeys",
        ["consumed_at"],
        unique=False,
    )

    op.create_table(
        "bitchat_envelopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("gig_id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.String(length=36), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("sender_device_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("recipient_device_id", sa.String(length=36), nullable=False),
        sa.Column("prekey_id", sa.Integer(), nullable=False),
        sa.Column("ephemeral_key", sa.String(length=44), nullable=False),
        sa.Column("nonce", sa.String(length=16), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("mac", sa.String(length=24), nullable=False),
        sa.Column("signature", sa.String(length=88), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("max_hops", sa.Integer(), nullable=False),
        sa.Column("transport", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["gig_id"], ["gigs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["recipient_device_id"], ["bitchat_devices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["sender_device_id"], ["bitchat_devices.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "recipient_device_id",
            name="uq_bitchat_message_recipient",
        ),
    )
    for column in (
        "expires_at",
        "gig_id",
        "message_id",
        "recipient_device_id",
        "recipient_id",
        "room_id",
        "sender_device_id",
        "sender_id",
    ):
        op.create_index(
            f"ix_bitchat_envelopes_{column}",
            "bitchat_envelopes",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_bitchat_envelopes_recipient_expiry",
        "bitchat_envelopes",
        ["recipient_device_id", "expires_at"],
        unique=False,
    )

    op.create_table(
        "bitchat_panic_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gig_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["gig_id"], ["gigs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("created_at", "device_id", "gig_id", "user_id"):
        op.create_index(
            f"ix_bitchat_panic_events_{column}",
            "bitchat_panic_events",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("created_at", "device_id", "gig_id", "user_id"):
        op.drop_index(
            f"ix_bitchat_panic_events_{column}",
            table_name="bitchat_panic_events",
        )
    op.drop_table("bitchat_panic_events")

    op.drop_index(
        "ix_bitchat_envelopes_recipient_expiry", table_name="bitchat_envelopes"
    )
    for column in reversed(
        (
            "expires_at",
            "gig_id",
            "message_id",
            "recipient_device_id",
            "recipient_id",
            "room_id",
            "sender_device_id",
            "sender_id",
        )
    ):
        op.drop_index(f"ix_bitchat_envelopes_{column}", table_name="bitchat_envelopes")
    op.drop_table("bitchat_envelopes")

    op.drop_index("ix_bitchat_prekeys_consumed_at", table_name="bitchat_prekeys")
    op.drop_index("ix_bitchat_prekeys_claimed_gig_id", table_name="bitchat_prekeys")
    op.drop_index(
        "ix_bitchat_prekeys_claimed_by_device_id", table_name="bitchat_prekeys"
    )
    op.drop_index("ix_bitchat_prekeys_claimed_at", table_name="bitchat_prekeys")
    op.drop_table("bitchat_prekeys")

    op.drop_index(
        "ix_bitchat_conversations_room_id", table_name="bitchat_conversations"
    )
    op.drop_table("bitchat_conversations")

    op.drop_index("ix_bitchat_devices_user_id", table_name="bitchat_devices")
    op.drop_index("ix_bitchat_devices_user_active", table_name="bitchat_devices")
    op.drop_index("ix_bitchat_devices_revoked_at", table_name="bitchat_devices")
    op.drop_index("ix_bitchat_devices_last_seen_at", table_name="bitchat_devices")
    op.drop_table("bitchat_devices")
