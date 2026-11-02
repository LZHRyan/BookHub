"""管理写接口 `/api/v1/admin` 的契约与安全行为。"""

from __future__ import annotations

import io
import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import tokens as token_service

from .conftest import make_settings, run_migrations

BOOTSTRAP = "bh_test_bootstrap_token_0123456789"
AUTH = {"Authorization": f"Bearer {BOOTSTRAP}"}


@pytest.fixture()
def api(tmp_path):
    settings = make_settings(tmp_path, admin_api_token=BOOTSTRAP)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, settings


def _issue(app, scopes, name="scoped") -> str:
    factory = app.state.sessionmaker
    with factory() as session:
        token, raw = token_service.issue_token(session, name=name, scopes=scopes)
        session.commit()
        return raw


def _create_book(client, *, title="API 手册", fmt="markdown", headers=AUTH) -> dict:
    response = client.post(
        "/api/v1/admin/books",
        # group 是创建 Book 的必填契约（迁移会建好「默认分组」，slug=default）
        json={"title": title, "summary": "通过 API 创建", "format": fmt, "group": "default"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------------ 鉴权


def test_missing_token_rejected(api) -> None:
    client, _ = api
    response = client.post("/api/v1/admin/books", json={"title": "x"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_invalid_token_rejected(api) -> None:
    client, _ = api
    response = client.get("/api/v1/admin/books", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_scope_enforced(api) -> None:
    client, _ = api
    read_token = _issue(client.app, ["read"], name="reader")
    response = client.post(
        "/api/v1/admin/books", json={"title": "只读不该能写"}, headers={"Authorization": f"Bearer {read_token}"}
    )
    assert response.status_code == 403
    assert "write" in response.json()["error"]["message"]

    write_token = _issue(client.app, ["write"], name="writer")
    forbidden = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {write_token}"})
    assert forbidden.status_code == 403
    assert "admin" in forbidden.json()["error"]["message"]


def test_bearer_works_when_public_api_key_configured(tmp_path) -> None:
    """配置了公共读 API_KEY 时，管理 API 仍只认 Bearer。"""
    settings = make_settings(tmp_path, admin_api_token=BOOTSTRAP, api_key="public-key")
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/books", headers=AUTH).status_code == 200
        assert client.get("/api/v1/books").status_code == 401
        assert client.get("/api/v1/books", headers={"X-API-Key": "public-key"}).status_code == 200


# ------------------------------------------------------------------ Book / 章节


def test_create_and_update_book(api) -> None:
    client, _ = api
    book = _create_book(client)
    assert re.fullmatch(r"[a-z0-9-]+", book["slug"]), book["slug"]
    assert book["format"] == "markdown"

    patched = client.patch(
        f"/api/v1/admin/books/{book['slug']}",
        json={"title": "API 手册（改）", "summary": "改过了"},
        headers=AUTH,
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "API 手册（改）"

    detail = client.get(f"/api/v1/books/{book['slug']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "API 手册（改）"


def test_create_chapter_json_and_publish(api) -> None:
    client, _ = api
    book = _create_book(client)
    created = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "第一章", "content": "# 你好\n\n正文", "status": "published"},
        headers=AUTH,
    )
    assert created.status_code == 201, created.text
    chapter = created.json()
    assert chapter["status"] == "published"
    # 章不再返回 format / content，正文在节上
    assert "format" not in chapter
    section = chapter["sections"][0]
    assert section["format"] == "markdown"

    public = client.get(f"/api/v1/books/{book['slug']}/chapters/{chapter['slug']}")
    assert public.status_code == 200
    assert "你好" in public.json()["section"]["content_rendered"]


def test_create_chapter_rejects_other_format(api) -> None:
    """整本单一格式：API 也不能给 Markdown 书写入 HTML 节。"""
    client, _ = api
    book = _create_book(client, fmt="markdown")
    blocked = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "错格式", "content": "<h1>hi</h1>", "format": "html"},
        headers=AUTH,
    )
    assert blocked.status_code == 400
    assert "Markdown" in blocked.json()["error"]["message"]
    listed = client.get(f"/api/v1/admin/books/{book['slug']}/chapters", headers=AUTH).json()
    assert listed["items"] == []


def test_upload_multipart_chapter(api) -> None:
    client, _ = api
    book = _create_book(client)
    response = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        files={"file": ("guide.md", "# 上传\n\n内容".encode(), "text/markdown")},
        data={"status": "published"},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    chapter = response.json()
    assert chapter["title"] == "guide"
    assert chapter["sections"][0]["title"] == "guide"


def test_upload_rejects_wrong_extension(api) -> None:
    client, _ = api
    book = _create_book(client, fmt="html")
    response = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        files={"file": ("guide.pdf", b"%PDF-1.4", "application/pdf")},
        headers=AUTH,
    )
    assert response.status_code == 400
    assert "不支持" in response.json()["error"]["message"]


def test_replace_conflict_and_rollback(api) -> None:
    client, _ = api
    book = _create_book(client)
    chapter = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "版本章", "content": "# v1"},
        headers=AUTH,
    ).json()
    section = chapter["sections"][0]
    base = (
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter['slug']}"
        f"/sections/{section['id']}"
    )

    replaced = client.patch(base, json={"content": "# v2", "base_version": 1}, headers=AUTH)
    assert replaced.status_code == 200
    assert replaced.json()["version"] == 2

    conflict = client.patch(base, json={"content": "# v3", "base_version": 1}, headers=AUTH)
    assert conflict.status_code == 409

    rolled = client.post(f"{base}/rollback/1", headers=AUTH)
    assert rolled.status_code == 200
    assert rolled.json()["version"] == 3
    assert rolled.json()["content_raw"].startswith("# v1")

    diff = client.get(f"{base}/diff?a=1&b=2", headers=AUTH)
    assert diff.status_code == 200
    assert diff.json()["identical"] is False


