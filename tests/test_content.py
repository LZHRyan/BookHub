"""Book、章与节的服务层行为。"""

from __future__ import annotations

import pytest

from app.errors import Conflict, ContentTooLong, NotFound, ValidationFailed
from app.models import Book
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import sections as sections_service


def test_create_book_generates_fallback_slug(db) -> None:
    book = books_service.create_book(db, title="运维手册")
    db.commit()
    assert book.slug.startswith("book-")
    assert len(book.slug) == len("book-") + 6
    assert book.visibility == "public"


def test_slug_conflict_gets_suffix(db) -> None:
    first = books_service.create_book(db, title="Guide", slug_raw="guide")
    second = books_service.create_book(db, title="Guide 2", slug_raw="guide")
    third = books_service.create_book(db, title="Guide 3", slug_raw="guide")
    db.commit()
    assert (first.slug, second.slug, third.slug) == ("guide", "guide-2", "guide-3")


def test_title_required(db) -> None:
    with pytest.raises(ValidationFailed):
        books_service.create_book(db, title="   ")


def test_soft_deleted_book_frees_slug(db) -> None:
    book = books_service.create_book(db, title="Guide", slug_raw="guide")
    db.commit()
    books_service.soft_delete_book(db, book)
    db.commit()
    again = books_service.create_book(db, title="Guide", slug_raw="guide")
    db.commit()
    assert again.slug == "guide"
    rows, total = books_service.list_books(db)
    assert total == 1
    with pytest.raises(NotFound):
        books_service.get_book(db, book.id)


def test_visibility_filtering(db) -> None:
    books_service.create_book(db, title="Public", visibility="public")
    books_service.create_book(db, title="Hidden", visibility="unlisted")
    db.commit()
    public_rows, public_total = books_service.list_books(db, visibility="public")
    assert public_total == 1
    assert public_rows[0].visibility == "public"
    all_rows, all_total = books_service.list_books(db, visibility=None)
    assert all_total == 2


