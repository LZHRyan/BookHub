"""webhooks

登记外部回调地址与投递记录两张表。

Revision ID: 0013_webhooks
Revises: 0012_token_book_scope
Create Date: 2026-10-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_webhooks"
down_revision = "0012_token_book_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("secret", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("events", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("description", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("last_sent_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "webhook_id",
            sa.Integer(),
            sa.ForeignKey("webhooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_webhook_deliveries_hook", "webhook_deliveries", ["webhook_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_hook", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_table("webhooks")