def test_section_crud_endpoints(api) -> None:
    client, _ = api
    book = _create_book(client)
    chapter = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "多节章", "content": "# 第一节"},
        headers=AUTH,
    ).json()
    base = f"/api/v1/admin/books/{book['slug']}/chapters/{chapter['slug']}"

    created = client.post(
        f"{base}/sections",
        json={"title": "第二节", "content": "# 第二节", "format": "markdown"},
        headers=AUTH,
    )
    assert created.status_code == 201, created.text
    section = created.json()
    assert section["title"] == "第二节"
    assert section["version"] == 1

    listed = client.get(f"{base}/sections", headers=AUTH).json()
    assert len(listed["items"]) == 2
    assert [item["title"] for item in listed["items"]][-1] == "第二节"

    moved = client.post(
        f"{base}/sections/{section['id']}/move", json={"position": 1}, headers=AUTH
    )
    assert moved.status_code == 200
    assert moved.json()["items"][0]["id"] == section["id"]

    preview = client.post(f"{base}/sections/{section['id']}/delete?dry_run=true", headers=AUTH)
    assert preview.json()["dry_run"] is True
    deleted = client.post(f"{base}/sections/{section['id']}/delete?confirm=true", headers=AUTH)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    restored = client.post(f"{base}/sections/{section['id']}/restore", headers=AUTH)
    assert restored.status_code == 200
    assert restored.json()["restored"] is True


def test_delete_preview_then_confirm_then_restore(api) -> None:
    client, _ = api
    book = _create_book(client)
    chapter = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "待删", "content": "x", "status": "published"},
        headers=AUTH,
    ).json()
    base = f"/api/v1/admin/books/{book['slug']}/chapters/{chapter['slug']}"

    preview = client.post(f"{base}/delete?dry_run=true", headers=AUTH)
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert client.get(f"/api/v1/books/{book['slug']}/chapters/{chapter['slug']}").status_code == 200

    refused = client.post(f"{base}/delete", headers=AUTH)
    assert refused.status_code == 400
    assert "confirm" in refused.json()["error"]["message"]

    deleted = client.post(f"{base}/delete?confirm=true", headers=AUTH)
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/books/{book['slug']}/chapters/{chapter['slug']}").status_code == 404

    restored = client.post(f"{base}/restore", headers=AUTH)
    assert restored.status_code == 200
    assert client.get(f"/api/v1/books/{book['slug']}/chapters/{chapter['slug']}").status_code == 200


