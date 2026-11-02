"""章 → 节：URL 规则、多文件上传、节级版本与幂等保存。"""

from __future__ import annotations

import pytest

from app.errors import ValidationFailed
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import sections as sections_service

from .conftest import csrf_token


def _book(db, *, title="节测试手册"):
    book = books_service.create_book(db, title=title, fmt="markdown")
    db.commit()
    return book


def _multi_chapter(db, book, *, status="published"):
    """一章三节，slug 固定好方便断言 URL。"""
    chapter = chapters_service.create_chapter(db, book, title="第一章", slug_raw="chapter-1", status=status)
    db.commit()
    sections_service.create_section(db, chapter, title="概述", raw="# 概述", slug_raw="overview")
    sections_service.create_section(db, chapter, title="架构", raw="# 架构", slug_raw="architecture")
    sections_service.create_section(db, chapter, title="示例", raw="# 示例", slug_raw="examples")
    db.commit()
    return chapter


# ---------------------------------------------------------------- URL 规则


def test_single_section_chapter_renders_content_directly(client, db) -> None:
    """只有一节时，章页直接显示这一节正文（兼容存量链接）。"""
    book = _book(db)
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="欢迎", raw="# 欢迎\n\n这里是正文", slug_raw="welcome", status="published"
    )
    db.commit()

    chapter_page = client.get(f"/b/{book.slug}/{chapter.slug}")
    assert chapter_page.status_code == 200
    assert "这里是正文" in chapter_page.text
    # 也照样能走节页
    section_page = client.get(f"/b/{book.slug}/{chapter.slug}/{section.slug}")
    assert section_page.status_code == 200
    assert "这里是正文" in section_page.text


def test_multi_section_chapter_renders_index(client, db) -> None:
    book = _book(db)
    chapter = _multi_chapter(db, book)

    index_page = client.get(f"/b/{book.slug}/{chapter.slug}")
    assert index_page.status_code == 200
    # 索引页只列节，不渲染正文
    assert "概述" in index_page.text and "架构" in index_page.text
    assert 'id="article-body"' not in index_page.text
    assert f"/b/{book.slug}/{chapter.slug}/overview" in index_page.text

    section_page = client.get(f"/b/{book.slug}/{chapter.slug}/architecture")
    assert section_page.status_code == 200
    assert "架构" in section_page.text


def test_section_numbers_are_chapter_dot_index(client, db) -> None:
    book = _book(db)
    _multi_chapter(db, book)
    html = client.get(f"/b/{book.slug}").text
    assert "1.1" in html
    assert "1.2" in html
    assert "1.3" in html
    # 节序号跟着章号走
    rows = chapters_service.tree(db, book.id)
    assert [no for _section, no in rows[0]["sections"]] == ["1.1", "1.2", "1.3"]


def test_section_pages_404_when_chapter_is_draft(client, db) -> None:
    book = _book(db)
    chapter = _multi_chapter(db, book, status="draft")
    for slug in ("overview", "architecture"):
        assert client.get(f"/b/{book.slug}/{chapter.slug}/{slug}").status_code == 404
    # 章页本身也 404（草稿对访客不可见）
    assert client.get(f"/b/{book.slug}/{chapter.slug}").status_code == 404

    chapters_service.set_status(db, chapter, "published")
    db.commit()
    assert client.get(f"/b/{book.slug}/{chapter.slug}/overview").status_code == 200

    chapters_service.set_status(db, chapter, "draft")
    db.commit()
    assert client.get(f"/b/{book.slug}/{chapter.slug}/overview").status_code == 404


def test_unknown_section_404(client, db) -> None:
    book = _book(db)
    chapter = _multi_chapter(db, book)
    assert client.get(f"/b/{book.slug}/{chapter.slug}/nope").status_code == 404
    assert client.get(f"/b/{book.slug}/nope/overview").status_code == 404


# ---------------------------------------------------------------- 多文件上传


