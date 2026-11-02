"""Web 端：访客阅读、管理端 CRUD、模板与安全头。"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.main import create_app
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import sections as sections_service
from app.services.users import create_user

from .conftest import ADMIN_PASSWORD, ADMIN_USER, csrf_token, make_settings, run_migrations


def _seed(db):
    book = books_service.create_book(db, title="研发手册", summary="入职文档")
    chapter, section = chapters_service.create_chapter_with_section(
        db,
        book,
        title="欢迎",
        raw="# 欢迎\n\n## 目标\n\n这里是正文。",
        slug_raw="welcome",
        status="published",
        section_slug="main",
    )
    draft = chapters_service.create_chapter_with_section(
        db, book, title="草稿", raw="草稿正文", slug_raw="draft", section_slug="main"
    )[0]
    hidden = books_service.create_book(db, title="隐藏手册", visibility="unlisted")
    chapters_service.create_chapter_with_section(
        db, hidden, title="内部", raw="内部内容", slug_raw="secret", status="published"
    )
    db.commit()
    return {
        "book": book,
        "chapter": chapter,
        "section": section,
        "draft": draft,
        "hidden": hidden,
    }


def test_home_lists_public_books_only(client, db) -> None:
    _seed(db)
    response = client.get("/")
    assert response.status_code == 200
    assert "研发手册" in response.text
    assert "隐藏手册" not in response.text


def test_book_page_lists_published_chapters(client, db) -> None:
    seeded = _seed(db)
    response = client.get(f"/b/{seeded['book'].slug}")
    assert response.status_code == 200
    assert "欢迎" in response.text
    assert "草稿" not in response.text


def test_unlisted_book_direct_link_works(client, db) -> None:
    seeded = _seed(db)
    response = client.get(f"/b/{seeded['hidden'].slug}")
    assert response.status_code == 200
    assert "内部" in response.text
    assert "未列出" in response.text


def test_chapter_page_renders_content_and_toc(client, db) -> None:
    seeded = _seed(db)
    response = client.get(f"/b/{seeded['book'].slug}/welcome")
    assert response.status_code == 200
    assert "这里是正文" in response.text
    assert 'id="目标"' in response.text
    assert "本页目录" in response.text


def test_draft_chapter_404(client, db) -> None:
    seeded = _seed(db)
    response = client.get(f"/b/{seeded['book'].slug}/draft")
    assert response.status_code == 404
    assert "草稿正文" not in response.text


def test_unknown_book_404(client) -> None:
    assert client.get("/b/nope").status_code == 404


def test_security_headers_on_html(client, db) -> None:
    _seed(db)
    response = client.get("/")
    assert "content-security-policy" in {key.lower() for key in response.headers}
    policy = response.headers["content-security-policy"]
    assert "script-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert response.headers["x-content-type-options"] == "nosniff"


def test_search_page(client, db) -> None:
    _seed(db)
    response = client.get("/search?q=正文")
    assert response.status_code == 200
    assert "欢迎" in response.text
    assert "<mark>" in response.text


def test_search_single_char_falls_back(client, db) -> None:
    _seed(db)
    response = client.get("/search?q=欢")
    assert response.status_code == 200
    assert "欢迎" in response.text


def test_admin_requires_login(client) -> None:
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert "/admin/login" in response.headers["location"]


def test_login_wrong_password(client) -> None:
    response = client.post(
        "/admin/login", data={"username": ADMIN_USER, "password": "wrong"}, follow_redirects=False
    )
    assert response.status_code == 401
    assert "用户名或密码错误" in response.text


def test_admin_pages_render(admin) -> None:
    for path in ("/admin", "/admin/books/new", "/admin/trash", "/admin/users", "/admin/settings", "/admin/audit"):
        response = admin.get(path)
        assert response.status_code == 200, (path, response.text[:400])


def test_create_book_via_form(admin, csrf) -> None:
    token = csrf(admin)
    response = admin.post(
        "/admin/books/new",
        data={"title": "新手册", "slug": "", "group": "default", "summary": "说明", "icon": "", "format": "markdown", "visibility": "public", "sort_order": "", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    listing = admin.get("/admin")
    assert "新手册" in listing.text


def test_create_book_empty_title_shows_error(admin, csrf) -> None:
    token = csrf(admin)
    response = admin.post(
        "/admin/books/new",
        data={"title": "  ", "slug": "", "group": "default", "summary": "", "icon": "", "format": "markdown", "visibility": "public", "sort_order": "", "csrf_token": token},
    )
    assert response.status_code == 400
    assert "标题必填" in response.text


def test_post_without_csrf_rejected(admin) -> None:
    response = admin.post("/admin/books/new", data={"title": "X"})
    assert response.status_code == 403


def test_upload_gb18030_chapter(admin, csrf, db) -> None:
    book = books_service.create_book(db, title="编码手册")
    db.commit()
    token = csrf(admin, f"/admin/books/{book.id}/chapters/new")
    payload = "# 部署指南\n\n中文内容".encode("gb18030")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/new",
        data={"title": "", "slug": "", "format": "markdown", "status": "draft", "content": "", "encoding": "", "csrf_token": token},
        files={"upload": ("部署指南.md", payload, "text/markdown")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    detail = admin.get(f"/admin/books/{book.id}")
    assert "部署指南" in detail.text


def test_upload_unsupported_extension(admin, csrf, db) -> None:
    book = books_service.create_book(db, title="编码手册")
    db.commit()
    token = csrf(admin, f"/admin/books/{book.id}/chapters/new")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/new",
        data={"title": "x", "slug": "", "format": "markdown", "status": "draft", "content": "", "encoding": "", "csrf_token": token},
        files={"upload": ("report.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 400
    assert "不支持" in response.text


def test_replace_section_and_view_versions(admin, csrf, db) -> None:
    seeded = _seed(db)
    chapter = seeded["chapter"]
    section = seeded["section"]
    token = csrf(
        admin, f"/admin/books/{seeded['book'].id}/chapters/{chapter.id}/sections/{section.id}"
    )
    response = admin.post(
        f"/admin/books/{seeded['book'].id}/chapters/{chapter.id}/sections/{section.id}/replace",
        data={
            "title": "欢迎（改）",
            "slug": section.slug,
            "format": "markdown",
            "content": "# 欢迎（改）\n\n新正文",
            "encoding": "",
            "base_version": str(section.current_version_no),
            "note": "改标题",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    versions = admin.get(
        f"/admin/books/{seeded['book'].id}/chapters/{chapter.id}/sections/{section.id}/versions"
    )
    assert versions.status_code == 200
    assert "v2" in versions.text or "2" in versions.text


def test_version_detail_and_diff_pages(admin, csrf, db) -> None:
    seeded = _seed(db)
    book = seeded["book"]
    chapter = seeded["chapter"]
    section = seeded["section"]
    sections_service.replace_content(db, section, raw="# 欢迎\n\n第二版正文")
    sections_service.replace_content(db, section, raw="# 欢迎\n\n第三版正文")
    db.commit()
    base = f"/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}"
    detail = admin.get(f"{base}/versions/2")
    assert detail.status_code == 200
    assert "第二版正文" in detail.text
    diff = admin.get(f"{base}/diff?a=1&b=2")
    assert diff.status_code == 200
    assert "diff-row" in diff.text
    rollback_token = csrf(admin, f"{base}/versions")
    rollback = admin.post(
        f"{base}/rollback/1",
        data={"csrf_token": rollback_token},
        follow_redirects=False,
    )
    assert rollback.status_code == 303
    db.refresh(section)
    assert section.current_version_no == 4


def test_replace_with_stale_base_version_conflict(admin, csrf, db) -> None:
    seeded = _seed(db)
    chapter = seeded["chapter"]
    section = seeded["section"]
    token = csrf(
        admin, f"/admin/books/{seeded['book'].id}/chapters/{chapter.id}/sections/{section.id}"
    )
    response = admin.post(
        f"/admin/books/{seeded['book'].id}/chapters/{chapter.id}/sections/{section.id}/replace",
        data={
            "title": section.title,
            "slug": section.slug,
            "format": "markdown",
            "content": "x",
            "encoding": "",
            "base_version": "99",
            "note": "",
            "csrf_token": token,
        },
    )
    assert response.status_code == 409 or response.status_code == 400


def test_publish_and_delete_flow(admin, csrf, db) -> None:
    seeded = _seed(db)
    book = seeded["book"]
    chapter = seeded["chapter"]
    token = csrf(admin, f"/admin/books/{book.id}")
    admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/status",
        data={"status": "draft", "csrf_token": token},
        follow_redirects=False,
    )
    assert admin.get(f"/b/{book.slug}/welcome").status_code == 404
    admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/status",
        data={"status": "published", "csrf_token": token},
        follow_redirects=False,
    )
    assert admin.get(f"/b/{book.slug}/welcome").status_code == 200

    admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert admin.get(f"/b/{book.slug}/welcome").status_code == 404
    trash = admin.get("/admin/trash")
    assert "欢迎" in trash.text

    admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/restore",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert admin.get(f"/b/{book.slug}/welcome").status_code == 200


def test_editor_cannot_manage_users(admin, csrf, db) -> None:
    create_user(db, username="editor01", password="EditorPass123", display_name="编辑", role="editor")
    db.commit()
    token = csrf(admin)
    admin.post(
        "/admin/users/new",
        data={"username": "editor02", "password": "EditorPass456", "display_name": "编辑2", "role": "editor", "csrf_token": token},
        follow_redirects=False,
    )
    admin.post("/admin/logout", data={"csrf_token": token}, follow_redirects=False)
    login = admin.post(
        "/admin/login", data={"username": "editor01", "password": "EditorPass123"}, follow_redirects=False
    )
    assert login.status_code == 303
    response = admin.get("/admin/users")
    assert response.status_code == 403


def test_site_settings_take_effect(admin, csrf) -> None:
    token = csrf(admin, "/admin/settings")
    response = admin.post(
        "/admin/settings",
        data={"site_name": "研发知识库", "site_footer": "内部", "home_intro": "欢迎光临", "csrf_token": token},
    )
    assert response.status_code == 200
    home = admin.get("/")
    assert "研发知识库" in home.text
    assert "欢迎光临" in home.text


def test_home_intro_is_sanitized(admin, csrf) -> None:
    token = csrf(admin, "/admin/settings")
    admin.post(
        "/admin/settings",
        data={
            "site_name": "研发知识库",
            "site_footer": "内部",
            "home_intro": '<p>允许的段落</p><script>alert(1)</script><iframe src="x"></iframe>',
            "csrf_token": token,
        },
    )
    home = admin.get("/")
    assert "允许的段落" in home.text
    assert "<script>alert(1)</script>" not in home.text
    assert "<iframe" not in home.text


def test_preview_draft_chapter(admin, db) -> None:
    seeded = _seed(db)
    page = admin.get(f"/admin/books/{seeded['book'].id}/chapters/{seeded['draft'].id}/preview")
    assert page.status_code == 200
    assert "草稿正文" in page.text
    assert "预览模式" in page.text
    # 预览不改变可见性
    assert admin.get(f"/b/{seeded['book'].slug}/draft").status_code == 404


def test_edit_chapter_slug(admin, csrf, db) -> None:
    seeded = _seed(db)
    book = seeded["book"]
    chapter = seeded["chapter"]
    token = csrf(admin, f"/admin/books/{book.id}/chapters/{chapter.id}")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/info",
        data={
            "title": chapter.title,
            "slug": "welcome-new",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db.refresh(chapter)
    assert chapter.slug == "welcome-new"
    assert admin.get(f"/b/{book.slug}/welcome-new").status_code == 200


def test_upload_too_large_returns_413(tmp_path) -> None:
    settings = make_settings(tmp_path, max_upload_bytes=1024)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/admin/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
        token = csrf_token(client)
        client.post(
            "/admin/books/new",
            data={"title": "限额手册", "slug": "", "group": "default", "summary": "", "icon": "", "format": "markdown", "visibility": "public", "sort_order": "", "csrf_token": token},
            follow_redirects=False,
        )
        book_id = 1
        form_token = csrf_token(client, f"/admin/books/{book_id}/chapters/new")
        response = client.post(
            f"/admin/books/{book_id}/chapters/new",
            data={"title": "大文件", "slug": "", "format": "markdown", "status": "draft", "content": "", "encoding": "", "csrf_token": form_token},
            files={"upload": ("big.md", b"x" * 5000, "text/markdown")},
        )
        assert response.status_code == 413
        assert "上限" in response.text


def test_content_too_long_returns_422(tmp_path) -> None:
    settings = make_settings(tmp_path, max_content_chars=100)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/admin/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
        token = csrf_token(client)
        client.post(
            "/admin/books/new",
            data={"title": "限额手册", "slug": "", "group": "default", "summary": "", "icon": "", "format": "markdown", "visibility": "public", "sort_order": "", "csrf_token": token},
            follow_redirects=False,
        )
        form_token = csrf_token(client, "/admin/books/1/chapters/new")
        response = client.post(
            "/admin/books/1/chapters/new",
            data={
                "title": "超长",
                "slug": "",
                "format": "markdown",
                "status": "draft",
                "content": "x" * 500,
                "encoding": "",
                "csrf_token": form_token,
            },
        )
        assert response.status_code == 422


def test_audit_page_lists_entries(admin, csrf, db) -> None:
    books_service.create_book(db, title="审计手册")
    db.commit()
    page = admin.get("/admin/audit")
    assert page.status_code == 200
    assert "book.create" in page.text


def test_root_path_links(tmp_path) -> None:
    settings = make_settings(tmp_path, root_path="/kb")
    run_migrations(settings.database_url)
    app = create_app(settings)
    session = app.state.sessionmaker()
    books_service.create_book(session, title="子路径手册")
    session.commit()
    session.close()
    with TestClient(app, root_path="/kb") as prefixed:
        response = prefixed.get("/kb/")
        assert response.status_code == 200
        assert "/kb/static/style.css" in response.text
        assert "/kb/b/" in response.text


def test_create_book_without_format_rejected(admin, csrf) -> None:
    token = csrf(admin)
    response = admin.post(
        "/admin/books/new",
        data={"title": "没选类型", "slug": "", "group": "default", "summary": "", "icon": "", "format": "", "visibility": "public", "sort_order": "", "csrf_token": token},
    )
    assert response.status_code == 400
    assert "文档类型" in response.text


def test_html_book_upload_only_accepts_html(admin, csrf, db) -> None:
    """整本单一格式：HTML 书只接受 .html 上传，.md 被拒绝。"""
    book = books_service.create_book(db, title="HTML 书", slug_raw="html-only", fmt="html")
    db.commit()
    token = csrf(admin, f"/admin/books/{book.id}/chapters/new")
    unsupported = admin.post(
        f"/admin/books/{book.id}/chapters/new",
        data={"title": "", "slug": "", "status": "draft", "content": "", "encoding": "", "csrf_token": token},
        files={"upload": ("report.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert unsupported.status_code == 400
    assert "不支持" in unsupported.text

    ok_token = csrf(admin, f"/admin/books/{book.id}/chapters/new")
    good = admin.post(
        f"/admin/books/{book.id}/chapters/new",
        data={"title": "页面", "slug": "page", "status": "published", "content": "", "encoding": "", "csrf_token": ok_token},
        files={"upload": ("page.html", b"<h1>hi</h1><script>alert(1)</script>", "text/html")},
        follow_redirects=False,
    )
    assert good.status_code == 303
    detail = admin.get(f"/api/v1/books/{book.slug}").json()
    assert detail["format"] == "html"
    formats = {
        section["format"] for chapter in detail["chapters"] for section in chapter["sections"]
    }
    assert formats == {"html"}

    # 同一本 HTML 书里上传 .md：扩展名与 Book 类型不符，直接拒绝
    md_token = csrf(admin, f"/admin/books/{book.id}/chapters/new")
    mixed = admin.post(
        f"/admin/books/{book.id}/chapters/new",
        data={"title": "笔记", "slug": "notes", "status": "published", "content": "", "encoding": "", "csrf_token": md_token},
        files={"upload": ("notes.md", b"# md", "text/markdown")},
        follow_redirects=False,
    )
    assert mixed.status_code == 400
    assert "HTML" in mixed.text
    detail = admin.get(f"/api/v1/books/{book.slug}").json()
    formats = {
        section["format"] for chapter in detail["chapters"] for section in chapter["sections"]
    }
    assert formats == {"html"}


def test_create_form_hides_slug(admin) -> None:
    html = admin.get("/admin/books/new").text
    assert 'name="slug"' not in html, "新建页不应出现 slug 输入"
    assert "访问地址会自动生成" in html


def test_create_book_generates_slug_automatically(admin, csrf) -> None:
    token = csrf(admin)
    response = admin.post(
        "/admin/books/new",
        data={
            "title": "自动地址手册",
            "group": "default",
            "summary": "",
            "icon": "📘",
            "format": "markdown",
            "visibility": "public",
            "sort_order": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert "notice=book-created" in location
    book_id = int(location.split("?")[0].rstrip("/").split("/")[-1])

    detail = admin.get(f"/api/v1/books/{book_id}").json()
    slug = detail["slug"]
    assert re.fullmatch(r"[a-z0-9-]+", slug)
    assert slug.startswith("book-"), f"中文标题应回退 book- 前缀，实际 {slug}"
    assert admin.get(f"/b/{slug}").status_code == 200


def test_edit_form_keeps_slug_editable(admin, csrf, db) -> None:
    book = books_service.create_book(db, title="改址手册", slug_raw="before-edit")
    db.commit()
    page = admin.get(f"/admin/books/{book.id}/edit")
    assert page.status_code == 200
    assert 'name="slug"' in page.text

    token = csrf(admin, f"/admin/books/{book.id}/edit")
    response = admin.post(
        f"/admin/books/{book.id}/edit",
        data={
            "title": book.title,
            "group": "default",
            "slug": "after-edit",
            "summary": "",
            "icon": "",
            "format": book.format,
            "visibility": "public",
            "sort_order": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert admin.get("/b/after-edit").status_code == 200
    assert admin.get("/b/before-edit").status_code == 404