def test_chapter_order_and_directory(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    first, _ = chapters_service.create_chapter_with_section(db, book, title="第一章", raw="# 一")
    second, _ = chapters_service.create_chapter_with_section(db, book, title="第二章", raw="# 二")
    db.commit()
    assert first.sort_order < second.sort_order
    chapters = chapters_service.ordered_chapters(db, book.id)
    assert [chapter.title for chapter in chapters] == ["第一章", "第二章"]


def test_chapter_slug_conflict_within_book(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    one, _ = chapters_service.create_chapter_with_section(
        db, book, title="Install", raw="a", slug_raw="install"
    )
    two, _ = chapters_service.create_chapter_with_section(
        db, book, title="Install 2", raw="b", slug_raw="install"
    )
    db.commit()
    assert one.slug == "install"
    assert two.slug == "install-2"


def test_section_slug_conflict_within_chapter(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    chapter = chapters_service.create_chapter(db, book, title="部署")
    db.commit()
    one = sections_service.create_section(db, chapter, title="Install", raw="a", slug_raw="install")
    two = sections_service.create_section(db, chapter, title="Install 2", raw="b", slug_raw="install")
    db.commit()
    assert one.slug == "install"
    assert two.slug == "install-2"


def test_replace_creates_new_version(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    _chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="部署", raw="# v1"
    )
    db.commit()
    sections_service.replace_content(db, section, raw="# v2", note="第二次")
    db.commit()
    assert section.current_version_no == 2
    versions = sections_service.list_versions(db, section)
    assert [version.version_no for version in versions] == [2, 1]
    assert versions[0].content_raw == "# v2"
    assert versions[1].content_raw == "# v1"


def test_replace_base_version_conflict(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    _chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="部署", raw="# v1"
    )
    db.commit()
    sections_service.replace_content(db, section, raw="# v2", base_version=1)
    db.commit()
    with pytest.raises(Conflict):
        sections_service.replace_content(db, section, raw="# v3", base_version=1)
    db.rollback()
    assert section.current_version_no == 2
    assert section.content_raw == "# v2"


def test_content_too_long_rejected(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    with pytest.raises(ContentTooLong):
        chapters_service.create_chapter_with_section(
            db, book, title="Big", raw="x" * 50, max_chars=10
        )


def test_publish_keeps_first_published_at(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    chapter, _section = chapters_service.create_chapter_with_section(
        db, book, title="Draft", raw="body"
    )
    db.commit()
    assert chapter.status == "draft"
    chapters_service.set_status(db, chapter, "published")
    db.commit()
    first = chapter.published_at
    assert first is not None
    chapters_service.set_status(db, chapter, "draft")
    chapters_service.set_status(db, chapter, "published")
    db.commit()
    assert chapter.published_at == first


def test_soft_delete_and_restore(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    chapter, _section = chapters_service.create_chapter_with_section(
        db, book, title="Intro", raw="body", slug_raw="intro"
    )
    db.commit()
    chapters_service.soft_delete_chapter(db, chapter)
    db.commit()
    assert chapters_service.ordered_chapters(db, book.id) == []
    replacement, _ = chapters_service.create_chapter_with_section(
        db, book, title="Intro new", raw="body2", slug_raw="intro"
    )
    db.commit()
    assert replacement.slug == "intro"
    chapters_service.restore_chapter(db, chapter)
    db.commit()
    assert chapter.deleted_at is None
    assert chapter.slug == "intro-2"


def test_move_chapter(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    a, _ = chapters_service.create_chapter_with_section(db, book, title="A", raw="a")
    chapters_service.create_chapter_with_section(db, book, title="B", raw="b")
    c, _ = chapters_service.create_chapter_with_section(db, book, title="C", raw="c")
    db.commit()
    chapters_service.move_chapter(db, c, -1)
    db.commit()
    assert [chapter.title for chapter in chapters_service.ordered_chapters(db, book.id)] == ["A", "C", "B"]
    chapters_service.move_chapter(db, a, -1)
    db.commit()
    assert [chapter.title for chapter in chapters_service.ordered_chapters(db, book.id)] == ["A", "C", "B"]


def test_reorder_requires_full_set(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    a, _ = chapters_service.create_chapter_with_section(db, book, title="A", raw="a")
    chapters_service.create_chapter_with_section(db, book, title="B", raw="b")
    db.commit()
    with pytest.raises(ValidationFailed):
        chapters_service.reorder_chapters(db, book.id, [a.id])


def test_rollback_appends_version(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    _chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="部署", raw="# v1"
    )
    db.commit()
    sections_service.replace_content(db, section, raw="# v2")
    sections_service.replace_content(db, section, raw="# v3")
    db.commit()
    sections_service.rollback(db, section, 1)
    db.commit()
    assert section.current_version_no == 4
    assert section.content_raw == "# v1"
    assert len(sections_service.list_versions(db, section)) == 4


def test_rollback_unknown_version(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    _chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="部署", raw="# v1"
    )
    db.commit()
    with pytest.raises(NotFound):
        sections_service.rollback(db, section, 99)


def test_version_retention(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    _chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="部署", raw="v1"
    )
    db.commit()
    for index in range(2, 8):
        sections_service.replace_content(db, section, raw=f"v{index}", retention=3)
    db.commit()
    versions = sections_service.list_versions(db, section)
    assert len(versions) == 3
    assert versions[0].version_no == section.current_version_no


def test_diff_versions(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    _chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="部署", raw="a\nb\nc"
    )
    db.commit()
    sections_service.replace_content(db, section, raw="a\nB\nc")
    db.commit()
    diff = sections_service.diff_versions(db, section, 1, 2)
    assert diff["identical"] is False
    kinds = {row["type"] for row in diff["rows"]}
    assert "delete" in kinds and "insert" in kinds


def test_draft_hidden_from_public_lookup(db) -> None:
    book = books_service.create_book(db, title="Handbook")
    chapters_service.create_chapter_with_section(
        db, book, title="Draft", raw="x", slug_raw="draft"
    )
    db.commit()
    with pytest.raises(NotFound):
        chapters_service.find_published_chapter(db, book.slug, "draft")


def test_audit_log_written(db) -> None:
    from sqlalchemy import select

    from app.models import AuditLog

    book = books_service.create_book(db, title="Handbook")
    _chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="部署", raw="x"
    )
    sections_service.replace_content(db, section, raw="y")
    db.commit()
    rows = db.execute(select(AuditLog)).scalars().all()
    actions = {row.action for row in rows}
    assert {"book.create", "chapter.create", "section.create", "section.replace"} <= actions
    replace_log = next(row for row in rows if row.action == "section.replace")
    assert '"from_version": 1' in replace_log.detail
    assert '"to_version": 2' in replace_log.detail


# ---------------------------------------------------------------- 格式下放到节


def test_create_book_rejects_unknown_format(db) -> None:
    from sqlalchemy import select

    with pytest.raises(ValidationFailed):
        books_service.create_book(db, title="混合书", fmt="mixed")
    with pytest.raises(ValidationFailed):
        books_service.create_book(db, title="空格式", fmt="")
    assert db.execute(select(Book)).scalars().all() == []


def test_book_format_locked_once_chapters_exist(db) -> None:
    """整本单一格式：有章之后不能改 Book 的文档类型。"""
    book = books_service.create_book(db, title="Markdown 书", fmt="markdown")
    _chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="第一章", raw="# 一"
    )
    db.commit()
    with pytest.raises(ValidationFailed) as excinfo:
        books_service.update_book(db, book, fmt="html")
    assert "文档类型" in str(excinfo.value)
    db.rollback()
    assert book.format == "markdown"
    db.refresh(section)
    assert section.format == "markdown"


def test_empty_book_can_switch_format(db) -> None:
    book = books_service.create_book(db, title="空书", fmt="markdown")
    db.commit()
    books_service.update_book(db, book, fmt="html")
    db.commit()
    assert book.format == "html"


def test_section_format_must_match_book(db) -> None:
    """节不指定格式时继承 Book；指定了别的格式直接拒绝（不允许混排）。"""
    book = books_service.create_book(db, title="HTML 书", fmt="html")
    chapter = chapters_service.create_chapter(db, book, title="页面")
    db.commit()
    inherited = sections_service.create_section(db, chapter, title="默认", raw="<h1>hi</h1>")
    db.commit()
    assert inherited.format == "html"

    with pytest.raises(ValidationFailed) as excinfo:
        sections_service.create_section(db, chapter, title="混排", raw="# md", fmt="markdown")
    assert "HTML" in str(excinfo.value)
    db.rollback()
    assert [item.format for item in sections_service.ordered_sections(db, chapter.id)] == ["html"]


def test_replace_rejects_other_format_and_bumps_same_format(db) -> None:
    book = books_service.create_book(db, title="Markdown 书", fmt="markdown")
    _chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="一", raw="# v1"
    )
    db.commit()

    with pytest.raises(ValidationFailed):
        sections_service.replace_content(db, section, raw="<h1>v2</h1>", fmt="html")
    db.rollback()
    assert section.current_version_no == 1

    sections_service.replace_content(db, section, raw="# v2", fmt="markdown")
    db.commit()
    db.refresh(section)
    assert section.current_version_no == 2
    assert section.format == "markdown"
    assert section.content_raw == "# v2"


def test_export_and_api_format_consistency(client, db) -> None:
    """API 的 Book 表示与整本导出都必须逐节体现各自格式。"""
    import io
    import zipfile

    md_book = books_service.create_book(db, title="MD 书", slug_raw="md-book", fmt="markdown")
    chapters_service.create_chapter_with_section(
        db, md_book, title="a", raw="# a", slug_raw="a", status="published"
    )
    html_book = books_service.create_book(db, title="HTML 书", slug_raw="html-book", fmt="html")
    chapters_service.create_chapter_with_section(
        db, html_book, title="b", raw="<h1>b</h1>", slug_raw="b", status="published"
    )
    db.commit()

    for slug, expected, suffix in (("md-book", "markdown", ".md"), ("html-book", "html", ".html")):
        detail = client.get(f"/api/v1/books/{slug}").json()
        assert detail["format"] == expected
        formats = {
            section["format"] for chapter in detail["chapters"] for section in chapter["sections"]
        }
        assert formats == {expected}
        archive = client.get(f"/api/v1/books/{slug}/export?format=zip")
        with zipfile.ZipFile(io.BytesIO(archive.content)) as archive_file:
            names = [name for name in archive_file.namelist() if name != "book.json"]
        assert names and all(name.endswith(suffix) for name in names)
