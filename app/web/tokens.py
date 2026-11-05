"""管理端「API Token」页面：签发、查看、吊销。"""

from __future__ import annotations

from datetime import datetime
from math import ceil

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import AppError, NotFound, ValidationFailed
from app.middleware import client_ip
from app.models import Book, utcnow
from app.services import audit as audit_service
from app.services import book_groups, idempotency
from app.services import tokens as token_service
from app.web.common import base_context, get_settings, require_csrf, require_user

router = APIRouter(prefix="/admin/tokens", include_in_schema=False)

# Book 范围选择器每页显示多少本：Book 上百本时靠分组 + 搜索 + 分页定位
BOOK_PAGE_SIZE = 20


def _render(request: Request, session: Session, user, template_context: dict, status_code: int = 200):
    context = base_context(
        request,
        session,
        user=user,
        page_title="API Token",
        **template_context,
    )
    return request.app.state.templates.TemplateResponse(
        request, "admin/tokens.html", context, status_code=status_code
    )


def _like_pattern(value: str) -> str:
    """把用户输入转成 LIKE 片段：% 和 _ 按字面匹配，避免搜索词被当成通配符。"""
    safe = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{safe}%"


def _book_scope_page(
    session: Session,
    *,
    group_ref: str = "",
    query: str = "",
    page: int = 1,
) -> dict[str, object]:
    """Book 范围选择器的一页数据：支持按分组过滤 + 标题/slug 搜索 + 分页。"""
    stmt = select(Book).where(Book.deleted_at.is_(None))
    group_ref = (group_ref or "").strip()
    if group_ref:
        try:
            group = book_groups.get_group(session, group_ref)
        except NotFound:
            group = None
        stmt = stmt.where(Book.group_id == group.id) if group is not None else stmt.where(False)
    query = (query or "").strip()
    if query:
        pattern = _like_pattern(query)
        stmt = stmt.where(
            or_(
                Book.title.ilike(pattern, escape="\\"),
                Book.slug.ilike(pattern, escape="\\"),
            )
        )

    total = int(session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
    pages = max(1, ceil(total / BOOK_PAGE_SIZE))
    page = min(max(int(page or 1), 1), pages)
    rows = list(
        session.execute(
            stmt.order_by(Book.title.asc(), Book.id.asc())
            .offset((page - 1) * BOOK_PAGE_SIZE)
            .limit(BOOK_PAGE_SIZE)
        ).scalars()
    )

    groups = book_groups.list_groups(session)
    counts = book_groups.book_counts(session)
    titles = {group.id: group.title for group in groups}
    return {
        # 键名避开 dict 自带属性（items/keys 等），否则 Jinja 会取到方法而不是数据
        "books": [
            {
                "id": book.id,
                "title": book.title,
                "slug": book.slug,
                "icon": book.icon,
                "group": titles.get(book.group_id, ""),
            }
            for book in rows
        ],
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": BOOK_PAGE_SIZE,
        "group": group_ref,
        "query": query,
        "groups": [
            {"slug": group.slug, "title": group.title, "count": counts.get(group.id, 0)}
            for group in groups
        ],
    }


def _page_context(
    session: Session,
    *,
    error: str = "",
    new_token: str = "",
    new_name: str = "",
    book_scope: dict[str, object] | None = None,
) -> dict:
    rows = token_service.list_tokens(session)
    described = []
    for token in rows:
        item = token_service.describe(token)
        books = []
        for book_id in item.pop("book_ids", []) or []:
            book = session.get(Book, int(book_id))
            if book is not None:
                books.append({"id": book.id, "slug": book.slug, "title": book.title})
        item["books"] = books
        item["expiry_hint"] = _expiry_hint(item)
        described.append(item)
    return {
        "tokens": described,
        "book_scope": book_scope or _book_scope_page(session),
        "error": error,
        "new_token": new_token,
        "new_name": new_name,
        "scopes": ["read", "write", "admin"],
        "idempotency_cleaned": 0,
    }


def _expiry_hint(item: dict) -> str:
    """Token 列表的过期/闲置提示（展示层派生，不落库）。"""
    now = utcnow()
    expires_at = item.get("expires_at")
    last_used_at = item.get("last_used_at")
    if item.get("revoked_at"):
        return "已吊销"
    if isinstance(expires_at, datetime):
        if expires_at <= now:
            return "已过期"
        days = (expires_at - now).days
        if days <= 14:
            return f"{max(days, 1)} 天后过期"
    if isinstance(last_used_at, datetime) and (now - last_used_at).days >= 30:
        return f"{(now - last_used_at).days} 天未使用"
    return ""


@router.get("", response_class=HTMLResponse)
def tokens_page(
    request: Request,
    bgroup: str = Query(default=""),
    bq: str = Query(default=""),
    bpage: int = Query(default=1, ge=1),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """签发页；`bgroup` / `bq` / `bpage` 决定「可操作的 Book」选择器的初始页。"""
    user = require_user(request, session, admin_only=True)
    scope = _book_scope_page(session, group_ref=bgroup, query=bq, page=bpage)
    return _render(request, session, user, _page_context(session, book_scope=scope))


@router.get("/books.json")
def book_scope_json(
    request: Request,
    group: str = Query(default=""),
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Book 范围选择器的数据源：分组过滤 + 标题/slug 搜索 + 分页。"""
    require_user(request, session, admin_only=True)
    return JSONResponse(_book_scope_page(session, group_ref=group, query=q, page=page))


@router.post("", response_class=HTMLResponse)
def create_token(
    request: Request,
    name: str = Form(default=""),
    scope_read: str = Form(default=""),
    scope_write: str = Form(default=""),
    scope_admin: str = Form(default=""),
    expires_in_days: str = Form(default=""),
    book_ids: list[int] = Form(default=[]),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session, admin_only=True)
    require_csrf(request, csrf_token)
    scopes = [
        scope
        for scope, chosen in (("read", scope_read), ("write", scope_write), ("admin", scope_admin))
        if chosen
    ]
    try:
        days = int(expires_in_days) if expires_in_days.strip() else None
        token, raw = token_service.issue_token(
            session,
            name=name,
            scopes=scopes or ["read"],
            created_by=user.id,
            expires_in_days=days,
            book_ids=book_ids,
        )
        audit_service.record(
            session,
            actor=user,
            action="token.create",
            target_type="token",
            target_id=token.id,
            target_label=token.name,
            detail={
                "scopes": token_service.scopes_of(token),
                "book_ids": token_service.book_scope_of(token),
            },
            ip=client_ip(request),
        )
        session.commit()
    except (AppError, ValueError) as exc:
        session.rollback()
        message = exc.message if isinstance(exc, AppError) else str(exc)
        return _render(request, session, user, _page_context(session, error=message), status_code=400)

    context = _page_context(session, new_token=raw, new_name=token.name)
    return _render(request, session, user, context)


@router.post("/{token_id}/revoke")
def revoke_token(
    request: Request,
    token_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session, admin_only=True)
    require_csrf(request, csrf_token)
    token = token_service.get_token(session, token_id)
    if token is None:
        raise NotFound("Token 不存在")
    token_service.revoke_token(session, token)
    audit_service.record(
        session,
        actor=user,
        action="token.revoke",
        target_type="token",
        target_id=token.id,
        target_label=token.name,
        ip=client_ip(request),
    )
    session.commit()
    settings = get_settings(request)
    return RedirectResponse(f"{settings.root_path}/admin/tokens", status_code=303)


@router.post("/{token_id}/delete")
def delete_token(
    request: Request,
    token_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """删除已吊销/已过期的 Token 记录（吊销只让它失效，不会从列表消失）。"""
    user = require_user(request, session, admin_only=True)
    require_csrf(request, csrf_token)
    token = token_service.get_token(session, token_id)
    if token is None:
        raise NotFound("Token 不存在")
    if token_service.is_active(token):
        raise ValidationFailed("Token 仍在有效期内，请先吊销再删除")
    name = token.name
    token_service.delete_token(session, token)
    audit_service.record(
        session,
        actor=user,
        action="token.delete",
        target_type="token",
        target_id=token_id,
        target_label=name,
        ip=client_ip(request),
    )
    session.commit()
    settings = get_settings(request)
    return RedirectResponse(f"{settings.root_path}/admin/tokens", status_code=303)


@router.post("/cleanup")
def cleanup_idempotency(
    request: Request,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    require_user(request, session, admin_only=True)
    require_csrf(request, csrf_token)
    removed = idempotency.cleanup(session)
    session.commit()
    settings = get_settings(request)
    if removed:
        raise ValidationFailed(f"已清理 {removed} 条过期幂等键")
    return RedirectResponse(f"{settings.root_path}/admin/tokens", status_code=303)
