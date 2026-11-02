"""幂等键：同键 + 同请求指纹在 TTL 内只执行一次。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.errors import Conflict
from app.models import IdempotencyKey, utcnow

DEFAULT_TTL_SECONDS = 24 * 3600


@dataclass(frozen=True)
class Replay:
    status_code: int
    payload: dict[str, object]


def fingerprint(*parts: object) -> str:
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lookup(session: Session, key: str, *, token_id: int | None, request_fingerprint: str) -> Replay | None:
    """命中且指纹一致 → 回放；指纹不同 → 409；过期 → 视为未命中。"""
    if not key:
        return None
    record = session.get(IdempotencyKey, key[:128])
    if record is None:
        return None
    if record.expires_at <= utcnow():
        session.delete(record)
        session.flush()
        return None
    if record.fingerprint != request_fingerprint:
        raise Conflict("同一 Idempotency-Key 被用于不同的请求内容")
    try:
        payload = json.loads(record.payload)
    except json.JSONDecodeError:
        payload = {}
    return Replay(status_code=record.status_code, payload=payload)


def remember(
    session: Session,
    key: str,
    *,
    token_id: int | None,
    request_fingerprint: str,
    status_code: int,
    payload: dict[str, object],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> None:
    if not key:
        return
    now = utcnow()
    record = session.get(IdempotencyKey, key[:128])
    if record is None:
        record = IdempotencyKey(
            key=key[:128],
            token_id=token_id,
            fingerprint=request_fingerprint,
            status_code=status_code,
            payload=json.dumps(payload, ensure_ascii=False, default=str),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        session.add(record)
    else:
        record.status_code = status_code
        record.payload = json.dumps(payload, ensure_ascii=False, default=str)
        record.expires_at = now + timedelta(seconds=ttl_seconds)
    session.flush()


def cleanup(session: Session) -> int:
    result = session.execute(delete(IdempotencyKey).where(IdempotencyKey.expires_at <= utcnow()))
    session.flush()
    return int(result.rowcount or 0)
