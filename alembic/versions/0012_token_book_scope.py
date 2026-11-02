"""token book scope

给 api_tokens 增加 book_scope：逗号分隔的 Book id，空字符串表示全部 Book。
用于把 Token 的权限收窄到特定文档，降低对接 AI 工具时的越权风险。

Revision ID: 0012_token_book_scope
Revises: 0011_book_cover
Create Date: 2026-10-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012_token_book_scope"
down_revision = "0011_book_cover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_tokens",
        sa.Column("book_scope", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    with op.batch_alter_table("api_tokens") as batch:
        batch.drop_column("book_scope")
