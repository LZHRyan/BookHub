"""book pinned

给 books 增加置顶开关：置顶优先于自动权重，置顶内部仍按权重排序。
存量 Book 全部非置顶，行为与之前一致。

Revision ID: 0010_book_pinned
Revises: 0009_chapter_groups
Create Date: 2026-10-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_book_pinned"
down_revision = "0009_chapter_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    with op.batch_alter_table("books") as batch:
        batch.drop_column("pinned")