def test_move_and_batch(api) -> None:
    client, _ = api
    book = _create_book(client)
    ids = []
    for index in range(3):
        created = client.post(
            f"/api/v1/admin/books/{book['slug']}/chapters",
            json={"title": f"章{index}", "content": f"# {index}"},
            headers=AUTH,
        ).json()
        ids.append(created["id"])

    moved = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters/{ids[2]}/move",
        json={"position": 1},
        headers=AUTH,
    )
    assert moved.status_code == 200
    assert [item["id"] for item in moved.json()["items"]][0] == ids[2]

    batch = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters/batch",
        json={"action": "publish", "chapter_ids": ids + [999999]},
        headers=AUTH,
    )
    assert batch.status_code == 200
    body = batch.json()
    assert body["ok_count"] == 3
    assert body["failed_count"] == 1
    assert body["results"][-1]["ok"] is False


# ------------------------------------------------------------------ 幂等


def test_idempotency_replays_first_result(api) -> None:
    client, _ = api
    book = _create_book(client)
    headers = {**AUTH, "Idempotency-Key": "create-chapter-1"}
    payload = {"title": "幂等章", "content": "# once"}

    first = client.post(f"/api/v1/admin/books/{book['slug']}/chapters", json=payload, headers=headers)
    second = client.post(f"/api/v1/admin/books/{book['slug']}/chapters", json=payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.headers.get("Idempotent-Replay") == "true"

    listing = client.get(f"/api/v1/admin/books/{book['slug']}/chapters", headers=AUTH).json()
    assert len(listing["items"]) == 1

    conflict = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "不同内容", "content": "# other"},
        headers=headers,
    )
    assert conflict.status_code == 409


# ------------------------------------------------------------------ 审计 / 账号 / 设置 / Token


def test_audit_attributes_to_token(api) -> None:
    client, _ = api
    book = _create_book(client)
    client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "审计章", "content": "x"},
        headers=AUTH,
    )
    audit = client.get("/api/v1/admin/audit", headers=AUTH).json()
    actors = {item["actor"] for item in audit["items"]}
    assert any(actor.startswith("api:") for actor in actors), actors
    assert any(item["action"] == "chapter.create" for item in audit["items"])


def test_users_and_settings_require_admin_scope(tmp_path) -> None:
    settings = make_settings(tmp_path, admin_api_token=BOOTSTRAP)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/users",
            json={"username": "apiuser", "password": "ApiUserPass123", "role": "editor"},
            headers=AUTH,
        )
        assert created.status_code == 201, created.text

        saved = client.put(
            "/api/v1/admin/settings",
            json={"site_name": "API 知识库", "site_footer": "API", "home_intro": ""},
            headers=AUTH,
        )
        assert saved.status_code == 200
        assert client.get("/").text.count("API 知识库") >= 1

        listing = client.get("/api/v1/admin/users", headers=AUTH).json()
        assert any(user["username"] == "apiuser" for user in listing["items"])


def test_token_issue_and_revoke_roundtrip(api) -> None:
    client, _ = api
    issued = client.post(
        "/api/v1/admin/tokens",
        json={"name": "cursor-tool", "scopes": ["write"]},
        headers=AUTH,
    )
    assert issued.status_code == 201
    payload = issued.json()
    raw = payload["token"]
    assert raw.startswith("bh_")
    assert payload["scopes"] == ["write"]

    call = client.get("/api/v1/admin/books", headers={"Authorization": f"Bearer {raw}"})
    assert call.status_code == 200

    revoked = client.delete(f"/api/v1/admin/tokens/{payload['id']}", headers=AUTH)
    assert revoked.status_code == 200
    after = client.get("/api/v1/admin/books", headers={"Authorization": f"Bearer {raw}"})
    assert after.status_code == 401


def test_rate_limit_is_per_token(tmp_path) -> None:
    settings = make_settings(tmp_path, admin_api_token=BOOTSTRAP, admin_api_rate_limit=2)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/books", headers=AUTH).status_code == 200
        assert client.get("/api/v1/admin/books", headers=AUTH).status_code == 200
        limited = client.get("/api/v1/admin/books", headers=AUTH)
        assert limited.status_code == 429
        assert "retry-after" in {key.lower() for key in limited.headers}

        other = _issue(app, ["read"], name="other")
        assert client.get("/api/v1/admin/books", headers={"Authorization": f"Bearer {other}"}).status_code == 200


