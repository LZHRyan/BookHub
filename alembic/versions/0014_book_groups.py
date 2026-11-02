"""book groups

在知识库与 Book 之间加一层「组」：book_groups 表 + books.group_id（必填）。
迁移分三步：建表 → 插入「默认分组」→ 加列回填并收紧为 NOT NULL。

Revision ID: 0014_book_groups
Revises: 0013_webhooks
Create Date: 2026-10-22
"""

from __future__ import annotations

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

revision = "0014_book_groups"
down_revision = "0013_webhooks"
branch_labels = None
depends_on = None

DEFAULT_SLUG = "default"
DEFAULT_TITLE = "默认分组"


def upgrade() -> None:
    op.create_table(
        "book_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=160), nullable=False, unique=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("icon", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_book_groups_sort_order", "book_groups", ["sort_order"])

    bind = op.get_bind()
    now = datetime.now(UTC).replace(tzinfo=None)
    bind.execute(
        sa.text(
            "INSERT INTO book_groups (slug, title, description, icon, sort_order, created_at, updated_at) "
            "VALUES (:slug, :title, '', '', 10, :now, :now)"
        ),
        {"slug": DEFAULT_SLUG, "title": DEFAULT_TITLE, "now": now},
    )
    default_id = bind.execute(
        sa.text("SELECT id FROM book_groups WHERE slug = :slug"), {"slug": DEFAULT_SLUG}
    ).scalar_one()

    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("books", naming_convention=naming) as batch:
        batch.add_column(sa.Column("group_id", sa.Integer(), nullable=True))

    bind.execute(sa.text("UPDATE books SET group_id = :gid"), {"gid": default_id})
    op.create_index("ix_books_group_id", "books", ["group_id"])

    # 回填完成后再收紧成 NOT NULL（SQLite 需要再重建一次表）
    with op.batch_alter_table("books", naming_convention=naming) as batch:
        batch.alter_column("group_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("fk_books_group_id_book_groups", "book_groups", ["group_id"], ["id"])


def downgrade() -> None:
    # 先删索引再重建表：batch 重建会把列上的索引一并丢掉
    op.drop_index("ix_books_group_id", table_name="books")
    with op.batch_alter_table("books") as batch:
        batch.drop_column("group_id")
    op.drop_index("ix_book_groups_sort_order", table_name="book_groups")
    op.drop_table("book_groups")
