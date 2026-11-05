"""对外只读 API 的契约。"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import sections as sections_service

from .conftest import make_settings, run_migrations


@pytest.fixture()
def seeded(db):
    book = books_service.create_book(db, title="研发手册", summary="入职与发布流程")
    welcome, welcome_section = chapters_service.create_chapter_with_section(
        db,
        book,
        title="欢迎使用",
        raw="# 欢迎\n\n知识库起步说明",
        slug_raw="welcome",
        status="published",
        section_slug="main",
    )
    deploy, deploy_section = chapters_service.create_chapter_with_section(
        db,
        book,
        title="部署指南",
        raw="# 部署\n\n用 docker 部署服务",
        slug_raw="deploy",
        status="published",
        section_slug="main",
    )
    draft = chapters_service.create_chapter_with_section(
        db, book, title="草稿章节", raw="未发布内容", slug_raw="draft"
    )[0]
    hidden = books_service.create_book(db, title="隐藏手册", visibility="unlisted")
    chapters_service.create_chapter_with_section(
        db, hidden, title="内部章节", raw="内部秘密内容", slug_raw="secret", status="published"
    )
    db.commit()
    return {
        "book": book,
        "welcome": welcome,
        "welcome_section": welcome_section,
        "deploy": deploy,
        "deploy_section": deploy_section,
        "draft": draft,
        "hidden": hidden,
    }


def test_site_info(client) -> None:
    payload = client.get("/api/v1/site").json()
    assert payload["name"] == "测试知识库"
    assert payload["api"]["version"] == "v1"
    assert payload["capabilities"]["api_key_required"] is False


def test_site_info_follows_admin_settings(admin, csrf) -> None:
    """后台改过站名后，/api/v1/site 要跟网页端一致（数据库覆盖环境变量默认值）。"""
    token = csrf(admin)
    response = admin.post(
        "/admin/settings",
        data={
            "site_name": "改过名的知识库",
            "site_footer": "内部资料",
            "home_intro": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 303), response.status_code
    assert admin.get("/api/v1/site").json()["name"] == "改过名的知识库"


def test_books_list_defaults(client, seeded) -> None:
    payload = client.get("/api/v1/books").json()
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert payload["total"] == 1
    item = payload["items"][0]
    for key in ("id", "slug", "title", "summary", "chapter_count", "updated_at"):
        assert key in item
    assert item["chapter_count"] == 2


def test_books_list_excludes_unlisted(client, seeded) -> None:
    payload = client.get("/api/v1/books").json()
    slugs = [item["slug"] for item in payload["items"]]
    assert seeded["hidden"].slug not in slugs


def test_books_visibility_unlisted_requires_api_key(client, seeded) -> None:
    assert client.get("/api/v1/books?visibility=unlisted").status_code == 400


def test_book_detail_by_slug_and_id(client, seeded) -> None:
    slug = seeded["book"].slug
    by_slug = client.get(f"/api/v1/books/{slug}")
    by_id = client.get(f"/api/v1/books/{seeded['book'].id}")
    assert by_slug.status_code == 200
    assert by_id.status_code == 200
    payload = by_slug.json()
    assert [chapter["slug"] for chapter in payload["chapters"]] == ["welcome", "deploy"]
    assert "content_raw" not in payload["chapters"][0]


def test_book_detail_unknown_404(client) -> None:
    response = client.get("/api/v1/books/nope")
    assert response.status_code == 404
    assert set(response.json()["error"]) == {"code", "message", "request_id"}


def test_chapter_json_payload(client, seeded) -> None:
    slug = seeded["book"].slug
    payload = client.get(f"/api/v1/books/{slug}/chapters/welcome").json()
    # 章只带目录字段与节列表；单节章的正文放在 section 里（兼容旧调用）
    assert payload["sections"][0]["slug"] == seeded["welcome_section"].slug
    assert payload["section"]["content_raw"] == "# 欢迎\n\n知识库起步说明"
    assert "<h1" in payload["section"]["content_rendered"]
    assert payload["section"]["toc"][0]["level"] == 1
    assert payload["section"]["version"] == 1
    assert payload["book"]["slug"] == slug
    # v1 老契约：单节章的正文/格式/版本继续平铺在章顶层
    assert payload["content_raw"] == "# 欢迎\n\n知识库起步说明"
    assert payload["format"] == "markdown"
    assert payload["version"] == 1
    assert payload["word_count"] == seeded["welcome_section"].word_count


def test_section_endpoint_payload(client, seeded) -> None:
    slug = seeded["book"].slug
    section_slug = seeded["welcome_section"].slug
    payload = client.get(f"/api/v1/books/{slug}/chapters/welcome?section={section_slug}").json()
    assert payload["content_raw"] == "# 欢迎\n\n知识库起步说明"
    assert payload["chapter"]["slug"] == "welcome"
    assert payload["url"].endswith(f"/b/{slug}/welcome/{section_slug}")


def test_chapter_raw_channel(client, seeded) -> None:
    slug = seeded["book"].slug
    response = client.get(f"/api/v1/books/{slug}/chapters/welcome?format=raw")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text == seeded["welcome_section"].content_raw


def test_chapter_accept_header_channel(client, seeded) -> None:
    slug = seeded["book"].slug
    response = client.get(
        f"/api/v1/books/{slug}/chapters/welcome", headers={"Accept": "text/markdown"}
    )
    assert response.headers["content-type"].startswith("text/markdown")
    html_response = client.get(
        f"/api/v1/books/{slug}/chapters/welcome", headers={"Accept": "text/html"}
    )
    assert html_response.headers["content-type"].startswith("text/html")
    assert "<h1" in html_response.text


def test_format_param_beats_accept(client, seeded) -> None:
    slug = seeded["book"].slug
    response = client.get(
        f"/api/v1/books/{slug}/chapters/welcome?format=rendered",
        headers={"Accept": "text/markdown"},
    )
    assert response.headers["content-type"].startswith("text/html")


def test_html_chapter_raw_channel_is_sanitized(client, db) -> None:
    book = books_service.create_book(db, title="HTML 手册", fmt="html")
    _chapter, section = chapters_service.create_chapter_with_section(
        db,
        book,
        title="页面",
        raw='<h1>标题</h1><script>alert(1)</script><p onclick="x()">正文</p>',
        fmt="html",
        slug_raw="page",
        status="published",
    )
    db.commit()
    response = client.get(f"/api/v1/books/{book.slug}/chapters/page?format=raw")
    assert response.headers["content-type"].startswith("text/html")
    assert "<script" not in response.text
    assert "onclick" not in response.text
    assert "标题" in response.text
    assert "正文" in response.text
    # 管理端仍保留管理员上传的原始内容，便于排查
    db.refresh(section)
    assert "<script" in section.content_raw


def test_draft_hidden_from_api(client, seeded) -> None:
    slug = seeded["book"].slug
    response = client.get(f"/api/v1/books/{slug}/chapters/draft")
    assert response.status_code == 404
    assert "草稿章节" not in response.text


def test_etag_and_304(client, seeded, db) -> None:
    slug = seeded["book"].slug
    first = client.get(f"/api/v1/books/{slug}/chapters/welcome")
    etag = first.headers["etag"]
    assert etag.startswith('"')
    second = client.get(f"/api/v1/books/{slug}/chapters/welcome", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""

    sections_service.replace_content(db, seeded["welcome_section"], raw="# 欢迎\n\n新内容")
    db.commit()
    third = client.get(f"/api/v1/books/{slug}/chapters/welcome", headers={"If-None-Match": etag})
    assert third.status_code == 200
    assert third.headers["etag"] != etag


def test_conditional_requests_weak_etag_and_last_modified(client, seeded) -> None:
    slug = seeded["book"].slug
    first = client.get(f"/api/v1/books/{slug}/chapters/welcome")
    etag = first.headers["etag"]
    last_modified = first.headers["last-modified"]
    weak = client.get(f"/api/v1/books/{slug}/chapters/welcome", headers={"If-None-Match": f"W/{etag}"})
    assert weak.status_code == 304
    since = client.get(
        f"/api/v1/books/{slug}/chapters/welcome", headers={"If-Modified-Since": last_modified}
    )
    assert since.status_code == 304


def test_changes_skips_unlisted_and_drafts(client, seeded) -> None:
    payload = client.get("/api/v1/changes?since=2000-01-01T00:00:00Z").json()
    chapter_slugs = {item["chapter_slug"] for item in payload["sections"]}
    assert "secret" not in chapter_slugs  # unlisted Book 下的章节
    assert "draft" not in chapter_slugs  # 从未发布过
    assert "welcome" in chapter_slugs


def test_export_json(client, seeded) -> None:
    slug = seeded["book"].slug
    payload = client.get(f"/api/v1/books/{slug}/export?format=json").json()
    assert payload["book"]["slug"] == slug
    assert payload["chapter_count"] == 2
    assert payload["section_count"] == 2
    assert [item["slug"] for item in payload["chapters"]] == ["welcome", "deploy"]


def test_export_zip(client, seeded) -> None:
    slug = seeded["book"].slug
    response = client.get(f"/api/v1/books/{slug}/export?format=zip")
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "book.json" in names
        assert {"welcome/main.md", "deploy/main.md"} <= names
        manifest = json.loads(archive.read("book.json"))
        assert manifest["chapter_count"] == 2


def test_search_endpoint(client, seeded) -> None:
    payload = client.get("/api/v1/search?q=部署").json()
    assert payload["total"] == 1
    assert payload["items"][0]["chapter"]["slug"] == "deploy"
    assert payload["items"][0]["section"]["slug"] == seeded["deploy_section"].slug
    assert "<mark>" in payload["items"][0]["snippet"]


def test_search_scoped_to_book(client, seeded) -> None:
    payload = client.get(f"/api/v1/search?q=隐藏&book={seeded['book'].slug}").json()
    assert payload["total"] == 0


def test_changes_requires_since(client) -> None:
    response = client.get("/api/v1/changes")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_changes_invalid_since(client) -> None:
    assert client.get("/api/v1/changes?since=nope").status_code == 400


def test_changes_reports_tombstone(client, seeded, db) -> None:
    chapters_service.soft_delete_chapter(db, seeded["welcome"])
    db.commit()
    payload = client.get("/api/v1/changes?since=2000-01-01T00:00:00Z").json()
    entry = next(item for item in payload["sections"] if item["chapter_slug"] == "welcome")
    assert entry["deleted"] is True
    # 墓碑只回 id/slug，连标题都不再对 AI 暴露
    assert "title" not in entry
    assert "chapter_title" not in entry


def test_pagination_clamped_and_validated(client) -> None:
    assert client.get("/api/v1/books?page=0").status_code == 400
    assert client.get("/api/v1/books?page=abc").status_code == 400
    payload = client.get("/api/v1/books?page_size=500").json()
    assert payload["page_size"] == 100


def test_write_methods_not_allowed(client) -> None:
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/v1/books")
        assert response.status_code == 405
        assert response.json()["error"]["code"] == "http_error"


def test_unknown_chapter_404(client, seeded) -> None:
    slug = seeded["book"].slug
    assert client.get(f"/api/v1/books/{slug}/chapters/nope").status_code == 404


def test_api_key_enforced(tmp_path) -> None:
    settings = make_settings(tmp_path, api_key="secret-key-value")
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as guarded:
        assert guarded.get("/api/v1/books").status_code == 401
        assert guarded.get("/api/v1/books", headers={"X-API-Key": "wrong"}).status_code == 401
        assert (
            guarded.get("/api/v1/books", headers={"X-API-Key": "secret-key-value"}).status_code == 200
        )
        assert guarded.get("/healthz").status_code == 200
        assert guarded.get("/readyz").status_code == 200
        assert guarded.get("/api/v1/site").status_code == 200


def test_api_key_allows_all_visibility(tmp_path) -> None:
    settings = make_settings(tmp_path, api_key="k" * 32)
    run_migrations(settings.database_url)
    app = create_app(settings)
    session = app.state.sessionmaker()
    books_service.create_book(session, title="隐藏", visibility="unlisted")
    session.commit()
    session.close()
    with TestClient(app) as guarded:
        response = guarded.get("/api/v1/books?visibility=all", headers={"X-API-Key": settings.api_key})
        assert response.status_code == 200
        assert response.json()["total"] == 1


def test_docs_toggle(tmp_path) -> None:
    settings = make_settings(tmp_path, api_docs_enabled=False)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as hidden_docs:
        assert hidden_docs.get("/docs").status_code == 404
        assert hidden_docs.get("/openapi.json").status_code == 404
        assert hidden_docs.get("/api/v1/site").status_code == 200


def test_openapi_lists_all_paths(client) -> None:
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])
    for expected in (
        "/api/v1/books",
        "/api/v1/books/{book_ref}",
        "/api/v1/books/{book_ref}/chapters/{chapter_ref}",
        "/api/v1/books/{book_ref}/export",
        "/api/v1/search",
        "/api/v1/changes",
        "/api/v1/site",
    ):
        assert expected in paths


def test_rate_limit_returns_429(tmp_path) -> None:
    settings = make_settings(tmp_path, rate_limit_enabled=True, rate_limit_per_minute=2)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as limited:
        assert limited.get("/api/v1/site").status_code == 200
        assert limited.get("/api/v1/books").status_code == 200
        response = limited.get("/api/v1/books")
        assert response.status_code == 429
        assert "retry-after" in {key.lower() for key in response.headers}


def test_forwarded_for_is_ignored_without_trusted_proxy(tmp_path) -> None:
    """默认不信任 XFF：伪造头换不来新的限流桶。"""
    settings = make_settings(tmp_path, rate_limit_enabled=True, rate_limit_per_minute=1)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as limited:
        first = limited.get("/api/v1/books", headers={"X-Forwarded-For": "1.1.1.1"})
        assert first.status_code == 200
        spoofed = limited.get("/api/v1/books", headers={"X-Forwarded-For": "2.2.2.2"})
        assert spoofed.status_code == 429


def test_client_ip_only_trusts_configured_proxies(tmp_path) -> None:
    """client_ip：只有直连 peer 在 TRUSTED_PROXIES 内才采信转发头。"""
    from types import SimpleNamespace

    from starlette.requests import Request

    from app.middleware import client_ip

    def probe(peer, forwarded=None, trusted=()):
        settings = make_settings(tmp_path, trusted_proxies=trusted)
        app_stub = SimpleNamespace(state=SimpleNamespace(settings=settings))
        headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": headers,
                "client": (peer, 1234),
                "app": app_stub,
            }
        )
        return client_ip(request)

    # 默认不信任：XFF 被忽略
    assert probe("203.0.113.9", "1.1.1.1") == "203.0.113.9"
    # 可信反代：采信 XFF 的第一跳
    assert probe("10.0.0.5", "1.1.1.1", ("10.0.0.0/8",)) == "1.1.1.1"
    assert probe("10.0.0.5", "1.1.1.1, 10.0.0.7", ("10.0.0.0/8",)) == "1.1.1.1"
    # 可信反代但没带 XFF：用直连地址
    assert probe("10.0.0.5", None, ("10.0.0.0/8",)) == "10.0.0.5"
    # 不在名单里的 peer：忽略 XFF
    assert probe("203.0.113.9", "1.1.1.1", ("10.0.0.0/8",)) == "203.0.113.9"
