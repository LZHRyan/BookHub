"""media scope index

把 `media_assets.stored_name` 的全局唯一索引换成 `(book_id, stored_name)` 复合唯一：
内容寻址的去重范围限定在同一个 Book 内，两个 Book 上传同一份文件不再互相冲突
（物理路径本来就按 book slug 分目录）。

Revision ID: 0008_media_scope_index
Revises: 0007_media_assets
Create Date: 2026-10-22
"""

from __future__ import annotations

from alembic import op

revision = "0008_media_scope_index"
down_revision = "0007_media_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_media_assets_stored_name", table_name="media_assets")
    op.create_index("ix_media_assets_stored_name", "media_assets", ["stored_name"])
    op.create_index(
        "uq_media_book_stored", "media_assets", ["book_id", "stored_name"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_media_book_stored", table_name="media_assets")
    op.drop_index("ix_media_assets_stored_name", table_name="media_assets")
    op.create_index(
        "ix_media_assets_stored_name", "media_assets", ["stored_name"], unique=True
    )
