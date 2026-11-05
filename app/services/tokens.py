"""API Token：签发、校验、吊销。

明文只在签发时返回一次；库里存 sha256 哈希，另存前 8 位前缀用于列表辨识。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ValidationFailed
from app.models import ApiToken, utcnow

SCOPE_ORDER = {"read": 1, "write": 2, "admin": 3}
DEFAULT_SCOPES = ("read",)
TOKEN_PREFIX = "bh_"


def hash_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def normalize_scopes(scopes: list[str] | tuple[str, ...] | str) -> list[str]:
    if isinstance(scopes, str):
        items = [part.strip() for part in scopes.split(",") if part.strip()]
    else:
        items = [str(part).strip() for part in scopes if str(part).strip()]
    unknown = [item for item in items if item not in SCOPE_ORDER]
    if unknown:
        raise ValidationFailed(f"作用域取值非法：{', '.join(unknown)}（可选 read/write/admin）")
    if not items:
        raise ValidationFailed("至少需要一个作用域")
    return sorted(set(items), key=lambda item: SCOPE_ORDER[item])


def scopes_of(token: ApiToken) -> list[str]:
    return [part for part in (token.scopes or "").split(",") if part]


def book_scope_of(token: ApiToken) -> list[int]:
    """Token 限定的 Book id 列表；空列表表示全部 Book。"""
    ids: list[int] = []
    for part in (token.book_scope or "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


def normalize_book_ids(book_ids: list[int] | tuple[int, ...] | str | None) -> list[int]:
    if book_ids is None:
        return []
    if isinstance(book_ids, str):
        parts = [part.strip() for part in book_ids.split(",")]
    else:
        parts = [str(item).strip() for item in book_ids]
    ids: list[int] = []
    for part in parts:
        if not part:
            continue
        if not part.isdigit():
            raise ValidationFailed(f"Book 取值非法：{part!r}")
        ids.append(int(part))
    return sorted(set(ids))


def has_scope(token: ApiToken, needed: str) -> bool:
    current = max((SCOPE_ORDER.get(scope, 0) for scope in scopes_of(token)), default=0)
    return current >= SCOPE_ORDER.get(needed, 99)


def ensure_scope_combination(scopes: list[str], book_ids: list[int]) -> None:
    """admin 作用域不能与 Book 范围共存。

    admin 覆盖账号、站点设置、Token/Webhook 与审计，这些端点没有 `book_ref`，
    Book 范围拦不住它们；两者共存会让人误以为 Token 被限定在几本书内，实际
    持有者只要再签一个无范围 Token 就能拿到全站控制权。
    """
    if book_ids and "admin" in scopes:
        raise ValidationFailed(
            "admin 作用域不能限定 Book 范围：admin 本身就是全站权限；"
            "要限定 Book 请改用 read / write 作用域"
        )


def issue_token(
    session: Session,
    *,
    name: str,
    scopes: list[str] | tuple[str, ...] | str = DEFAULT_SCOPES,
    created_by: int | None = None,
    expires_in_days: int | None = None,
    book_ids: list[int] | tuple[int, ...] | str | None = None,
) -> tuple[ApiToken, str]:
    """创建 Token，返回 (记录, 明文)。明文只此一次。"""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValidationFailed("Token 名称必填")
    if len(clean_name) > 80:
        raise ValidationFailed("Token 名称不能超过 80 个字符")
    clean_scopes = normalize_scopes(scopes)
    clean_books = normalize_book_ids(book_ids)
    ensure_scope_combination(clean_scopes, clean_books)
    existing = session.execute(select(ApiToken).where(ApiToken.name == clean_name)).scalar_one_or_none()
    if existing is not None:
        raise ValidationFailed("同名 Token 已存在")

    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    expires_at = None
    if expires_in_days:
        expires_at = utcnow() + timedelta(days=int(expires_in_days))

    token = ApiToken(
        name=clean_name,
        token_hash=hash_token(raw),
        prefix=raw[:11],
        scopes=",".join(clean_scopes),
        book_scope=",".join(str(item) for item in clean_books),
        created_by=created_by,
        expires_at=expires_at,
    )
    session.add(token)
    session.flush()
    return token, raw


def verify_token(session: Session, raw: str) -> ApiToken | None:
    """按哈希查表并检查吊销/过期；命中时更新 last_used_at。"""
    if not raw:
        return None
    token = session.execute(
        select(ApiToken).where(ApiToken.token_hash == hash_token(raw))
    ).scalar_one_or_none()
    if token is None or token.revoked_at is not None:
        return None
    now = utcnow()
    if token.expires_at is not None and token.expires_at <= now:
        return None
    token.last_used_at = now
    session.flush()
    return token


def get_token(session: Session, token_id: int) -> ApiToken | None:
    return session.get(ApiToken, token_id)


def revoke_token(session: Session, token: ApiToken) -> None:
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        session.flush()


def is_active(token: ApiToken, now: datetime | None = None) -> bool:
    """还能用的 Token：没吊销、没过期。"""
    return token.revoked_at is None and not _expired(token, now)


def delete_token(session: Session, token: ApiToken) -> None:
    """物理删除一条 Token 记录。

    只允许删「已经不能用」的（吊销或过期）：还能用的必须先把吊销做成一次独立动作，
    否则删掉再用同一明文重建就能悄悄延命，审计里也看不出"这个 Token 哪天失效"。
    """
    if is_active(token):
        raise ValidationFailed("Token 仍在有效期内，请先吊销再删除")
    session.delete(token)
    session.flush()


def list_tokens(session: Session) -> list[ApiToken]:
    return list(session.execute(select(ApiToken).order_by(ApiToken.created_at.desc())).scalars())


def ensure_bootstrap_token(session: Session, raw: str, *, name: str = "bootstrap") -> ApiToken | None:
    """把环境变量里的明文 Token 落库（幂等）。已存在同哈希则直接返回。"""
    value = (raw or "").strip()
    if not value:
        return None
    existing = session.execute(
        select(ApiToken).where(ApiToken.token_hash == hash_token(value))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    candidate = name
    index = 2
    while session.execute(select(ApiToken).where(ApiToken.name == candidate)).scalar_one_or_none():
        candidate = f"{name}-{index}"
        index += 1
    token = ApiToken(
        name=candidate,
        token_hash=hash_token(value),
        prefix=value[:11],
        scopes="admin",
    )
    session.add(token)
    session.flush()
    return token


def describe(token: ApiToken) -> dict[str, object]:
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.prefix,
        "scopes": scopes_of(token),
        "book_ids": book_scope_of(token),
        "created_at": token.created_at,
        "expires_at": token.expires_at,
        "revoked_at": token.revoked_at,
        "last_used_at": token.last_used_at,
        "active": token.revoked_at is None and not _expired(token),
    }


def _expired(token: ApiToken, now: datetime | None = None) -> bool:
    if token.expires_at is None:
        return False
    return token.expires_at <= (now or utcnow())
