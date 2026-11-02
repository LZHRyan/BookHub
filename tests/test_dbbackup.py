"""迁移前快照：URL 解析、快照内容、轮转与降级路径。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.dbbackup import database_file, snapshot


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO books (title) VALUES ('研发手册')")
    conn.commit()
    conn.close()


def test_database_file_parses_urls() -> None:
    assert database_file("sqlite:////data/bookhub.db") == Path("/data/bookhub.db")
    assert database_file("sqlite:///./data/bookhub.db") == Path("./data/bookhub.db")
    assert database_file("postgresql+psycopg://u:p@db:5432/bookhub") is None
    assert database_file("") is None


def test_snapshot_copies_data_and_rotates(tmp_path: Path) -> None:
    db = tmp_path / "bookhub.db"
    _make_db(db)
    out = tmp_path / "backups"

    created = [
        snapshot(db, out, keep=2, now=datetime(2026, 5, 1, hour, 0, 0, tzinfo=UTC))
        for hour in (1, 2, 3)
    ]
    assert all(path is not None for path in created)
    assert created[0] is not None and not created[0].exists()  # 最旧的一份被轮转掉
    assert created[1] is not None and created[1].exists()
    assert created[2] is not None and created[2].exists()

    kept = sorted(out.glob("pre-upgrade-*.db"))
    assert len(kept) == 2

    conn = sqlite3.connect(kept[-1])
    try:
        assert conn.execute("SELECT title FROM books").fetchone()[0] == "研发手册"
    finally:
        conn.close()


def test_snapshot_excludes_uncommitted_wal_rows(tmp_path: Path) -> None:
    db = tmp_path / "bookhub.db"
    _make_db(db)

    writer = sqlite3.connect(db)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("INSERT INTO books (title) VALUES ('未提交')")  # 故意不 commit
    try:
        target = snapshot(db, tmp_path / "backups")
    finally:
        writer.rollback()
        writer.close()

    assert target is not None
    conn = sqlite3.connect(target)
    try:
        assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
    finally:
        conn.close()


def test_snapshot_returns_none_when_db_missing(tmp_path: Path) -> None:
    # 首次启动没有库文件：不算失败，entrypoint 继续往下走
    assert snapshot(tmp_path / "missing.db", tmp_path / "backups") is None
    assert not (tmp_path / "backups").exists()
