"""book builtin flag

给 books 增加 `is_builtin`：标记「系统内置、随系统生命周期存在」的 Book
（当前只有《AI Agent 使用指南》）。存量 Book 全部为 false，行为不变。

Revision ID: 0017_book_builtin
Revises: 0016_section_index
Create Date: 2026-11-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0017_book_builtin"
down_revision = "0016_section_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    with op.batch_alter_table("books") as batch:
        batch.drop_column("is_builtin")
