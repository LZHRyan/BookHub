"""media assets

新增媒体资源表（只加表，不动既有表）。

Revision ID: 0007_media_assets
Revises: 0006_admin_api
Create Date: 2026-10-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_media_assets"
down_revision = "0006_admin_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("stored_name", sa.String(length=200), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="attachment"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_media_assets_book_id", "media_assets", ["book_id"])
    op.create_index("ix_media_book_active", "media_assets", ["book_id", "deleted_at"])
    op.create_index("ix_media_checksum", "media_assets", ["book_id", "checksum"])
    op.create_index("ix_media_assets_stored_name", "media_assets", ["stored_name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_media_assets_stored_name", table_name="media_assets")
    op.drop_index("ix_media_checksum", table_name="media_assets")
    op.drop_index("ix_media_book_active", table_name="media_assets")
    op.drop_index("ix_media_assets_book_id", table_name="media_assets")
    op.drop_table("media_assets")