def test_multi_file_upload_creates_multiple_sections(admin, db) -> None:
    book = _book(db)
    token = csrf_token(admin, f"/admin/books/{book.id}/chapters/new")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/new",
        data={"csrf_token": token, "title": "第 1 章", "slug": "chapter-1", "status": "draft"},
        files=[
            ("upload", ("01-概述.md", "# 概述\n\n内容".encode(), "text/markdown")),
            ("upload", ("02-架构.md", "# 架构\n\n内容".encode(), "text/markdown")),
            ("upload", ("03-示例.md", "# 示例\n\n内容".encode(), "text/markdown")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text

    chapters = chapters_service.ordered_chapters(db, book.id)
    assert len(chapters) == 1
    sections = sections_service.ordered_sections(db, chapters[0].id)
    assert [item.title for item in sections] == ["01-概述", "02-架构", "03-示例"]
    # 整本 Markdown：三节都是 markdown
    assert [item.format for item in sections] == ["markdown", "markdown", "markdown"]
    assert [item.sort_order for item in sections] == [10, 20, 30]


def test_multi_file_upload_rejects_other_format(admin, db) -> None:
    """Markdown 书里混进 .html 会被拒绝，且整次请求不落库。"""
    book = _book(db)
    token = csrf_token(admin, f"/admin/books/{book.id}/chapters/new")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/new",
        data={"csrf_token": token, "title": "第 1 章", "slug": "chapter-1", "status": "draft"},
        files=[
            ("upload", ("01-概述.md", "# 概述".encode(), "text/markdown")),
            ("upload", ("02-示例.html", b"<h1>example</h1>", "text/html")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Markdown" in response.text
    assert chapters_service.ordered_chapters(db, book.id) == []


def test_upload_file_count_is_capped(tmp_path) -> None:
    """一次请求里的文件个数也有上限，挡住“上传一万个小文件”。"""
    from fastapi.testclient import TestClient

    from app.main import create_app

    from .conftest import ADMIN_PASSWORD, ADMIN_USER, make_settings, run_migrations

    settings = make_settings(tmp_path, max_upload_files=2)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        login = client.post(
            "/admin/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
            follow_redirects=False,
        )
        assert login.status_code == 303
        with app.state.sessionmaker() as session:
            book = books_service.create_book(session, title="限量书", fmt="markdown")
            session.commit()
            book_id = book.id
        token = csrf_token(client, f"/admin/books/{book_id}/chapters/new")
        response = client.post(
            f"/admin/books/{book_id}/chapters/new",
            data={"csrf_token": token, "title": "第 1 章", "slug": "chapter-1", "status": "draft"},
            files=[
                ("upload", ("01.md", b"# 1", "text/markdown")),
                ("upload", ("02.md", b"# 2", "text/markdown")),
                ("upload", ("03.md", b"# 3", "text/markdown")),
            ],
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert "一次最多上传 2 个文件" in response.text


def test_append_multiple_sections_via_section_form(admin, db) -> None:
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="章", slug_raw="c1")
    db.commit()
    token = csrf_token(admin, f"/admin/books/{book.id}/chapters/{chapter.id}/sections/new")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/sections/new",
        data={"csrf_token": token},
        files=[
            ("upload", ("a.md", b"# a", "text/markdown")),
            ("upload", ("b.md", b"# b", "text/markdown")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "notice=sections-created" in response.headers["location"]
    assert len(sections_service.ordered_sections(db, chapter.id)) == 2


# ---------------------------------------------------------------- 节级版本


def test_section_versions_are_independent(client, db) -> None:
    book = _book(db)
    chapter = _multi_chapter(db, book, status="draft")
    sections = sections_service.ordered_sections(db, chapter.id)
    overview, architecture = sections[0], sections[1]

    sections_service.replace_content(db, overview, raw="# 概述 v2")
    db.commit()
    assert overview.current_version_no == 2
    assert architecture.current_version_no == 1
    assert [v.version_no for v in sections_service.list_versions(db, architecture)] == [1]


def test_section_version_rollback(admin, db) -> None:
    book = _book(db)
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="章", raw="# v1"
    )
    db.commit()
    sections_service.replace_content(db, section, raw="# v2")
    sections_service.replace_content(db, section, raw="# v3")
    db.commit()

    token = csrf_token(
        admin, f"/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}/versions"
    )
    response = admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}/rollback/1",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db.refresh(section)
    assert section.content_raw == "# v1"
    assert section.current_version_no == 4
    # 章的状态不受回滚影响
    db.refresh(chapter)
    assert chapter.status == "draft"


def test_section_versions_pages_render(admin, db) -> None:
    book = _book(db)
    chapter = _multi_chapter(db, book)
    section = sections_service.ordered_sections(db, chapter.id)[0]
    sections_service.replace_content(db, section, raw="# 概述 v2")
    db.commit()

    chapter_versions = admin.get(f"/admin/books/{book.id}/chapters/{chapter.id}/versions")
    assert chapter_versions.status_code == 200
    assert "概述" in chapter_versions.text

    base = f"/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}"
    assert admin.get(f"{base}/versions").status_code == 200
    assert admin.get(f"{base}/versions/1").status_code == 200
    assert admin.get(f"{base}/diff?a=1&b=2").status_code == 200


def test_unchanged_save_does_not_create_version(db) -> None:
    book = _book(db)
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="章", raw="第一行\n第二行\n"
    )
    db.commit()
    # 只多了 CRLF，属于同一内容
    sections_service.replace_content(db, section, raw="第一行\r\n第二行\r\n")
    db.commit()
    assert section.current_version_no == 1
    assert len(sections_service.list_versions(db, section)) == 1

    # 真改了正文才有新版本
    sections_service.replace_content(db, section, raw="第一行\n改过了\n")
    db.commit()
    assert section.current_version_no == 2


def test_section_delete_and_restore(db) -> None:
    book = _book(db)
    chapter = _multi_chapter(db, book)
    section = sections_service.ordered_sections(db, chapter.id)[1]
    sections_service.delete_section(db, section)
    db.commit()
    assert [item.slug for item in sections_service.ordered_sections(db, chapter.id)] == [
        "overview",
        "examples",
    ]
    sections_service.restore_section(db, section)
    db.commit()
    assert [item.slug for item in sections_service.ordered_sections(db, chapter.id)] == [
        "overview",
        "architecture",
        "examples",
    ]


def test_section_format_must_match_book(db, client) -> None:
    """整本单一格式：Markdown 书里建 HTML 节被拒绝，页面只有一种格式。"""
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="统一", slug_raw="single", status="published")
    db.commit()
    sections_service.create_section(db, chapter, title="Markdown 节", raw="# md", slug_raw="md")
    db.commit()
    with pytest.raises(ValidationFailed):
        sections_service.create_section(
            db, chapter, title="HTML 节", raw="<h1>html</h1>", fmt="html", slug_raw="html"
        )
    db.rollback()
    sections_service.create_section(db, chapter, title="第二节", raw="# md 2", slug_raw="md2")
    db.commit()
    assert {item.format for item in sections_service.ordered_sections(db, chapter.id)} == {"markdown"}
    assert client.get(f"/b/{book.slug}/{chapter.slug}/md").status_code == 200
    assert client.get(f"/b/{book.slug}/{chapter.slug}/md/raw").status_code == 404


@pytest.mark.parametrize("status", ["draft", "published"])
def test_search_index_follows_section_lifecycle(db, status) -> None:
    from app.services.search import search as run_search

    book = _book(db)
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="部署", raw="知识库部署流程", status=status
    )
    db.commit()
    assert run_search(db, query="知识库")[1] == (1 if status == "published" else 0)

    sections_service.delete_section(db, section)
    db.commit()
    assert run_search(db, query="知识库")[1] == 0
