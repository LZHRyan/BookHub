"""book cover

给 books 增加封面：指向该 Book 媒体库里的一张图片（media_assets.id）。
SQLite 不支持 ALTER 加外键，用 batch（copy-and-move）方式加列。

Revision ID: 0011_book_cover
Revises: 0010_book_pinned
Create Date: 2026-10-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_book_cover"
down_revision = "0010_book_pinned"
branch_labels = None
depends_on = None


def upgrade() -> None:
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("books", naming_convention=naming) as batch:
        batch.add_column(
            sa.Column(
                "cover_media_id",
                sa.Integer(),
                sa.ForeignKey("media_assets.id", name="fk_books_cover_media_id_media_assets"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("books") as batch:
        batch.drop_column("cover_media_id")
