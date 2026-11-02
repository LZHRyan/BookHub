"""管理员账号服务。"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ValidationFailed
from app.models import ROLE_ADMIN, ROLES, User, utcnow
from app.security import (
    DUMMY_PASSWORD_HASH,
    PasswordError,
    hash_password,
    password_policy_errors,
    verify_password,
)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")


def normalize_username(raw: str) -> str:
    return (raw or "").strip().lower()


def create_user(
    session: Session,
    *,
    username: str,
    password: str,
    display_name: str = "",
    role: str = ROLE_ADMIN,
) -> User:
    name = normalize_username(username)
    if not USERNAME_RE.match(name):
        raise ValidationFailed("用户名只能包含字母、数字、点、下划线与连字符，长度 3-64")
    if role not in ROLES:
        raise ValidationFailed("角色取值非法")
    problems = password_policy_errors(password, name)
    if problems:
        raise ValidationFailed("；".join(problems))
    exists = session.execute(select(User).where(User.username == name)).scalar_one_or_none()
    if exists is not None:
        raise ValidationFailed("该用户名已存在")
    try:
        password_hash = hash_password(password)
    except PasswordError as exc:
        raise ValidationFailed(str(exc)) from exc
    user = User(
        username=name,
        display_name=(display_name or name).strip(),
        password_hash=password_hash,
        role=role,
        is_active=True,
        session_epoch=1,
    )
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, username: str, password: str) -> User | None:
    name = normalize_username(username)
    user = session.execute(select(User).where(User.username == name)).scalar_one_or_none()
    if user is None:
        # 用合法的假 hash 真算一次，避免用响应时间判断账号是否存在
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def mark_login(session: Session, user: User) -> None:
    user.last_login_at = utcnow()
    session.flush()


def set_password(user: User, password: str) -> None:
    problems = password_policy_errors(password, user.username)
    if problems:
        raise ValidationFailed("；".join(problems))
    try:
        user.password_hash = hash_password(password)
    except PasswordError as exc:
        raise ValidationFailed(str(exc)) from exc
    user.session_epoch += 1


def set_active(user: User, active: bool) -> None:
    user.is_active = active
    if not active:
        user.session_epoch += 1


def ensure_initial_admin(session: Session, settings: Settings) -> bool:
    """幂等创建初始管理员；变量缺失时什么都不做。"""
    username = settings.initial_admin_user
    password = settings.initial_admin_password
    if not username or not password:
        return False
    name = normalize_username(username)
    existing = session.execute(select(User).where(User.username == name)).scalar_one_or_none()
    if existing is not None:
        return False
    problems = password_policy_errors(password, name)
    if problems:
        raise ValidationFailed(f"初始管理员密码不符合策略：{'；'.join(problems)}")
    user = create_user(
        session,
        username=name,
        password=password,
        display_name=name,
        role=ROLE_ADMIN,
    )
    session.flush()
    return user is not None
