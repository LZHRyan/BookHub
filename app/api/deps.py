"""管理 API 的认证与限流依赖。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import Forbidden, RateLimited, Unauthorized
from app.services import tokens as token_service

SCOPE_ORDER = {"read": 1, "write": 2, "admin": 3}


@dataclass(frozen=True)
class Principal:
    """审计与业务层可用的轻量身份（鸭子类型兼容 services 里的 actor 参数）。"""

    token_id: int
    name: str
    scopes: tuple[str, ...]
    book_ids: tuple[int, ...] = ()

    @property
    def id(self) -> int | None:
        return None

    @property
    def username(self) -> str:
        return f"api:{self.name}"

    @property
    def display_name(self) -> str:
        return f"api:{self.name}"

    @property
    def role(self) -> str:
        return "admin" if "admin" in self.scopes else "editor"

    def allows(self, needed: str) -> bool:
        current = max((SCOPE_ORDER.get(scope, 0) for scope in self.scopes), default=0)
        return current >= SCOPE_ORDER.get(needed, 99)


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    # 方便一些只支持自定义头的工具
    return request.headers.get("x-api-key", "").strip()


def current_principal(request: Request, session: Session) -> Principal:
    raw = bearer_token(request)
    if not raw:
        raise Unauthorized("缺少凭据：请使用 Authorization: Bearer <token>")
    token = token_service.verify_token(session, raw)
    if token is None:
        raise Unauthorized("Token 无效、已吊销或已过期")

    limiter = getattr(request.app.state, "admin_limiter", None)
    if limiter is not None:
        allowed, retry_after = limiter.check(f"token:{token.id}")
        if not allowed:
            raise RateLimited(
                "管理接口调用过于频繁，请稍后重试",
                headers={"Retry-After": str(retry_after)},
            )

    scopes = tuple(token_service.scopes_of(token))
    book_ids = tuple(token_service.book_scope_of(token))
    # 历史上可能签出过 admin + Book 范围的组合：它在全站级端点上无法被范围拦住，
    # 等于全站管理员，直接拒绝使用，要求吊销重签。
    if "admin" in scopes and book_ids:
        raise Forbidden(
            "该 Token 的 admin 作用域与 Book 范围不能共存：admin 是全站权限，"
            "请吊销后重新签发（限定 Book 请改用 read / write）"
        )

    return Principal(
        token_id=token.id,
        name=token.name,
        scopes=scopes,
        book_ids=book_ids,
    )


def _check_book_scope(request: Request, session: Session, principal: Principal) -> None:
    """Token 限定了 Book 范围时，校验路径里的 book_ref 是否在范围内。"""
    if not principal.book_ids:
        return
    ref = request.path_params.get("book_ref")
    if not ref:
        return
    from app.services import books as books_service

    try:
        book = books_service.get_book(session, ref, include_deleted=True)
    except Exception:
        return  # 不存在交给端点自己返回 404
    if book.id not in principal.book_ids:
        raise Forbidden(f"该 Token 无权操作这个 Book（{book.slug}）")


def require_scope(needed: str):
    """依赖工厂：校验作用域（read < write < admin 递增包含）。"""

    def dependency(request: Request, session: Session = Depends(get_session)) -> Principal:
        principal = current_principal(request, session)
        if not principal.allows(needed):
            raise Forbidden(f"该 Token 缺少 {needed} 作用域")
        _check_book_scope(request, session, principal)
        return principal

    return dependency
