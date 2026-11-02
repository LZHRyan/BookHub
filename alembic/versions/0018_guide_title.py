"""rename builtin guide title

内置指南改名为《AI Agent 接入使用指南》：原来的名字没说清"接入"，容易被当成
一本讲 Agent 原理的书。

只改**标题仍是旧默认值**的内置 Book：管理员如果自己改过标题，保留他的版本。
`is_builtin=1` 是必要条件，用户自己的书不受影响。

Revision ID: 0018_guide_title
Revises: 0017_book_builtin
Create Date: 2026-11-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0018_guide_title"
down_revision = "0017_book_builtin"
branch_labels = None
depends_on = None

OLD_TITLE = "AI Agent 使用指南"
NEW_TITLE = "AI Agent 接入使用指南"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE books SET title = :new_title, updated_at = CURRENT_TIMESTAMP"
            " WHERE is_builtin = :flag AND title = :old_title"
        ).bindparams(new_title=NEW_TITLE, flag=True, old_title=OLD_TITLE)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE books SET title = :old_title, updated_at = CURRENT_TIMESTAMP"
            " WHERE is_builtin = :flag AND title = :new_title"
        ).bindparams(new_title=NEW_TITLE, flag=True, old_title=OLD_TITLE)
    )
