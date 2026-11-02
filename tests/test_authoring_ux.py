"""编写体验：幂等保存、保存反馈、分享地址与 OG 元数据。"""

from __future__ import annotations

import pytest

from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import media as media_service
from app.services import sections as sections_service

from .conftest import csrf_token, make_settings, run_migrations

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
AUTH = {"Authorization": "Bearer bh_ux_token_0123456789"}


def _book(db, title="体验手册"):
    book = books_service.create_book(db, title=title, fmt="markdown")
    db.commit()
    return book


def _chapter(db, book, title="第一章", raw="# 正文"):
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title=title, raw=raw, section_slug="main"
    )
    db.commit()
    return chapter, section


# ------------------------------------------------------------------ 幂等保存


def test_replace_without_changes_keeps_version(db) -> None:
    book = _book(db)
    _chapter_row, section = _chapter(db, book)
    before = section.current_version_no

    for _ in range(2):
        sections_service.replace_content(db, section, title="第一章", raw="# 正文")
        db.commit()

    assert section.current_version_no == before
    assert len(sections_service.list_versions(db, section)) == 1


def test_replace_with_new_content_bumps_version(db) -> None:
    book = _book(db)
    _chapter_row, section = _chapter(db, book)
    sections_service.replace_content(db, section, raw="# 新正文")
    db.commit()
    assert section.current_version_no == 2
    assert len(sections_service.list_versions(db, section)) == 2


def test_title_only_change_bumps_version(db) -> None:
    book = _book(db)
    _chapter_row, section = _chapter(db, book)
    sections_service.replace_content(db, section, title="改了标题")
    db.commit()
    assert section.current_version_no == 2


def test_slug_change_bumps_version(db) -> None:
    book = _book(db)
    _chapter_row, section = _chapter(db, book)
    sections_service.replace_content(db, section, slug_raw="renamed-slug")
    db.commit()
    assert section.slug == "renamed-slug"
    assert section.current_version_no == 2


def test_crlf_submission_counts_as_unchanged(db) -> None:
    """浏览器提交 textarea 会把换行变成 CRLF，不能因此判定成"改了内容"。"""
    book = _book(db)
    _chapter_row, section = _chapter(db, book, raw="第一行\n第二行\n")
    sections_service.replace_content(db, section, raw="第一行\r\n第二行\r\n")
    db.commit()
    assert section.current_version_no == 1
    assert len(sections_service.list_versions(db, section)) == 1


# ------------------------------------------------------------------ 保存反馈


def test_create_chapter_shows_notice(admin, db) -> None:
    book = _book(db)
    token = csrf_token(admin, f"/admin/books/{book.id}/chapters/new")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/new",
        data={"csrf_token": token, "title": "新章", "content": "# hi", "status": "draft"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "notice=chapter-created" in response.headers["location"]
    page = admin.get(response.headers["location"]).text
    assert "章已创建" in page
    assert "v1" in page


def test_unchanged_save_shows_warning_notice(admin, db) -> None:
    book = _book(db)
    chapter, section = _chapter(db, book)
    token = csrf_token(
        admin, f"/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}"
    )
    response = admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}/replace",
        data={
            "csrf_token": token,
            "title": section.title,
            "content": section.content_raw,
            "base_version": str(section.current_version_no),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "notice=section-unchanged" in response.headers["location"]
    page = admin.get(response.headers["location"]).text
    assert "未生成新版本" in page


def test_changed_save_shows_version_notice(admin, db) -> None:
    book = _book(db)
    chapter, section = _chapter(db, book)
    token = csrf_token(
        admin, f"/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}"
    )
    response = admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}/replace",
        data={
            "csrf_token": token,
            "title": section.title,
            "content": "# 改过的内容",
            "base_version": str(section.current_version_no),
        },
        follow_redirects=False,
    )
    assert "notice=section-saved" in response.headers["location"]
    assert "已保存为 v2" in admin.get(response.headers["location"]).text


