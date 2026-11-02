"""Alembic 环境：数据库地址来自 DATABASE_URL。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import context

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import Base, build_engine  # noqa: E402
import app.models  # noqa: F401,E402  确保模型被导入

config = context.config
target_metadata = Base.metadata


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    default = "sqlite:///" + str(ROOT / "data" / "bookhub.db")
    Path(ROOT / "data").mkdir(parents=True, exist_ok=True)
    return default


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine(database_url())
    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            # SQLite 的 batch_alter_table 用「建新表→拷数据→删旧表」实现，
            # 删旧表时若有外键引用会直接失败；迁移期间关掉外键检查是标准做法。
            # PRAGMA 必须在事务外执行，所以随后显式提交一次。
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
