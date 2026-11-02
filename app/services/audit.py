"""审计日志写入。"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, User, utcnow


def record(
    session: Session,
    *,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: int | None = None,
    target_label: str = "",
    book_id: int | None = None,
    detail: dict[str, object] | None = None,
    ip: str = "",
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_name=(actor.display_name or actor.username) if actor else "system",
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label[:200],
        book_id=book_id,
        detail=json.dumps(detail or {}, ensure_ascii=False),
        ip=ip[:64],
    )
    session.add(entry)
    return entry


def query_rows(
    session: Session,
    *,
    book_id: int | None = None,
    actor: str = "",
    action: str = "",
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    """审计查询的唯一入口：网页、查询接口与 CSV 导出都走它，保证过滤语义一致。"""
    conditions = []
    if book_id is not None:
        conditions.append(AuditLog.book_id == book_id)
    if actor.strip():
        conditions.append(AuditLog.actor_name.ilike(f"%{actor.strip()}%"))
    if action.strip():
        conditions.append(AuditLog.action.ilike(f"{action.strip()}%"))
    if since is not None:
        conditions.append(AuditLog.created_at >= since)
    if until is not None:
        conditions.append(AuditLog.created_at <= until)
    stmt = select(AuditLog).where(*conditions).order_by(
        AuditLog.created_at.desc(), AuditLog.id.desc()
    )
    if limit:
        stmt = stmt.limit(limit).offset(max(0, offset))
    return list(session.execute(stmt).scalars())


def count_rows(
    session: Session,
    *,
    book_id: int | None = None,
    actor: str = "",
    action: str = "",
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    conditions = []
    if book_id is not None:
        conditions.append(AuditLog.book_id == book_id)
    if actor.strip():
        conditions.append(AuditLog.actor_name.ilike(f"%{actor.strip()}%"))
    if action.strip():
        conditions.append(AuditLog.action.ilike(f"{action.strip()}%"))
    if since is not None:
        conditions.append(AuditLog.created_at >= since)
    if until is not None:
        conditions.append(AuditLog.created_at <= until)
    return int(
        session.execute(select(func.count()).select_from(AuditLog).where(*conditions)).scalar_one()
    )


CSV_COLUMNS = ("created_at", "actor", "action", "target_type", "target_id", "target_label", "book_id", "ip", "detail")


def export_csv(rows: list[AuditLog]) -> str:
    """导出为带 BOM 的 CSV 文本（Excel 双击打开不乱码）。"""
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                row.actor_name,
                row.action,
                row.target_type,
                row.target_id if row.target_id is not None else "",
                row.target_label,
                row.book_id if row.book_id is not None else "",
                row.ip,
                json.dumps(detail_of(row), ensure_ascii=False),
            ]
        )
    return buffer.getvalue()


def cleanup(session: Session, retention_days: int, *, now: datetime | None = None) -> dict[str, object]:
    """按保留期删除旧审计；retention_days<=0 表示永久保留。"""
    if not retention_days or retention_days <= 0:
        return {"deleted": 0, "oldest": None, "cutoff": None, "retention_days": retention_days}
    now = now or utcnow()
    cutoff = now - timedelta(days=retention_days)
    oldest = session.execute(
        select(func.min(AuditLog.created_at)).where(AuditLog.created_at < cutoff)
    ).scalar()
    result = session.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    deleted = int(result.rowcount or 0)
    session.flush()
    return {
        "deleted": deleted,
        "oldest": oldest,
        "cutoff": cutoff,
        "retention_days": retention_days,
    }


def detail_of(entry: AuditLog) -> dict[str, object]:
    try:
        value = json.loads(entry.detail or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
