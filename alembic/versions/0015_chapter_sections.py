"""chapter sections

把「章」拆成「章（目录行）+ 节（正文/版本）」，并删除分卷。

数据按约定可丢弃：本迁移不搬运正文与版本，直接重建表结构。
若库里已有内容，`chapters` 会被清空（正文/版本随之丢弃），需要保留请先自行导出。

Revision ID: 0015_chapter_sections
Revises: 0014_book_groups
Create Date: 2026-10-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0015_chapter_sections"
down_revision = "0014_book_groups"
branch_labels = None
depends_on = None

DROP_COLUMNS = (
    "parent_id",
    "kind",
    "format",
    "content_raw",
    "content_safe",
    "content_rendered",
    "content_toc",
    "content_checksum",
    "word_count",
    "current_version_no",
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. 旧版本表与章节正文一起丢弃（数据可抹除）
    op.drop_table("chapter_versions")
    bind.execute(sa.text("DELETE FROM chapters"))

    # 2. chapters 瘦身：只剩目录行与发布状态
    existing = {index["name"] for index in sa.inspect(bind).get_indexes("chapters")}
    for name in ("ix_chapters_tree", "ix_chapters_parent_id"):
        if name in existing:
            op.drop_index(name, table_name="chapters")
    with op.batch_alter_table("chapters") as batch:
        for column in DROP_COLUMNS:
            batch.drop_column(column)

    # 3. 节与节的版本
    op.create_table(
        "chapter_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "chapter_id",
            sa.Integer(),
            sa.ForeignKey("chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column("current_version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "uq_chapter_sections_slug_active",
        "chapter_sections",
        ["chapter_id", "slug"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_chapter_sections_order",
        "chapter_sections",
        ["chapter_id", "deleted_at", "sort_order"],
    )

    op.create_table(
        "section_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "section_id",
            sa.Integer(),
            sa.ForeignKey("chapter_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="markdown"),
        sa.Column("content_raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("section_id", "version_no", name="uq_section_version"),
    )
    op.create_index("ix_section_versions_section", "section_versions", ["section_id"])


def downgrade() -> None:
    op.drop_index("ix_section_versions_section", table_name="section_versions")
    op.drop_table("section_versions")
    op.drop_index("ix_chapter_sections_order", table_name="chapter_sections")
    op.drop_index("uq_chapter_sections_slug_active", table_name="chapter_sections")
    op.drop_table("chapter_sections")

    with op.batch_alter_table("chapters") as batch:
        batch.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="doc")
        )
        batch.add_column(
            sa.Column("format", sa.String(length=16), nullable=False, server_default="markdown")
        )
        batch.add_column(sa.Column("content_raw", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("content_safe", sa.Text(), nullable=False, server_default=""))
        batch.add_column(
            sa.Column("content_rendered", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("content_toc", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("content_checksum", sa.String(length=64), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("word_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("current_version_no", sa.Integer(), nullable=False, server_default="1")
        )
    op.create_index("ix_chapters_tree", "chapters", ["book_id", "parent_id", "sort_order"])

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