def test_openapi_covers_admin_operations(api) -> None:
    client, _ = api
    schema = client.get("/openapi.json").json()
    admin_paths = [path for path in schema["paths"] if path.startswith("/api/v1/admin")]
    assert len(admin_paths) >= 20
    for path in admin_paths:
        for method, operation in schema["paths"][path].items():
            assert operation.get("operationId"), f"{method} {path} 缺少 operationId"
            assert operation.get("summary"), f"{method} {path} 缺少 summary"
            assert "admin" in operation.get("tags", [])


# ------------------------------------------------------------------ 媒体库


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _upload_media(client, book_ref, *, name="arch.png", data=PNG, headers=None, idem_key=None):
    files = {"file": (name, io.BytesIO(data), "image/png")}
    merged = dict(headers or AUTH)
    if idem_key:
        merged["Idempotency-Key"] = idem_key
    return client.post(f"/api/v1/admin/books/{book_ref}/media", files=files, headers=merged)


def test_media_upload_and_list(api) -> None:
    client, _ = api
    book = _create_book(client)
    created = _upload_media(client, book["slug"])
    assert created.status_code == 201, created.text
    asset = created.json()
    assert asset["kind"] == "image"
    assert asset["url"].startswith(f"/media/{book['slug']}/")

    listed = client.get(f"/api/v1/admin/books/{book['slug']}/media", headers=AUTH)
    assert listed.status_code == 200
    body = listed.json()
    assert body["items"][0]["stored_name"] == asset["stored_name"]
    assert body["items"][0]["referenced"] is False
    assert body["usage"]["used"] == len(PNG)
    assert body["usage"]["limit"] > 0


def test_media_upload_requires_write_scope(api) -> None:
    client, _ = api
    book = _create_book(client)
    read_only = _issue(client.app, ["read"], name="reader-media")
    response = _upload_media(
        client, book["slug"], headers={"Authorization": f"Bearer {read_only}"}
    )
    assert response.status_code == 403
    assert "write" in response.json()["error"]["message"]


def test_media_upload_is_idempotent(api) -> None:
    client, _ = api
    book = _create_book(client)
    key = "media-key-1"
    first = _upload_media(client, book["slug"], idem_key=key)
    assert first.status_code == 201
    again = _upload_media(client, book["slug"], idem_key=key)
    assert again.status_code == 201
    assert again.headers.get("Idempotent-Replay") == "true"
    assert again.json()["id"] == first.json()["id"]


def test_media_delete_needs_confirm_and_supports_dry_run(api) -> None:
    client, _ = api
    book = _create_book(client)
    asset = _upload_media(client, book["slug"]).json()
    url = f"/api/v1/admin/books/{book['slug']}/media/{asset['id']}"

    preview = client.delete(f"{url}?dry_run=true", headers=AUTH)
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True

    blocked = client.delete(url, headers=AUTH)
    assert blocked.status_code == 400
    assert "confirm" in blocked.json()["error"]["message"]

    done = client.delete(f"{url}?confirm=true", headers=AUTH)
    assert done.status_code == 200
    assert done.json()["deleted_at"] is not None

    listed = client.get(f"/api/v1/admin/books/{book['slug']}/media", headers=AUTH).json()
    assert listed["usage"]["used"] == 0


def test_media_cleanup_previews_by_default(api) -> None:
    client, _ = api
    book = _create_book(client)
    _upload_media(client, book["slug"])
    channel = f"/api/v1/admin/books/{book['slug']}/media/cleanup"

    preview = client.post(channel, headers=AUTH)
    assert preview.status_code == 200
    body = preview.json()
    assert body["applied"] is False
    assert len(body["deleted"]) == 1

    applied = client.post(f"{channel}?confirm=true", headers=AUTH)
    assert applied.status_code == 200
    assert applied.json()["applied"] is True
    listed = client.get(f"/api/v1/admin/books/{book['slug']}/media", headers=AUTH).json()
    assert listed["items"][0]["deleted_at"] is not None


def test_media_meta_reports_capability(api) -> None:
    client, _ = api
    body = client.get("/api/v1/admin/meta", headers=AUTH).json()
    assert "media" in body["capabilities"]
    assert body["limits"]["media_max_bytes"] > 0
