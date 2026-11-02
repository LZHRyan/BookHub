"""迁移前的 SQLite 一致性快照。

容器 entrypoint 在发现「待执行迁移」时会先调用本模块，把当前库做成一份
`{DATA_DIR}/backups/pre-upgrade-<UTC时间>.db`，再执行 `alembic upgrade head`。
这样即便新版迁移有破坏性改动（删列、改类型），也能从启动瞬间的快照回退。

设计约束：
- 只用标准库 sqlite3 的 backup() API：WAL 模式下依然能得到一致的副本；
- 只做 SQLite；Postgres 部署不做自动快照（entrypoint 只打印提示，运维用 pg_dump）；
- 快照失败**不阻塞启动**，由调用方决定告警（数据可用性优先于流程完美）；
- 旧快照按数量轮转，避免把命名卷撑爆。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_KEEP = 5
DEFAULT_LABEL = "pre-upgrade"


def database_file(database_url: str) -> Path | None:
    """从 SQLAlchemy URL 解析 SQLite 库文件路径；非 SQLite 返回 None。"""
    url = (database_url or "").strip()
    if not url.startswith("sqlite"):
        return None
    from sqlalchemy.engine.url import make_url

    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database:
        return None
    return Path(parsed.database).expanduser()


def snapshot(
    db_path: Path,
    out_dir: Path,
    *,
    label: str = DEFAULT_LABEL,
    keep: int = DEFAULT_KEEP,
    now: datetime | None = None,
) -> Path | None:
    """给 SQLite 库做一份一致副本；库文件不存在（首次启动）时返回 None。"""
    db_path = Path(db_path)
    if not db_path.exists():
        return None

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / f"{label}-{stamp}.db"

    source = sqlite3.connect(str(db_path))
    try:
        copy = sqlite3.connect(str(target))
        try:
            with copy:
                source.backup(copy)
        finally:
            copy.close()
    except Exception:
        source.close()
        target.unlink(missing_ok=True)
        raise
    else:
        source.close()

    check = sqlite3.connect(str(target))
    try:
        verdict = check.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        check.close()
    if verdict != "ok":
        target.unlink(missing_ok=True)
        raise RuntimeError(f"快照完整性检查失败：{verdict}")

    if keep > 0:
        for stale in sorted(out_dir.glob(f"{label}-*.db"))[:-keep]:
            stale.unlink(missing_ok=True)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="迁移前 SQLite 一致性快照")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "sqlite:////data/bookhub.db"),
    )
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "/data"))
    parser.add_argument(
        "--keep",
        type=int,
        default=int(os.environ.get("PRE_UPGRADE_BACKUP_KEEP", DEFAULT_KEEP)),
    )
    parser.add_argument("--label", default=DEFAULT_LABEL)
    args = parser.parse_args(argv)

    db_path = database_file(args.database_url)
    if db_path is None:
        print(f"skip: DATABASE_URL 不是 SQLite（{args.database_url}）", file=sys.stderr)
        return 0
    try:
        target = snapshot(
            db_path, Path(args.data_dir) / "backups", label=args.label, keep=args.keep
        )
    except Exception as exc:  # pragma: no cover - 依赖真实文件系统故障
        print(f"error: 快照失败：{exc}", file=sys.stderr)
        return 1
    if target is None:
        print(f"skip: 库文件不存在（{db_path}），按首次启动处理", file=sys.stderr)
        return 0
    print(f"snapshot: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
