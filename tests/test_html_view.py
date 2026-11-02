"""HTML 原始文档通道：/raw 端点、CSP 沙箱、Book 阅读方式与入口。"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.errors import ValidationFailed
from app.models import SectionViewDaily
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import sections as sections_service

SAMPLE_HTML = """<!doctype html>
<html><head><style>.doc-nav a{color:#c00}</style></head>
<body>
  <nav class="doc-nav"><a href="#s1">第一节</a></nav>
  <h2 id="s1">第一节</h2>
  <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==" alt="点">
  <script>document.title = "doc";</script>
</body></html>"""


def _html_book(db, *, title="原始文档", html_view=None, slug="doc"):
    book = books_service.create_book(
        db, title=title, slug_raw=slug, fmt="html", html_view=html_view
    )
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="整页文档", raw=SAMPLE_HTML, slug_raw="page", status="published"
    )
    db.commit()
    return book, chapter, section


def _views(app) -> int:
    with app.state.sessionmaker() as session:
        return int(session.execute(select(func.sum(SectionViewDaily.views))).scalar_one() or 0)


# ---------------------------------------------------------------- /raw 端点


def test_raw_returns_untouched_document_with_sandbox_csp(client, db) -> None:
    book, chapter, section = _html_book(db)
    response = client.get(f"/b/{book.slug}/{chapter.slug}/{section.slug}/raw")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    # 原样输出：样式、脚本、base64 图片都还在
    assert "<style>" in body
    assert "<script>" in body
    assert "data:image/png;base64" in body
    assert ".doc-nav a" in body

    csp = response.headers["content-security-policy"]
    assert "sandbox" in csp
    assert "allow-scripts" in csp
    assert "allow-same-origin" not in csp
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "noindex" in response.headers["x-robots-tag"]
    # 站点自己的阅读页 CSP 不应覆盖这份响应
    assert "script-src 'self'" not in csp


def _draft_and_markdown(db):
    book = books_service.create_book(db, title="草稿书", slug_raw="draftbook", fmt="html")
    draft_chapter, draft_section = chapters_service.create_chapter_with_section(
        db, book, title="草稿页", raw=SAMPLE_HTML, slug_raw="hidden", status="draft"
    )
    md_book = books_service.create_book(db, title="Markdown 书", slug_raw="mdbook")
    md_chapter, md_section = chapters_service.create_chapter_with_section(
        db, md_book, title="章节", raw="# 标题\n\n正文", slug_raw="md", status="published"
    )
    db.commit()
    return {
        "book": book,
        "chapter": draft_chapter,
        "section": draft_section,
        "md_book": md_book,
        "md_chapter": md_chapter,
        "md_section": md_section,
    }


def test_raw_is_404_for_draft_and_for_markdown(client, db) -> None:
    seeded = _draft_and_markdown(db)
    book, chapter, section = seeded["book"], seeded["chapter"], seeded["section"]
    assert client.get(f"/b/{book.slug}/{chapter.slug}/{section.slug}/raw").status_code == 404
    md_book, md_chapter, md_section = (
        seeded["md_book"],
        seeded["md_chapter"],
        seeded["md_section"],
    )
    assert (
        client.get(f"/b/{md_book.slug}/{md_chapter.slug}/{md_section.slug}/raw").status_code
        == 404
    )


def test_raw_lets_logged_in_user_preview_draft(admin, db) -> None:
    seeded = _draft_and_markdown(db)
    book, chapter, section = seeded["book"], seeded["chapter"], seeded["section"]
    # 登录用户可以预览草稿原文
    assert admin.get(f"/b/{book.slug}/{chapter.slug}/{section.slug}/raw").status_code == 200


def test_raw_access_counts_book_heat(client, db, app) -> None:
    book, chapter, section = _html_book(db)
    url = f"/b/{book.slug}/{chapter.slug}/{section.slug}/raw"
    assert _views(app) == 0
    assert client.get(url).status_code == 200
    assert _views(app) == 1
    # 同一访客短时间重复打开不重复计
    assert client.get(url).status_code == 200
    assert _views(app) == 1


# ---------------------------------------------------------------- 阅读方式


def test_markdown_book_always_inline(db) -> None:
    plain = books_service.create_book(db, title="普通 Markdown")
    assert plain.html_view == "inline"
    book = books_service.create_book(db, title="Markdown 书", html_view="document")
    assert book.html_view == "inline"
    with pytest.raises(ValidationFailed):
        books_service.create_book(db, title="坏值", fmt="html", html_view="iframe")


def test_html_book_defaults_to_document(client, db) -> None:
    """HTML Book 一律默认按原始文档打开（存量由迁移回填，新书由服务层默认）。"""
    book = books_service.create_book(db, title="默认原始文档", slug_raw="rawdefault", fmt="html")
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="整页文档", raw=SAMPLE_HTML, slug_raw="page", status="published"
    )
    db.commit()
    assert book.html_view == "document"

    html = client.get(f"/b/{book.slug}").text
    assert f"/b/{book.slug}/{chapter.slug}/{section.slug}/raw" in html
    assert 'target="_blank"' in html
    chapter_page = client.get(f"/b/{book.slug}/{chapter.slug}").text
    assert "原始文档" in chapter_page
    # 站内章节页仍然可用（净化版兜底）
    assert client.get(f"/b/{book.slug}/{chapter.slug}").status_code == 200


def test_switching_to_inline_returns_to_site_pages(client, db) -> None:
    book, chapter, section = _html_book(db, html_view="document")

    books_service.update_book(db, book, html_view="inline")
    db.commit()
    assert book.html_view == "inline"

    html = client.get(f"/b/{book.slug}").text
    assert f"/b/{book.slug}/{chapter.slug}/{section.slug}/raw" not in html
    chapter_page = client.get(f"/b/{book.slug}/{chapter.slug}").text
    assert "站内安全渲染版" in chapter_page


def test_admin_form_persists_reading_mode(admin, db, csrf) -> None:
    token = csrf(admin)
    response = admin.post(
        "/admin/books/new",
        data={
            "title": "整页 HTML",
            "slug": "",
            "group": "default",
            "summary": "",
            "icon": "",
            "format": "html",
            "html_view": "document",
            "visibility": "public",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    book = db.execute(
        select(books_service.Book).where(books_service.Book.title == "整页 HTML")
    ).scalar_one()
    assert book.html_view == "document"
    assert "原始版式（新标签页）" in admin.get(f"/admin/books/{book.id}").text

    # 站内页面表单里能看到两个选项
    form = admin.get(f"/admin/books/{book.id}/edit").text
    assert 'name="html_view"' in form
    assert 'value="document"' in form


def test_api_exposes_html_view(client, db) -> None:
    book, _chapter, _section = _html_book(db, html_view="document")
    payload = client.get("/api/v1/books").json()["items"][0]
    assert payload["html_view"] == "document"
    detail = client.get(f"/api/v1/books/{book.slug}").json()
    assert detail["html_view"] == "document"


def test_html_book_allows_only_html_sections(client, db) -> None:
    """整本单一格式：HTML 书里只能有 HTML 节，Markdown 节被拒绝。"""
    book = books_service.create_book(db, title="HTML 书", slug_raw="html-only", fmt="html")
    chapter = chapters_service.create_chapter(db, book, title="页面章")
    db.commit()
    sections_service.create_section(db, chapter, title="页面", raw=SAMPLE_HTML, slug_raw="page")
    db.commit()
    with pytest.raises(ValidationFailed) as excinfo:
        sections_service.create_section(db, chapter, title="笔记", raw="# md", fmt="markdown", slug_raw="note")
    assert "HTML" in str(excinfo.value)
    db.rollback()
    sections_service.create_section(db, chapter, title="附录", raw="<h1>附录</h1>", slug_raw="appendix")
    chapters_service.set_status(db, chapter, "published")
    db.commit()

    index_page = client.get(f"/b/{book.slug}/{chapter.slug}")
    assert index_page.status_code == 200
    html = index_page.text
    assert f"/b/{book.slug}/{chapter.slug}/page" in html
    assert f"/b/{book.slug}/{chapter.slug}/appendix" in html
    assert {item.format for item in sections_service.ordered_sections(db, chapter.id)} == {"html"}
    # HTML 节有原始文档通道
    assert client.get(f"/b/{book.slug}/{chapter.slug}/page/raw").status_code == 200
