"""backfill html view document

HTML 类型的 Book 一律按原始文档打开：把存量的 HTML Book 回填成 `document`。
Markdown Book 不受影响（服务层强制 `inline`）。

Revision ID: 0005_backfill_html_view
Revises: 0004_book_html_view
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op

revision = "0005_backfill_html_view"
down_revision = "0004_book_html_view"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE books SET html_view = 'document' WHERE format = 'html'")


def downgrade() -> None:
    # 回滚到"默认站内渲染"的旧行为；管理员手工选过的值无法区分，统一回填 inline
    op.execute("UPDATE books SET html_view = 'inline' WHERE format = 'html'")
