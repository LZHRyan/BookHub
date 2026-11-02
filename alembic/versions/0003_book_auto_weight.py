"""book auto weight

Book 排序改为按访问热度 + 创建时间自动计算：
- 新增 `book_view_daily` 存放按天聚合的访问计数（热度数据源）
- 删除 `books.sort_order`（不再由用户设置）
- `ix_books_listing` 去掉 sort_order 列

Revision ID: 0003_book_auto_weight
Revises: 0002_book_format
Create Date: 2026-10-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_book_auto_weight"
down_revision = "0002_book_format"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "book_view_daily",
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_book_view_daily_day", "book_view_daily", ["day"])
    # 先删掉索引再批处理删列：索引里带着 sort_order，重建表时会把它一起带回来
    op.drop_index("ix_books_listing", table_name="books")
    with op.batch_alter_table("books") as batch:
        batch.drop_column("sort_order")
    op.create_index("ix_books_listing", "books", ["deleted_at", "visibility"])


def downgrade() -> None:
    op.drop_index("ix_books_listing", table_name="books")
    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_books_listing", "books", ["deleted_at", "visibility", "sort_order"])
    op.drop_index("ix_book_view_daily_day", table_name="book_view_daily")
    op.drop_table("book_view_daily")
