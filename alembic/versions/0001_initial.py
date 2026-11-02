"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="editor"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("icon", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="public"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "uq_books_slug_active",
        "books",
        ["slug"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_books_listing", "books", ["deleted_at", "visibility", "sort_order"])

    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="markdown"),
        sa.Column("content_raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_safe", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_rendered", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_toc", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("content_checksum", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("current_version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_chapters_book_id", "chapters", ["book_id"])
    op.create_index(
        "uq_chapters_book_slug_active",
        "chapters",
        ["book_id", "slug"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_chapters_order", "chapters", ["book_id", "deleted_at", "sort_order"])
    op.create_index("ix_chapters_changes", "chapters", ["updated_at"])

    op.create_table(
        "chapter_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "chapter_id",
            sa.Integer(),
            sa.ForeignKey("chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="markdown"),
        sa.Column("content_raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("chapter_id", "version_no", name="uq_chapter_version"),
    )
    op.create_index("ix_chapter_versions_chapter_id", "chapter_versions", ["chapter_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("target_label", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("ip", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_created", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_book_id", "audit_logs", ["book_id"])

    op.create_table(
        "site_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chapter_fts USING fts5("
            "title, body, tokenize='unicode61 remove_diacritics 2')"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TABLE IF EXISTS chapter_fts")
    op.drop_table("site_settings")
    op.drop_table("audit_logs")
    op.drop_table("chapter_versions")
    op.drop_table("chapters")
    op.drop_table("books")
    op.drop_table("users")
