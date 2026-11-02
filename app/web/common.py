"""Web 层公共工具：会话用户、模板上下文、CSRF 与分页。"""

from __future__ import annotations

import math

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import Forbidden, Unauthorized
from app.middleware import client_ip
from app.models import ROLE_ADMIN, User
from app.security import SessionData, issue_csrf, read_session, verify_csrf
from app.services.settings import load_settings

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def absolute_url(request: Request, path: str) -> str:
    """拼绝对地址。

    「反代剥离前缀」的部署里 `request.base_url` 不含 ROOT_PATH（见 docs/deploy.md），
    因此这里显式补一次；若服务端已配 root_path（base_url 已含），就不重复加。
    """
    settings = get_settings(request)
    base = str(request.base_url).rstrip("/")
    root_path = settings.root_path.rstrip("/")
    if root_path and not base.endswith(root_path):
        base = f"{base}{root_path}"
    return f"{base}{path}"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_data(request: Request) -> SessionData | None:
    settings = get_settings(request)
    token = request.cookies.get(settings.session_cookie_name, "")
    return read_session(settings.secret_key, token, settings.session_max_age)


def current_user(request: Request, session: Session) -> User | None:
    cached = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached
    data = get_session_data(request)
    if data is None:
        return None
    user = session.get(User, data.user_id)
    if user is None or not user.is_active or user.session_epoch != data.epoch:
        return None
    request.state.current_user = user
    return user


def site_context(request: Request, session: Session) -> dict[str, object]:
    settings = get_settings(request)
    site = load_settings(session, settings)
    return {
        "site": site,
        "settings": settings,
        "root_path": settings.root_path,
        "version": __import__("app").__version__,
    }


def base_context(
    request: Request,
    session: Session,
    *,
    user: User | None = None,
    page_title: str = "",
    **extra: object,
) -> dict[str, object]:
    context: dict[str, object] = {
        "request": request,
        "page_title": page_title,
        "current_user": user,
        "csrf_token": "",
        "client_ip": client_ip(request),
    }
    context.update(site_context(request, session))
    if user is not None:
        data = get_session_data(request)
        if data is not None:
            context["csrf_token"] = issue_csrf(get_settings(request).secret_key, data)
    context.update(extra)
    return context


def require_user(request: Request, session: Session, *, admin_only: bool = False) -> User:
    user = current_user(request, session)
    if user is None:
        raise Unauthorized("请先登录")
    if admin_only and user.role != ROLE_ADMIN:
        raise Forbidden("该操作仅限管理员")
    return user


def require_csrf(request: Request, token: str | None) -> None:
    settings = get_settings(request)
    data = get_session_data(request)
    if data is None:
        raise Unauthorized("会话已失效，请重新登录")
    candidate = (token or "").strip()
    if not candidate:
        candidate = request.headers.get("x-csrf-token", "")
    if not verify_csrf(settings.secret_key, data, candidate, settings.session_max_age):
        raise Forbidden("CSRF 校验失败，请刷新页面后重试")


def parse_page(raw: object, *, default_size: int = DEFAULT_PAGE_SIZE) -> tuple[int, int]:
    page = 1
    size = default_size
    if raw is not None:
        try:
            page = int(str(raw))
        except (TypeError, ValueError):
            page = 1
    return max(1, page), size


def paginate(total: int, page: int, page_size: int) -> dict[str, int]:
    pages = max(1, math.ceil(total / page_size)) if page_size else 1
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
    }
