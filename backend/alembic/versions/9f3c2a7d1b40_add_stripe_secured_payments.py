"""add Stripe secured payments

Revision ID: 9f3c2a7d1b40
Revises: 4e7b1c9d2a10
Create Date: 2026-09-13

PaymentIntent state is durable and webhook ids are retained as content-free receipts. Ledger
provider references are unique so API reconciliation and Stripe's at-least-once webhooks cannot
release the same money twice.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9f3c2a7d1b40"
down_revision: str | None = "4e7b1c9d2a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ledger_entries",
        sa.Column("external_reference", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_ledger_entries_external_reference",
        "ledger_entries",
        ["external_reference"],
        unique=True,
    )

    op.create_table(
        "gig_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gig_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_payment_intent_id", sa.String(length=255), nullable=False),
        sa.Column("provider_charge_id", sa.String(length=255), nullable=True),
        sa.Column("provider_refund_id", sa.String(length=255), nullable=True),
        sa.Column("provider_status", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("platform_fee", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("worker_payout", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("last_event_created", sa.BigInteger(), nullable=False),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.String(length=240), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["gig_id"], ["gigs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gig_id", name="uq_gig_payments_gig"),
        sa.UniqueConstraint(
            "provider_payment_intent_id",
            name="uq_gig_payments_provider_intent",
        ),
    )
    for column in (
        "customer_id",
        "gig_id",
        "provider_charge_id",
        "provider_payment_intent_id",
        "provider_refund_id",
        "status",
        "worker_id",
    ):
        op.create_index(
            f"ix_gig_payments_{column}",
            "gig_payments",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_gig_payments_status_updated",
        "gig_payments",
        ["status", "updated_at"],
        unique=False,
    )

    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("provider_created", sa.BigInteger(), nullable=False),
        sa.Column("object_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("event_type", "object_id", "received_at"):
        op.create_index(
            f"ix_stripe_webhook_events_{column}",
            "stripe_webhook_events",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in reversed(("event_type", "object_id", "received_at")):
        op.drop_index(
            f"ix_stripe_webhook_events_{column}",
            table_name="stripe_webhook_events",
        )
    op.drop_table("stripe_webhook_events")

    op.drop_index("ix_gig_payments_status_updated", table_name="gig_payments")
    for column in reversed(
        (
            "customer_id",
            "gig_id",
            "provider_charge_id",
            "provider_payment_intent_id",
            "provider_refund_id",
            "status",
            "worker_id",
        )
    ):
        op.drop_index(f"ix_gig_payments_{column}", table_name="gig_payments")
    op.drop_table("gig_payments")

    op.drop_index(
        "ix_ledger_entries_external_reference",
        table_name="ledger_entries",
    )
    op.drop_column("ledger_entries", "external_reference")
