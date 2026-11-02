"""FastAPI 应用工厂。"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import Settings
from app.db import build_engine, build_sessionmaker
from app.errors import AppError, error_body, request_id_of
from app.logging_setup import configure_logging, log_event
from app.middleware import (
    ApiKeyMiddleware,
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.services.ratelimit import RateLimiter
from app.services.visits import VisitDeduper

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def asset_version() -> str:
    """静态资源版本号：取 static/ 下最新修改时间，用于给 <link>/<script> 加 ?v= 破缓存。

    没有指纹文件名时，升级镜像后浏览器仍会用旧 CSS/JS；带上这个版本号即可自动失效。
    """
    try:
        stamps = [path.stat().st_mtime for path in STATIC_DIR.iterdir() if path.is_file()]
    except OSError:
        stamps = []
    return str(int(max(stamps))) if stamps else "1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log_event("app.start", version=__version__, **settings.public_dict())
        _startup_tasks(app)
        yield
        from app.services import webhooks

        webhooks.EXECUTOR.shutdown()
        app.state.engine.dispose()
        log_event("app.stop")

    app = FastAPI(
        title="BookHub",
        version=__version__,
        description="研发部技术文档知识库：Book / 章 / 节 / 只读 API",
        lifespan=lifespan,
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    )

    engine = build_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = build_sessionmaker(engine)
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute, 60)
    app.state.login_limiter = RateLimiter(settings.login_fail_limit, settings.login_fail_window)
    # 每 IP 的登录总闸：换用户名不能绕过（按 (IP,用户名) 的那道只防单个账号被爆破）
    app.state.login_ip_limiter = RateLimiter(
        max(10, settings.login_fail_limit * 6), settings.login_fail_window, max_entries=10_000
    )
    app.state.admin_limiter = RateLimiter(settings.admin_api_rate_limit, 60)
    app.state.visit_deduper = VisitDeduper()

    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    templates.env.filters["tojson_pretty"] = lambda value: json.dumps(value, ensure_ascii=False, indent=2)
    templates.env.globals["asset_version"] = asset_version()
    from app.services.media import media_root, prefix_media_urls

    templates.env.filters["media_urls"] = lambda html: prefix_media_urls(html, settings.root_path)
    app.state.templates = templates

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    media_root(settings).mkdir(parents=True, exist_ok=True)

    app.add_middleware(ApiKeyMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    # 顺序：后添加的更靠外层。请求体上限放在 RequestContext 内层，
    # 这样 413 也能带上 request id 并进访问日志。
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins and settings.cors_origins != ("*",):
        from starlette.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "HEAD", "OPTIONS"],
            allow_headers=["X-API-Key", "If-None-Match", "Accept"],
            expose_headers=["ETag", "X-Request-ID", "Retry-After"],
            allow_credentials=False,
        )
    elif settings.cors_origins == ("*",):
        from starlette.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "HEAD", "OPTIONS"],
            allow_headers=["X-API-Key", "If-None-Match", "Accept"],
            expose_headers=["ETag", "X-Request-ID", "Retry-After"],
            allow_credentials=False,
        )

    _register_error_handlers(app)
    _register_health(app)

    from app.api.admin import router as management_router
    from app.api.v1 import router as api_router
    from app.web.admin import router as admin_router
    from app.web.auth import router as auth_router
    from app.web.media import router as media_router
    from app.web.public import router as public_router
    from app.web.tokens import router as tokens_router

    app.include_router(management_router)
    app.include_router(api_router)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(tokens_router)
    app.include_router(media_router)
    app.include_router(public_router)

    return app


def _startup_tasks(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    factory = app.state.sessionmaker
    try:
        with factory() as session:
            # 启动阶段写库（演示数据 / 内置指南）也可能产生 webhook 事件：
            # 给出会话工厂，commit 后由监听器交给后台线程。
            from app.db import WEBHOOK_FACTORY_KEY

            session.info[WEBHOOK_FACTORY_KEY] = factory
            from app.services.users import ensure_initial_admin

            created = ensure_initial_admin(session, settings)
            session.commit()
            if created:
                log_event("admin.bootstrap", user=settings.initial_admin_user)
            elif not settings.initial_admin_user:
                log_event("admin.bootstrap.skipped", reason="initial admin env not set")
            if settings.seed_demo:
                from app.services.demo import seed_demo_content

                seeded = seed_demo_content(session)
                session.commit()
                if seeded:
                    log_event("demo.seeded")

            # 内置《AI Agent 接入使用指南》：幂等创建，已存在的内容不覆盖
            if settings.builtin_guide:
                from app.services.guide import ensure_guide

                guided = ensure_guide(session)
                session.commit()
                if guided is not None:
                    log_event("guide.ensured", slug=guided.slug)
                else:
                    log_event("guide.skipped", reason="slug taken by a non-builtin book")

            # 管理 API：引导 Token（幂等）与过期幂等键清理
            from app.services import idempotency as idempotency_service
            from app.services import tokens as token_service

            if settings.admin_api_token:
                bootstrap = token_service.ensure_bootstrap_token(session, settings.admin_api_token)
                session.commit()
                if bootstrap is not None:
                    log_event("admin.token.bootstrap", name=bootstrap.name)
            cleaned = idempotency_service.cleanup(session)
            session.commit()
            if cleaned:
                log_event("admin.idempotency.cleanup", removed=cleaned)

            # 审计保留策略：按 AUDIT_RETENTION_DAYS 清理，0 表示永久保留
            from app.services import audit as audit_service

            pruned = audit_service.cleanup(session, settings.audit_retention_days)
            session.commit()
            if pruned.get("deleted"):
                log_event("audit.cleanup", **pruned)
    except Exception as exc:  # pragma: no cover - 启动阶段容错
        log_event("app.startup.error", error=str(exc))


def _schema_revision(factory) -> str | None:
    """当前库结构版本（alembic revision）；读不到就返回 None，绝不影响探针。"""
    try:
        with factory() as session:
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        return None
    return str(revision) if revision else None


def _register_health(app: FastAPI) -> None:
    @app.get("/healthz", include_in_schema=False)
    def healthz(request: Request) -> JSONResponse:
        # 升级验证用：version 来自镜像，schema 来自数据库，两者一起才能确认"迁移真的跑过了"
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "schema": _schema_revision(request.app.state.sessionmaker),
            }
        )

    @app.get("/readyz", include_in_schema=False)
    def readyz(request: Request) -> JSONResponse:
        factory = request.app.state.sessionmaker
        try:
            with factory() as session:
                session.execute(text("CREATE TABLE IF NOT EXISTS _readyz_probe (id INTEGER PRIMARY KEY)"))
                session.execute(text("INSERT INTO _readyz_probe (id) VALUES (1)"))
                session.execute(text("DELETE FROM _readyz_probe WHERE id = 1"))
                session.commit()
        except Exception as exc:
            log_event("readyz.failed", error=str(exc))
            return JSONResponse({"status": "unavailable", "reason": "database not writable"}, status_code=503)
        return JSONResponse(
            {"status": "ready", "version": __version__, "schema": _schema_revision(factory)}
        )


def _register_error_handlers(app: FastAPI) -> None:
    templates: Jinja2Templates = app.state.templates
    settings: Settings = app.state.settings

    def wants_json(request: Request) -> bool:
        path = request.url.path
        return path.startswith("/api/") or path in {"/healthz", "/readyz"}

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> Response:
        request_id = request_id_of(request)
        if wants_json(request):
            headers = {"X-Request-ID": request_id}
            headers.update(getattr(exc, "headers", {}) or {})
            return JSONResponse(
                error_body(exc.code, exc.message, request_id),
                status_code=exc.status_code,
                headers=headers,
            )
        if exc.status_code == 401 and request.url.path.startswith("/admin"):
            next_url = request.url.path
            return RedirectResponse(f"{settings.root_path}/admin/login?next={next_url}", status_code=303)
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": exc.status_code,
                "message": exc.message,
                "request_id": request_id,
                "site": {"site_name": settings.site_name, "site_footer": settings.site_footer, "home_intro": ""},
                "current_user": None,
            },
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> Response:
        """兜底：未预期异常也返回统一错误体，且绝不把堆栈/内部路径吐给调用方。"""
        from starlette.exceptions import HTTPException as _HTTPException

        if isinstance(exc, _HTTPException):  # pragma: no cover - 由上面的 handler 负责
            raise exc
        request_id = request_id_of(request)
        log_event(
            "app.error",
            level=logging.ERROR,
            error=f"{type(exc).__name__}: {exc}"[:500],
            path=request.url.path,
            request_id=request_id,
        )
        message = "服务器内部错误，请稍后重试；如持续出现请联系管理员并提供 request id"
        if wants_json(request):
            return JSONResponse(
                error_body("internal_error", message, request_id),
                status_code=500,
                headers={"X-Request-ID": request_id},
            )
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": 500,
                "message": message,
                "request_id": request_id,
                "site": {"site_name": settings.site_name, "site_footer": settings.site_footer, "home_intro": ""},
                "current_user": None,
            },
            status_code=500,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> Response:
        request_id = request_id_of(request)
        if wants_json(request) or exc.status_code >= 500:
            return JSONResponse(
                error_body("http_error", str(exc.detail), request_id),
                status_code=exc.status_code,
                headers=getattr(exc, "headers", None) or {"X-Request-ID": request_id},
            )
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": exc.status_code,
                "message": str(exc.detail),
                "request_id": request_id,
                "site": {"site_name": settings.site_name, "site_footer": settings.site_footer, "home_intro": ""},
                "current_user": None,
            },
            status_code=exc.status_code,
        )


class _LazyApp:
    """`uvicorn app.main:app` 的兼容入口。

    首次请求时才装配应用，配置缺失会以明确的 ConfigError 暴露出来，
    而不是让模块级变量变成 None 后再报"不是可调用对象"。
    容器内仍推荐 `uvicorn app.main:create_app --factory`。
    """

    _inner: FastAPI | None = None

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if self._inner is None:
            self._inner = create_app()
        await self._inner(scope, receive, send)


app = _LazyApp()