def test_edit_form_previews_next_version(admin, db) -> None:
    book = _book(db)
    chapter, section = _chapter(db, book)
    sections_service.replace_content(db, section, raw="# v2 内容")
    db.commit()
    page = admin.get(
        f"/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}"
    ).text
    assert "保存为 v3" in page


def test_book_create_and_edit_notices(admin, db) -> None:
    token = csrf_token(admin, "/admin/books/new")
    created = admin.post(
        "/admin/books/new",
        data={
            "csrf_token": token,
            "title": "提示手册",
            "group": "default",
            "summary": "",
            "icon": "",
            "format": "markdown",
            "visibility": "public",
        },
        follow_redirects=False,
    )
    assert "notice=book-created" in created.headers["location"]
    page = admin.get(created.headers["location"]).text
    assert "Book 已创建" in page


# ------------------------------------------------------------------ 分享地址


def test_share_url_is_absolute(client, db) -> None:
    book = _book(db)
    chapter, section = _chapter(db, book, raw="# x")
    chapters_service.set_status(db, chapter, "published")
    db.commit()

    book_page = client.get(f"/b/{book.slug}").text
    assert f'og:url" content="http://testserver/b/{book.slug}"' in book_page
    assert f'data-copy="http://testserver/b/{book.slug}"' in book_page

    # 单节章：章页直接渲染这一节，规范地址仍是章地址（分享出去不会有两份重复内容）
    chapter_page = client.get(f"/b/{book.slug}/{chapter.slug}").text
    chapter_url = f"http://testserver/b/{book.slug}/{chapter.slug}"
    assert f'og:url" content="{chapter_url}"' in chapter_page
    assert f'data-copy="{chapter_url}"' in chapter_page
    assert "复制链接" in chapter_page
    # 章与节的标题相同时只显示一次，不再出现「第一章 · 第一章」
    assert 'og:title" content="第一章"' in chapter_page
    section_page = client.get(f"/b/{book.slug}/{chapter.slug}/{section.slug}").text
    share = f"http://testserver/b/{book.slug}/{chapter.slug}/{section.slug}"
    assert f'og:url" content="{share}"' in section_page


def test_share_url_respects_root_path(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = make_settings(tmp_path, root_path="/kb")
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.sessionmaker() as session:
            book = books_service.create_book(session, title="前缀手册", fmt="markdown")
            session.commit()
            slug = book.slug
        page = client.get(f"/b/{slug}").text
        assert f'data-copy="http://testserver/kb/b/{slug}"' in page


def test_og_image_uses_cover(client, db, settings) -> None:
    book = _book(db)
    asset = media_service.save_media(
        db, book=book, filename="cover.png", data=PNG, settings=settings, actor=None
    )
    books_service.set_cover(db, book, asset.id)
    db.commit()
    page = client.get(f"/b/{book.slug}").text
    assert 'property="og:image" content="http://testserver/media/' in page


def test_book_page_has_copy_button(client, db) -> None:
    book = _book(db)
    db.commit()
    page = client.get(f"/b/{book.slug}").text
    assert "复制链接" in page
    assert 'data-copy="http://testserver/b/' in page


# ------------------------------------------------------------------ API 幂等


@pytest.fixture()
def api(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = make_settings(tmp_path, admin_api_token=AUTH["Authorization"].split()[-1])
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def test_api_save_is_idempotent(api) -> None:
    client = api
    book = client.post(
        "/api/v1/admin/books",
        json={"title": "API 幂等", "format": "markdown", "group": "default"},
        headers=AUTH,
    ).json()
    chapter = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "第一章", "content": "# 正文"},
        headers=AUTH,
    ).json()
    section = chapter["sections"][0]

    first = client.patch(
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter['slug']}/sections/{section['slug']}",
        json={"content": "# 正文"},
        headers=AUTH,
    )
    assert first.status_code == 200
    assert first.json()["version"] == 1

    second = client.patch(
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter['slug']}/sections/{section['slug']}",
        json={"content": "# 改过"},
        headers=AUTH,
    )
    assert second.json()["version"] == 2
