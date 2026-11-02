"""登录与登出。"""

from __future__ import annotations

from contextlib import suppress

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import AppError
from app.logging_setup import log_event
from app.middleware import client_ip
from app.security import issue_session
from app.services.users import authenticate, mark_login, normalize_username
from app.web.common import base_context, current_user, get_settings

router = APIRouter(include_in_schema=False)


@router.get("/admin/login", response_class=HTMLResponse)
def login_form(
    request: Request,
    next: str = Query(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if current_user(request, session) is not None:
        return RedirectResponse(f"{get_settings(request).root_path}/admin", status_code=303)
    context = base_context(
        request,
        session,
        page_title="登录",
        error="",
        next_url=next,
        username="",
    )
    return request.app.state.templates.TemplateResponse(request, "admin/login.html", context)


@router.post("/admin/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
    next: str = Form(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    settings = get_settings(request)
    ip = client_ip(request)
    key = f"login:{ip}:{normalize_username(username)}"
    ip_allowed, ip_retry = request.app.state.login_ip_limiter.check(f"login-ip:{ip}")
    if not ip_allowed:
        log_event("auth.rate_limited_ip", ip=ip)
        context = base_context(
            request,
            session,
            page_title="登录",
            error=f"该来源登录尝试过于频繁，请 {ip_retry} 秒后再试",
            next_url=next,
            username=username,
        )
        return request.app.state.templates.TemplateResponse(
            request, "admin/login.html", context, status_code=429
        )
    allowed, retry_after = request.app.state.login_limiter.check(key)
    if not allowed:
        log_event("auth.rate_limited", ip=ip, username=username)
        context = base_context(
            request,
            session,
            page_title="登录",
            error=f"登录失败次数过多，请 {retry_after} 秒后再试",
            next_url=next,
            username=username,
        )
        return request.app.state.templates.TemplateResponse(
            request, "admin/login.html", context, status_code=429
        )

    user = authenticate(session, username, password)
    if user is None:
        log_event("auth.login_failed", ip=ip, username=username)
        context = base_context(
            request,
            session,
            page_title="登录",
            error="用户名或密码错误",
            next_url=next,
            username=username,
        )
        return request.app.state.templates.TemplateResponse(
            request, "admin/login.html", context, status_code=401
        )

    request.app.state.login_limiter.reset(key)
    mark_login(session, user)
    session.commit()
    token = issue_session(settings.secret_key, user.id, user.session_epoch)
    target = next if next.startswith("/admin") else f"{settings.root_path}/admin"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path=settings.root_path or "/",
    )
    log_event("auth.login_success", user=user.username, ip=ip)
    return response


@router.post("/admin/logout")
def logout(
    request: Request,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    settings = get_settings(request)
    from app.web.common import require_csrf

    with suppress(AppError):
        require_csrf(request, csrf_token)
    response = RedirectResponse(f"{settings.root_path}/admin/login", status_code=303)
    response.delete_cookie(settings.session_cookie_name, path=settings.root_path or "/")
    return response
