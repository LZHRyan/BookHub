"""密码哈希、签名会话与 CSRF token。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from contextlib import suppress
from dataclasses import dataclass

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

PASSWORD_MIN_LENGTH = 10
BCRYPT_MAX_BYTES = 72
SESSION_SALT = "bookhub-session-v1"
CSRF_SALT = "bookhub-csrf-v1"


class PasswordError(ValueError):
    """密码不符合策略。"""


def hash_password(password: str) -> str:
    """bcrypt 哈希；超长密码在此处拒绝而不是静默截断。"""
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        raise PasswordError(f"密码不能超过 {BCRYPT_MAX_BYTES} 字节")
    if not encoded:
        raise PasswordError("密码不能为空")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=12)).decode("ascii")


# 用户不存在时拿它做一次**真实**校验，让两条路径耗时接近，避免用响应时间枚举账号。
# 必须是一个合法 hash：拼出来的假串会让 bcrypt 立刻抛 ValueError（等于没算），
# 既泄露时间差，又会在超长密码分支上抛未捕获异常。
DUMMY_PASSWORD_HASH = "$2b$12$gRZYyzGq06Lt1gqLbnUvsuz3mF7yZIc.6M2lc2qAkqpMHWDI5mHzG"


def _bcrypt_work(password: bytes, password_hash: str) -> None:
    """只花一次哈希时间，不关心结果；任何异常都吞掉（调用方只用于等时）。"""
    target = (password_hash or DUMMY_PASSWORD_HASH).encode("ascii", "ignore")
    with suppress(ValueError, TypeError):
        bcrypt.hashpw(password[:BCRYPT_MAX_BYTES] or b"x", target)


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")
    if not encoded or len(encoded) > BCRYPT_MAX_BYTES:
        # 超长/空密码也要花掉一次哈希时间，且绝不能抛异常
        _bcrypt_work(encoded, password_hash)
        return False
    try:
        return bcrypt.checkpw(encoded, (password_hash or DUMMY_PASSWORD_HASH).encode("ascii"))
    except (ValueError, TypeError):
        return False


def password_policy_errors(password: str, username: str = "") -> list[str]:
    """返回密码策略问题列表，空列表表示通过。"""
    problems: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"密码至少需要 {PASSWORD_MIN_LENGTH} 个字符")
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        problems.append(f"密码不能超过 {BCRYPT_MAX_BYTES} 字节")
    if username and password.strip().lower() == username.strip().lower():
        problems.append("密码不能与用户名相同")
    if password and (password.isdigit() or password.isalpha()):
        problems.append("密码需要同时包含字母与数字等两类以上字符")
    return problems


@dataclass(frozen=True)
class SessionData:
    user_id: int
    epoch: int
    nonce: str


def _serializer(secret_key: str, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        secret_key, salt=salt, signer_kwargs={"digest_method": hashlib.sha256}
    )


def issue_session(secret_key: str, user_id: int, epoch: int) -> str:
    payload = {"u": int(user_id), "e": int(epoch), "n": secrets.token_hex(8)}
    return _serializer(secret_key, SESSION_SALT).dumps(payload)


def read_session(secret_key: str, token: str, max_age: int) -> SessionData | None:
    if not token:
        return None
    try:
        payload = _serializer(secret_key, SESSION_SALT).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return SessionData(user_id=int(payload["u"]), epoch=int(payload["e"]), nonce=str(payload["n"]))
    except (KeyError, TypeError, ValueError):
        return None


def issue_csrf(secret_key: str, session: SessionData) -> str:
    return _serializer(secret_key, CSRF_SALT).dumps({"u": session.user_id, "n": session.nonce})


def verify_csrf(secret_key: str, session: SessionData, token: str, max_age: int) -> bool:
    if not token:
        return False
    try:
        payload = _serializer(secret_key, CSRF_SALT).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return False
    if not isinstance(payload, dict):
        return False
    return (
        str(payload.get("u")) == str(session.user_id)
        and hmac.compare_digest(str(payload.get("n", "")), session.nonce)
    )


def safe_compare(a: str, b: str) -> bool:
    """定长比较，用于 API Key 这类共享密钥。"""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
