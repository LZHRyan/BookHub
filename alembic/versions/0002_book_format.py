"""book format

给 Book 增加文档类型，并把已有数据按「首章的格式」回填。

Revision ID: 0002_book_format
Revises: 0001_initial
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_book_format"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column("format", sa.String(length=16), nullable=False, server_default="markdown"),
    )
    # 按排序最靠前的章节推断格式；没有章节的 Book 保持 markdown
    op.execute(
        "UPDATE books SET format = COALESCE("
        "  (SELECT c.format FROM chapters c WHERE c.book_id = books.id"
        "   ORDER BY c.sort_order ASC, c.id ASC LIMIT 1),"
        "  'markdown')"
    )


def downgrade() -> None:
    with op.batch_alter_table("books") as batch:
        batch.drop_column("format")
