"""内置《AI Agent 接入使用指南》：创建、幂等、不可删除与对外暴露。"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.errors import ValidationFailed
from app.main import create_app
from app.services import books as books_service
from app.services import builtin, guide
from app.services import chapters as chapters_service
from app.services import sections as sections_service

from .conftest import ADMIN_PASSWORD, ADMIN_USER, make_settings, run_migrations

EXPECTED_CHAPTERS = ["start", "structure", "http-api", "mcp", "skill", "faq"]


def _sections_of(db, chapter) -> list:
    return sections_service.ordered_sections(db, chapter.id)


# ------------------------------------------------------------------ 服务层


def test_ensure_guide_builds_the_whole_book(db) -> None:
    book = guide.ensure_guide(db)
    db.commit()
    assert book is not None
    assert book.slug == builtin.BUILTIN_SLUG
    assert book.title == builtin.BUILTIN_TITLE
    assert book.is_builtin is True
    assert book.pinned is True
    assert book.format == "markdown"

    chapters = chapters_service.ordered_chapters(db, book.id)
    assert [chapter.slug for chapter in chapters] == EXPECTED_CHAPTERS
    assert all(chapter.status == "published" for chapter in chapters)
    assert all(_sections_of(db, chapter) for chapter in chapters)

    # 内容真的覆盖了三件事：HTTP API、MCP、SKILL
    bodies = {
        chapter.slug: "\n".join(section.content_safe for section in _sections_of(db, chapter))
        for chapter in chapters
    }
    assert "/api/v1/admin/books" in bodies["http-api"]
    assert "FastMCP" in bodies["mcp"] and "mcpServers" in bodies["mcp"]
    assert "SKILL.md" in bodies["skill"]
    assert "409" in bodies["faq"]
    # 内容组织与上传格式要求（同一章的两节）
    assert "分组" in bodies["structure"] and "chapters" in bodies["structure"]
    assert "/api/v1/books" in bodies["structure"]
    assert "GB18030" in bodies["structure"]
    assert ".md" in bodies["structure"] and ".html" in bodies["structure"]
    assert "MAX_UPLOAD_FILES" in bodies["structure"]
    assert "MEDIA_ALLOWED_TYPES" in bodies["structure"]


def test_ensure_guide_is_idempotent(db) -> None:
    guide.ensure_guide(db)
    db.commit()
    chapters = chapters_service.ordered_chapters(db, books_service.get_book(db, builtin.BUILTIN_SLUG).id)
    section_count = sum(len(_sections_of(db, chapter)) for chapter in chapters)

    guide.ensure_guide(db)
    db.commit()
    again = chapters_service.ordered_chapters(db, books_service.get_book(db, builtin.BUILTIN_SLUG).id)
    assert [chapter.slug for chapter in again] == EXPECTED_CHAPTERS
    assert sum(len(_sections_of(db, chapter)) for chapter in again) == section_count


def test_ensure_guide_fills_missing_sections_without_overwriting(db) -> None:
    book = guide.ensure_guide(db)
    db.commit()
    mcp = next(chapter for chapter in chapters_service.ordered_chapters(db, book.id) if chapter.slug == "mcp")
    sections = _sections_of(db, mcp)
    edited, removed = sections[0], sections[-1]
    sections_service.replace_content(db, edited, raw="# 我自己的版本\n\n改过的正文。")
    db.delete(removed)
    db.commit()

    guide.ensure_guide(db)
    db.commit()
    restored = {section.slug: section for section in _sections_of(db, mcp)}
    assert "我自己的版本" in restored[edited.slug].content_safe  # 用户编辑不被覆盖
    assert removed.slug in restored  # 缺的那一节被补回来


def test_upgrade_inserts_new_chapter_in_spec_order(db) -> None:
    """老实例缺「内容怎么组织」这一章时，补进来要落在第 2 位而不是末尾。"""
    book = guide.ensure_guide(db)
    db.commit()
    structure = next(
        chapter for chapter in chapters_service.ordered_chapters(db, book.id) if chapter.slug == "structure"
    )
    for section in list(structure.sections):
        db.delete(section)
    db.delete(structure)
    db.commit()
    assert "structure" not in [
        chapter.slug for chapter in chapters_service.ordered_chapters(db, book.id)
    ]

    guide.ensure_guide(db)
    db.commit()
    chapters = chapters_service.ordered_chapters(db, book.id)
    assert [chapter.slug for chapter in chapters] == EXPECTED_CHAPTERS
    restored = next(chapter for chapter in chapters if chapter.slug == "structure")
    assert len(_sections_of(db, restored)) == 2


def test_builtin_book_cannot_be_deleted(db) -> None:
    book = guide.ensure_guide(db)
    db.commit()
    with pytest.raises(ValidationFailed):
        books_service.soft_delete_book(db, book)
    db.rollback()
    assert books_service.get_book(db, builtin.BUILTIN_SLUG) is not None


def test_builtin_chapters_and_sections_cannot_be_deleted(db) -> None:
    book = guide.ensure_guide(db)
    db.commit()
    chapter = chapters_service.ordered_chapters(db, book.id)[0]
    with pytest.raises(ValidationFailed):
        chapters_service.soft_delete_chapter(db, chapter)
    db.rollback()

    chapter = chapters_service.ordered_chapters(db, book.id)[0]
    section = _sections_of(db, chapter)[0]
    with pytest.raises(ValidationFailed):
        sections_service.delete_section(db, section)
    db.rollback()

    assert len(chapters_service.ordered_chapters(db, book.id)) == len(EXPECTED_CHAPTERS)


def test_builtin_identity_is_locked_but_content_is_editable(db) -> None:
    book = guide.ensure_guide(db)
    db.commit()
    with pytest.raises(ValidationFailed):
        books_service.update_book(db, book, slug_raw="another-guide")
    db.rollback()
    with pytest.raises(ValidationFailed):
        books_service.update_book(db, book, fmt="html")
    db.rollback()

    book = books_service.get_book(db, builtin.BUILTIN_SLUG)
    updated = books_service.update_book(
        db, book, slug_raw=builtin.BUILTIN_SLUG, title="AI Agent 接入使用指南（已校对）", summary="改过简介"
    )
    db.commit()
    assert updated.title == "AI Agent 接入使用指南（已校对）"
    assert updated.slug == builtin.BUILTIN_SLUG


def test_ensure_guide_does_not_hijack_a_user_book_with_same_slug(db) -> None:
    books_service.create_book(db, title="用户自己写的指南", slug_raw=builtin.BUILTIN_SLUG)
    db.commit()
    assert guide.ensure_guide(db) is None
    db.rollback()
    book = books_service.get_book(db, builtin.BUILTIN_SLUG)
    assert book.is_builtin is False
    assert chapters_service.ordered_chapters(db, book.id) == []


# ------------------------------------------------------------------ 启动与 API


@pytest.fixture()
def guided(tmp_path):
    settings = make_settings(tmp_path, builtin_guide=True, admin_api_token="bh_guide_token_0123456789")
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, app


def test_startup_creates_guide_and_site_advertises_it(guided) -> None:
    client, _app = guided
    site = client.get("/api/v1/site").json()
    assert site["guide"]["slug"] == builtin.BUILTIN_SLUG
    assert site["guide"]["url"].endswith(f"/b/{builtin.BUILTIN_SLUG}")

    listing = client.get("/api/v1/books").json()
    entry = next(item for item in listing["items"] if item["slug"] == builtin.BUILTIN_SLUG)
    assert entry["is_builtin"] is True


def test_guide_content_is_readable_through_both_apis(guided) -> None:
    client, _app = guided
    public = client.get(
        f"/api/v1/books/{builtin.BUILTIN_SLUG}/chapters/mcp?section=server&format=raw"
    )
    assert public.status_code == 200
    assert "FastMCP" in public.text

    admin = client.get(
        f"/api/v1/admin/books/{builtin.BUILTIN_SLUG}/chapters/mcp/sections/server",
        headers={"Authorization": "Bearer bh_guide_token_0123456789"},
    )
    assert admin.status_code == 200
    assert "FastMCP" in admin.json()["content_raw"]


def test_api_cannot_delete_the_guide(guided) -> None:
    client, _app = guided
    headers = {"Authorization": "Bearer bh_guide_token_0123456789"}
    response = client.post(
        f"/api/v1/admin/books/{builtin.BUILTIN_SLUG}/delete?confirm=true", headers=headers
    )
    assert response.status_code == 400
    assert "内置指南" in response.json()["error"]["message"]

    chapter = client.get(f"/api/v1/admin/books/{builtin.BUILTIN_SLUG}/chapters", headers=headers).json()["items"][0]
    blocked = client.post(
        f"/api/v1/admin/books/{builtin.BUILTIN_SLUG}/chapters/{chapter['slug']}/delete?confirm=true",
        headers=headers,
    )
    assert blocked.status_code == 400


def test_api_batch_delete_and_patch_cannot_remove_the_guide(guided) -> None:
    """批量删章同样被拦；PATCH 也不能把 is_builtin 清掉再删。"""
    client, _app = guided
    headers = {"Authorization": "Bearer bh_guide_token_0123456789"}
    chapter_ids = [
        item["id"]
        for item in client.get(
            f"/api/v1/admin/books/{builtin.BUILTIN_SLUG}/chapters", headers=headers
        ).json()["items"]
    ]
    batch = client.post(
        f"/api/v1/admin/books/{builtin.BUILTIN_SLUG}/chapters/batch?confirm=true",
        json={"action": "delete", "chapter_ids": chapter_ids},
        headers=headers,
    )
    assert batch.status_code == 200
    assert batch.json()["ok_count"] == 0
    assert all(not item["ok"] for item in batch.json()["results"])

    patched = client.patch(
        f"/api/v1/admin/books/{builtin.BUILTIN_SLUG}",
        json={"is_builtin": False, "title": "AI Agent 接入使用指南"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["is_builtin"] is True

    trash = client.get("/api/v1/admin/trash", headers=headers).json()
    assert all(item["slug"] != builtin.BUILTIN_SLUG for item in trash["books"])


def test_web_form_cannot_delete_the_guide(guided) -> None:
    """网页端的删除表单即使被手工构造，也只是回列表页带提示，书与内容都还在。"""
    client, _app = guided
    login = client.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    book = client.get(
        f"/api/v1/admin/books/{builtin.BUILTIN_SLUG}",
        headers={"Authorization": "Bearer bh_guide_token_0123456789"},
    ).json()
    page = client.get(f"/admin/books/{book['id']}").text
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match is not None

    blocked = client.post(
        f"/admin/books/{book['id']}/delete",
        data={"csrf_token": match.group(1)},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert "error=" in blocked.headers["location"]
    assert "内置指南" in client.get(blocked.headers["location"]).text

    after = client.get(
        f"/api/v1/admin/books/{builtin.BUILTIN_SLUG}",
        headers={"Authorization": "Bearer bh_guide_token_0123456789"},
    ).json()
    assert after["deleted"] is False
    assert after["chapter_count"] == len(EXPECTED_CHAPTERS)


def test_admin_pages_mark_the_guide_as_builtin(guided) -> None:
    client, _app = guided
    login = client.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    dashboard = client.get("/admin").text
    assert "内置指南" in dashboard
    assert "内置 · 不可删除" in dashboard

    book = client.get(f"/api/v1/admin/books/{builtin.BUILTIN_SLUG}", headers={
        "Authorization": "Bearer bh_guide_token_0123456789"
    }).json()
    detail = client.get(f"/admin/books/{book['id']}").text
    assert "内置指南 · 不可删除" in detail
    assert f"/admin/books/{book['id']}/delete" not in detail

    form = client.get(f"/admin/books/{book['id']}/edit").text
    assert "这是<strong>内置指南</strong>" in form

def test_migration_renames_untouched_builtin_title(tmp_path) -> None:
    """0018：只改仍是旧默认标题的内置书；用户改过的标题与他人书籍不动。"""
    import os

    from alembic.config import Config as AlembicConfig
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from alembic import command
    from app.models import Book

    from .conftest import ROOT

    settings = make_settings(tmp_path)
    os.environ["DATABASE_URL"] = settings.database_url
    config = AlembicConfig(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(config, "0017_book_builtin")

    engine = create_engine(settings.database_url)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        untouched = books_service.create_book(
            session, title="AI Agent 使用指南", slug_raw="ai-agent-guide"
        )
        untouched.is_builtin = True
        edited = books_service.create_book(
            session, title="AI Agent 使用指南", slug_raw="guide-copy"
        )
        edited.is_builtin = True
        edited.title = "我自己起的名字"
        user_book = books_service.create_book(
            session, title="AI Agent 使用指南", slug_raw="user-book"
        )
        session.commit()
        ids = (untouched.id, edited.id, user_book.id)
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(settings.database_url)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        titles = {book_id: session.get(Book, book_id).title for book_id in ids}
    engine.dispose()

    assert titles[ids[0]] == builtin.BUILTIN_TITLE == "AI Agent 接入使用指南"
    assert titles[ids[1]] == "我自己起的名字"
    assert titles[ids[2]] == "AI Agent 使用指南"
