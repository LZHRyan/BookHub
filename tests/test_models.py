"""数据模型：约束、默认值与 FTS 索引同步。"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.models import AuditLog, Book, Chapter, SectionVersion, SiteSetting, User
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import sections as sections_service
from app.services.search import index_section, remove_from_index


def test_sqlite_wal_enabled(db) -> None:
    assert db.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
    assert db.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_user_defaults(db) -> None:
    user = User(username="tester", display_name="t", password_hash="x")
    db.add(user)
    db.commit()
    assert user.role == "editor"
    assert user.is_active is True
    assert user.session_epoch == 1
    assert user.created_at is not None


def test_book_slug_unique_when_active(db) -> None:
    books_service.create_book(db, title="A", slug_raw="dup")
    db.commit()
    books_service.create_book(db, title="B", slug_raw="dup")
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(Book(slug="dup", title="C"))
        db.flush()
    db.rollback()


def test_section_version_unique(db) -> None:
    book = books_service.create_book(db, title="A")
    _chapter, section = chapters_service.create_chapter_with_section(db, book, title="c", raw="x")
    db.commit()
    db.add(SectionVersion(section_id=section.id, version_no=1, content_raw="dup"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_chapter_defaults(db) -> None:
    book = books_service.create_book(db, title="A")
    chapter, section = chapters_service.create_chapter_with_section(db, book, title="c", raw="# hi")
    db.commit()
    # 章只剩目录字段：没有正文、格式与版本
    assert chapter.status == "draft"
    assert chapter.published_at is None
    assert not hasattr(chapter, "content_raw")
    assert not hasattr(chapter, "current_version_no")
    # 正文与版本都在节上
    assert section.format == "markdown"
    assert section.current_version_no == 1
    assert section.word_count > 0
    assert section.content_checksum


def test_fts_row_per_section(db) -> None:
    book = books_service.create_book(db, title="A")
    chapters_service.create_chapter_with_section(db, book, title="一", raw="知识库")
    chapters_service.create_chapter_with_section(db, book, title="二", raw="部署")
    db.commit()
    assert db.execute(text("SELECT COUNT(*) FROM chapter_fts")).scalar_one() == 2


def test_fts_remove_and_reindex(db) -> None:
    book = books_service.create_book(db, title="A")
    _chapter, section = chapters_service.create_chapter_with_section(db, book, title="一", raw="知识库")
    db.commit()
    index_section(
        db,
        section_id=section.id,
        book_id=book.id,
        chapter_id=section.chapter_id,
        title=section.title,
        body="知识库 知识",
    )
    db.commit()
    assert db.execute(text("SELECT COUNT(*) FROM chapter_fts WHERE rowid = :rid"), {"rid": section.id}).scalar_one() == 1
    remove_from_index(db, section.id)
    db.commit()
    assert db.execute(text("SELECT COUNT(*) FROM chapter_fts WHERE rowid = :rid"), {"rid": section.id}).scalar_one() == 0


def test_site_setting_key_primary(db) -> None:
    db.add(SiteSetting(key="site_name", value="A"))
    db.commit()
    assert db.get(SiteSetting, "site_name").value == "A"


def test_audit_detail_default(db) -> None:
    db.add(AuditLog(action="x", target_type="book"))
    db.commit()
    entry = db.execute(select(AuditLog)).scalars().one()
    assert entry.detail == "{}"
    assert entry.actor_name == ""


def test_chapter_counts(db) -> None:
    book = books_service.create_book(db, title="A")
    chapters_service.create_chapter_with_section(db, book, title="pub", raw="x", status="published")
    chapters_service.create_chapter_with_section(db, book, title="draft", raw="y")
    db.commit()
    counts = books_service.chapter_counts(db, [book.id])
    assert counts[book.id] == 1
    all_counts = books_service.chapter_counts(db, [book.id], published_only=False)
    assert all_counts[book.id] == 2
    assert db.execute(select(func.count()).select_from(Chapter)).scalar_one() == 2


def test_section_counts_per_chapter(db) -> None:
    book = books_service.create_book(db, title="A")
    chapter = chapters_service.create_chapter(db, book, title="c")
    db.commit()
    sections_service.create_section(db, chapter, title="一", raw="x")
    sections_service.create_section(db, chapter, title="二", raw="y")
    db.commit()
    assert sections_service.section_counts(db, [chapter.id])[chapter.id] == 2
