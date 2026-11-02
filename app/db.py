"""数据库引擎、会话与声明式基类。"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.requests import Request

# 待投递的 webhook 记录：由 services 在事务里登记，commit 之后交给后台线程发送。
# 键定义在这里是为了让 `get_session`/监听器与 services 共用同一份常量。
WEBHOOK_PENDING_KEY = "webhook_pending"
WEBHOOK_FACTORY_KEY = "webhook_factory"

# 进程内唯一的会话工厂；监听器在拿不到 session.info 里的工厂时用它兜底。
# 单实例单库是既定部署形态（SQLite / 单副本），因此这样够用。
_webhook_factory: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def build_engine(url: str) -> Engine:
    """按 URL 构造引擎；SQLite 额外打开 WAL 与外键约束。"""
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _apply_pragmas(dbapi_connection, _record) -> None:  # pragma: no cover - 驱动回调
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def build_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    global _webhook_factory
    maker = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _webhook_factory = maker
    return maker


def _attach_webhook_dispatch() -> None:
    """提交成功后再把 webhook 交给后台线程，避免网络 I/O 卡住写事务。

    监听器只做「取待投递 id + 提交任务」这两件轻量事；真正的 HTTP 请求在
    `webhooks.deliver_pending()` 里用独立会话完成，失败只写日志。
    """

    @event.listens_for(Session, "after_commit")
    def _flush_pending(session: Session) -> None:  # pragma: no cover - 由集成测试覆盖
        pending = session.info.pop(WEBHOOK_PENDING_KEY, None)
        if not pending:
            return
        factory = session.info.get(WEBHOOK_FACTORY_KEY) or _webhook_factory
        if factory is None:
            return
        from app.services import webhooks

        webhooks.EXECUTOR.submit(webhooks.deliver_pending, factory, list(pending))

    @event.listens_for(Session, "after_rollback")
    def _drop_pending(session: Session) -> None:  # pragma: no cover - 同上
        session.info.pop(WEBHOOK_PENDING_KEY, None)


_attach_webhook_dispatch()


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话。"""
    factory: sessionmaker[Session] = request.app.state.sessionmaker
    session = factory()
    session.info[WEBHOOK_FACTORY_KEY] = factory
    try:
        yield session
    finally:
        session.close()
