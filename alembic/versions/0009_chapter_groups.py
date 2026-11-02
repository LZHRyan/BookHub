"""chapter groups

给 chapters 增加「分卷」支持：kind（doc/group）与自引用 parent_id，
并建 (book_id, parent_id, sort_order) 索引。存量行默认 kind='doc'、parent_id=NULL，
语义与之前完全一致（全部落在根层）。

Revision ID: 0009_chapter_groups
Revises: 0008_media_scope_index
Create Date: 2026-10-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_chapter_groups"
down_revision = "0008_media_scope_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 不支持 ALTER 加外键约束，用 batch（copy-and-move）方式加两列。
    # 既有表里的外键没命名，batch 重建时需要一个命名约定才能处理它们。
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("chapters", naming_convention=naming) as batch:
        batch.add_column(
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="doc")
        )
        batch.add_column(
            sa.Column(
                "parent_id",
                sa.Integer(),
                sa.ForeignKey("chapters.id", name="fk_chapters_parent_id_chapters"),
                nullable=True,
            )
        )
    op.create_index("ix_chapters_parent_id", "chapters", ["parent_id"])
    op.create_index("ix_chapters_tree", "chapters", ["book_id", "parent_id", "sort_order"])


def downgrade() -> None:
    op.drop_index("ix_chapters_tree", table_name="chapters")
    op.drop_index("ix_chapters_parent_id", table_name="chapters")
    with op.batch_alter_table("chapters") as batch:
        batch.drop_column("parent_id")
        batch.drop_column("kind")
