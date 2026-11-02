"""管理端输入校验与失败提示：空 slug / 空标题 / 删除失败的提示条。"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import ADMIN_PASSWORD, ADMIN_USER, make_settings, run_migrations

BOOTSTRAP = "bh_validation_token_0123456789"
AUTH = {"Authorization": f"Bearer {BOOTSTRAP}"}


def _api(tmp_path):
    settings = make_settings(tmp_path, admin_api_token=BOOTSTRAP, builtin_guide=True)
    run_migrations(settings.database_url)
    app = create_app(settings)
    return TestClient(app), settings


def _book(client, *, title="校验手册") -> dict:
    response = client.post(
        "/api/v1/admin/books",
        json={"title": title, "format": "markdown", "group": "default"},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------------ 空 slug


def test_patch_book_rejects_blank_slug(tmp_path) -> None:
    with _api(tmp_path)[0] as client:
        book = _book(client)
        response = client.patch(
            f"/api/v1/admin/books/{book['slug']}", json={"slug": "  "}, headers=AUTH
        )
        assert response.status_code == 400
        assert "访问标识不能为空" in response.json()["error"]["message"]
        # 没改到任何东西
        detail = client.get(f"/api/v1/admin/books/{book['slug']}", headers=AUTH).json()
        assert detail["slug"] == book["slug"]


def test_patch_book_without_slug_still_works(tmp_path) -> None:
    with _api(tmp_path)[0] as client:
        book = _book(client)
        response = client.patch(
            f"/api/v1/admin/books/{book['slug']}", json={"title": "只改标题"}, headers=AUTH
        )
        assert response.status_code == 200
        assert response.json()["title"] == "只改标题"
        assert response.json()["slug"] == book["slug"]


# ------------------------------------------------------------------ 空章标题


def test_create_chapter_json_requires_title(tmp_path) -> None:
    with _api(tmp_path)[0] as client:
        book = _book(client)
        response = client.post(
            f"/api/v1/admin/books/{book['slug']}/chapters",
            json={"title": "   ", "content": "# 正文"},
            headers=AUTH,
        )
        assert response.status_code == 400
        assert "章标题必填" in response.json()["error"]["message"]
        listed = client.get(f"/api/v1/admin/books/{book['slug']}/chapters", headers=AUTH).json()
        assert listed["items"] == []


def test_create_chapter_multipart_keeps_filename_fallback(tmp_path) -> None:
    """上传文件时可以省略 title：标题回落为文件名（这是既有契约，不能被收紧误伤）。"""
    with _api(tmp_path)[0] as client:
        book = _book(client)
        response = client.post(
            f"/api/v1/admin/books/{book['slug']}/chapters",
            data={"status": "draft"},
            files=[("upload", ("01-intro.md", b"# hello", "text/markdown"))],
            headers=AUTH,
        )
        assert response.status_code == 201, response.text
        chapter = response.json()
        assert chapter["title"] == "01-intro"
        assert len(chapter["sections"]) == 1


# ------------------------------------------------------------------ 网页端失败提示


def _login(client) -> None:
    response = client.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _csrf(client, path: str) -> str:
    html = client.get(path).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, f"{path} 没有 csrf_token"
    return match.group(1)


def test_web_delete_failure_redirects_with_error_banner(tmp_path) -> None:
    with _api(tmp_path)[0] as client:
        _login(client)
        guide = client.get(
            "/api/v1/admin/books/ai-agent-guide", headers=AUTH
        ).json()
        token = _csrf(client, f"/admin/books/{guide['id']}")
        response = client.post(
            f"/admin/books/{guide['id']}/delete",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers["location"]
        assert "error=" in location

        page = client.get(location)
        assert page.status_code == 200
        assert "内置指南" in page.text
        # 书还在
        assert client.get("/api/v1/admin/books/ai-agent-guide", headers=AUTH).json()["deleted"] is False


def test_dashboard_renders_error_query(tmp_path) -> None:
    with _api(tmp_path)[0] as client:
        _login(client)
        page = client.get("/admin?error=这里是一段错误提示")
        assert page.status_code == 200
        assert "这里是一段错误提示" in page.text


def test_web_edit_blank_slug_shows_form_error(tmp_path) -> None:
    with _api(tmp_path)[0] as client:
        _login(client)
        book = _book(client)
        book_id = book["id"]
        token = _csrf(client, f"/admin/books/{book_id}/edit")
        response = client.post(
            f"/admin/books/{book_id}/edit",
            data={
                "title": book["title"],
                "slug": "",
                "group": "default",
                "summary": "",
                "icon": "",
                "format": "markdown",
                "html_view": "inline",
                "visibility": "public",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "访问标识不能为空" in response.text
