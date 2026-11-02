"""book html view mode

给 Book 增加「HTML 阅读方式」：`inline`（站内净化渲染，默认）或
`document`（新标签页原样打开上传文档，保留其 CSS/JS/内置导航）。

Revision ID: 0004_book_html_view
Revises: 0003_book_auto_weight
Create Date: 2026-10-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_book_html_view"
down_revision = "0003_book_auto_weight"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column("html_view", sa.String(length=16), nullable=False, server_default="inline"),
    )


def downgrade() -> None:
    with op.batch_alter_table("books") as batch:
        batch.drop_column("html_view")
