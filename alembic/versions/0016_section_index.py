"""content search/views migration

把全文索引与访问计数改到节粒度：
- `chapter_fts` 的 `rowid` 从章 id 改成节 id，并补上 book_id / chapter_id / section_id
  三列（FTS5 的 UNINDEXED 列，只存不索引，便于查询时定位）；
- 新增 `section_view_daily`（节的每日访问计数），Book 热度按其各节之和聚合。

Revision ID: 0016_section_index
Revises: 0015_chapter_sections
Create Date: 2026-10-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0016_section_index"
down_revision = "0015_chapter_sections"
branch_labels = None
depends_on = None

OLD_FTS = "CREATE VIRTUAL TABLE chapter_fts USING fts5(title, body, tokenize='unicode61 remove_diacritics 2')"
NEW_FTS = (
    "CREATE VIRTUAL TABLE chapter_fts USING fts5("
    "book_id UNINDEXED, chapter_id UNINDEXED, section_id UNINDEXED,"
    " title, body, tokenize='unicode61 remove_diacritics 2')"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # 旧索引的 rowid 是章 id，与新模型（节 id）不能混用：整表重建，正文由
        # 后续保存 / `reindex_all` 重新灌入。
        op.execute("DROP TABLE IF EXISTS chapter_fts")
        op.execute(NEW_FTS)

    op.create_table(
        "section_view_daily",
        sa.Column(
            "section_id",
            sa.Integer(),
            sa.ForeignKey("chapter_sections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_section_view_daily_day", "section_view_daily", ["day"])

    # Book 级访问计数表已无人使用：热度改由 section_view_daily 聚合
    op.drop_index("ix_book_view_daily_day", table_name="book_view_daily")
    op.drop_table("book_view_daily")


def downgrade() -> None:
    op.create_table(
        "book_view_daily",
        sa.Column(
            "book_id",
            sa.Integer(),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_book_view_daily_day", "book_view_daily", ["day"])

    op.drop_index("ix_section_view_daily_day", table_name="section_view_daily")
    op.drop_table("section_view_daily")

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("DROP TABLE IF EXISTS chapter_fts")
        op.execute(OLD_FTS)
