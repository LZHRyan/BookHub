"""启动期一次性任务：幂等创建初始管理员、可选演示数据。

作为独立命令执行：`python -m app.bootstrap`。
entrypoint 在迁移之后调用它，保证容器启动后一定有可用管理员。
"""

from __future__ import annotations

import sys

from app.config import ConfigError, Settings
from app.db import build_engine, build_sessionmaker
from app.logging_setup import configure_logging, log_event
from app.services.demo import seed_demo_content
from app.services.users import ensure_initial_admin


def main() -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"[bootstrap] 配置错误：{exc}", file=sys.stderr)
        return 1
    configure_logging(settings.log_level)
    engine = build_engine(settings.database_url)
    factory = build_sessionmaker(engine)
    try:
        with factory() as session:
            created = ensure_initial_admin(session, settings)
            session.commit()
            if created:
                log_event("admin.bootstrap", user=settings.initial_admin_user)
            elif not settings.initial_admin_user:
                log_event("admin.bootstrap.skipped", reason="initial admin env not set")
            if settings.seed_demo and seed_demo_content(session):
                session.commit()
                log_event("demo.seeded")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
