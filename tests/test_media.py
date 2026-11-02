"""媒体库：类型判定、内容寻址、配额、访问控制、引用清理与部署前缀重写。"""

from __future__ import annotations

import io
import re

import pytest

from app.errors import PayloadTooLarge, QuotaExceeded, UnsupportedMediaType, ValidationFailed
from app.models import VISIBILITY_UNLISTED
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import media as media_service
from app.services import sections as sections_service
from app.services import tokens as token_service

from .conftest import csrf_token, make_settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PNG_ALT = b"\x89PNG\r\n\x1a\n" + b"\x01" * 72
PDF = b"%PDF-1.7\n" + b"x" * 32


# ------------------------------------------------------------------ 单元：类型判定


def test_detect_accepts_known_binary_types() -> None:
    assert media_service.detect_media_type("a.png", PNG).mime == "image/png"
    assert media_service.detect_media_type("a.pdf", PDF).kind == "attachment"
    assert media_service.detect_media_type("a.ZIP", b"PK\x03\x04rest").mime == "application/zip"


def test_detect_rejects_extension_content_mismatch() -> None:
    with pytest.raises(UnsupportedMediaType):
        media_service.detect_media_type("fake.png", b"#!/bin/sh\necho hi\n")


def test_detect_rejects_extension_outside_whitelist() -> None:
    with pytest.raises(UnsupportedMediaType):
        media_service.detect_media_type("run.exe", b"MZ\x90\x00")
    with pytest.raises(UnsupportedMediaType):
        media_service.detect_media_type("noext", PNG)


def test_detect_rejects_svg_with_script() -> None:
    evil = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with pytest.raises(UnsupportedMediaType):
        media_service.detect_media_type("x.svg", evil)
    ok = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    assert media_service.detect_media_type("x.svg", ok).mime == "image/svg+xml"


def test_safe_name_strips_path_and_control_chars() -> None:
    assert media_service.safe_name("../../etc/passwd.png") == "passwd.png"
    assert media_service.safe_name("a b\x00c.png") == "a-bc.png"
    assert media_service.safe_name("---.PNG").endswith(".png")


def test_storage_path_stays_inside_media_root(settings) -> None:
    path = media_service.storage_path(settings, "demo", "abc-arch.png")
    assert path.parent == media_service.media_root(settings) / "demo"
    with pytest.raises(ValidationFailed):
        media_service.storage_path(settings, "demo", "../../escape.png")
    with pytest.raises(ValidationFailed):
        media_service.storage_path(settings, "../demo", "abc.png")


# ------------------------------------------------------------------ 服务层：落盘与配额


def _book(db, *, fmt="markdown", visibility="public"):
    book = books_service.create_book(db, title="媒体手册", fmt=fmt, visibility=visibility)
    db.commit()
    return book


def test_save_media_writes_file_and_dedupes(db, settings) -> None:
    book = _book(db)
    first = media_service.save_media(
        db, book=book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    target = media_service.storage_path(settings, book.slug, first.stored_name)
    assert target.exists()
    assert first.kind == "image"

    again = media_service.save_media(
        db, book=book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    assert again.id == first.id
    assert len(media_service.list_media(db, book.id)) == 1
    assert media_service.usage(db, book.id, settings)["used"] == len(PNG)


def test_save_media_rejects_oversize_and_quota(db, tmp_path) -> None:
    small = make_settings(tmp_path, media_max_bytes=100, media_quota_bytes=130)
    book = books_service.create_book(db, title="小配额", fmt="markdown")
    db.commit()
    with pytest.raises(PayloadTooLarge):
        media_service.save_media(
            db, book=book, filename="big.png", data=PNG * 2, settings=small, actor=None
        )
    media_service.save_media(
        db, book=book, filename="a.png", data=PNG, settings=small, actor=None
    )
    db.commit()
    with pytest.raises(QuotaExceeded):
        media_service.save_media(
            db, book=book, filename="b.png", data=PNG_ALT, settings=small, actor=None
        )
    assert len(media_service.list_media(db, book.id)) == 1


def test_same_bytes_can_belong_to_two_books(db, settings) -> None:
    first_book = _book(db)
    second_book = books_service.create_book(db, title="第二本", fmt="markdown")
    db.commit()
    first = media_service.save_media(
        db, book=first_book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    second = media_service.save_media(
        db, book=second_book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    assert first.id != second.id
    assert first.stored_name == second.stored_name
    assert media_service.storage_path(settings, first_book.slug, first.stored_name).exists()
    assert media_service.storage_path(settings, second_book.slug, second.stored_name).exists()


def test_delete_is_soft_and_idempotent(db, settings) -> None:
    book = _book(db)
    asset = media_service.save_media(
        db, book=book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    media_service.delete_media(db, book=book, asset=asset, actor=None)
    db.commit()
    assert media_service.find_media(db, book, asset.stored_name) is None
    assert media_service.find_media(db, book, asset.stored_name, include_deleted=True) is not None
    assert media_service.storage_path(settings, book.slug, asset.stored_name).exists()
    media_service.delete_media(db, book=book, asset=asset, actor=None)
    db.commit()
    assert media_service.usage(db, book.id, settings)["used"] == 0


def test_cleanup_preview_then_confirm(db, settings) -> None:
    book = _book(db)
    used = media_service.save_media(
        db, book=book, filename="used.png", data=PNG, settings=settings, actor=None
    )
    media_service.save_media(
        db, book=book, filename="orphan.png", data=PNG_ALT, settings=settings, actor=None
    )
    chapters_service.create_chapter_with_section(
        db,
        book,
        title="架构",
        raw=f"![图](/media/{book.slug}/{used.stored_name})",
        status="published",
    )
    db.commit()

    plan = media_service.cleanup_plan(db, book, settings)
    assert [item["filename"] for item in plan["deleted"]] == ["orphan.png"]
    assert len(media_service.list_media(db, book.id)) == 2

    result = media_service.cleanup(db, book=book, settings=settings, actor=None, confirm=True)
    db.commit()
    assert result["applied"] is True
    assert [item["filename"] for item in result["deleted"]] == ["orphan.png"]
    assert [asset.filename for asset in media_service.list_media(db, book.id)] == ["used.png"]


def test_cleanup_keeps_assets_referenced_by_history(db, settings) -> None:
    book = _book(db)
    asset = media_service.save_media(
        db, book=book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    _chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="v1", raw=f"![图](/media/{book.slug}/{asset.stored_name})"
    )
    db.commit()
    sections_service.replace_content(db, section, raw="没有任何图片了", actor=None)
    db.commit()

    plan = media_service.cleanup_plan(db, book, settings)
    assert plan["deleted"] == []
    assert media_service.referenced_names(db, book.id) == {asset.stored_name}


def test_stale_references_detects_missing_asset(db, settings) -> None:
    book = _book(db)
    asset = media_service.save_media(
        db, book=book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    chapters_service.create_chapter_with_section(
        db,
        book,
        title="引用",
        raw=f"![好](/media/{book.slug}/{asset.stored_name})\n![坏](/media/{book.slug}/deadbeef-gone.png)",
    )
    db.commit()
    stale = media_service.stale_references(db, book)
    assert stale == [f"/media/{book.slug}/deadbeef-gone.png"]


# ------------------------------------------------------------------ 部署前缀


def test_prefix_media_urls(settings) -> None:
    html = '<p><img src="/media/demo/abc.png" alt="x"><a href="/media/demo/a.pdf">f</a></p>'
    assert media_service.prefix_media_urls(html, "") == html
    prefixed = media_service.prefix_media_urls(html, "/kb")
    assert 'src="/kb/media/demo/abc.png"' in prefixed
    assert 'href="/kb/media/demo/a.pdf"' in prefixed


def test_chapter_page_rewrites_media_for_root_path(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import run_migrations

    settings = make_settings(tmp_path, root_path="/kb")
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.sessionmaker() as session:
            book = books_service.create_book(session, title="前缀书", fmt="markdown")
            session.commit()
            asset = media_service.save_media(
                session,
                book=book,
                filename="arch.png",
                data=PNG,
                settings=settings,
                actor=None,
            )
            chapter = chapters_service.create_chapter_with_section(
                session,
                book,
                title="图",
                raw=f"![图](/media/{book.slug}/{asset.stored_name})",
                status="published",
            )[0]
            session.commit()
            book_slug, chapter_slug = book.slug, chapter.slug
        html = client.get(f"/b/{book_slug}/{chapter_slug}").text
        assert f"/kb/media/{book_slug}/{asset.stored_name}" in html
        # 原文与导出保持作者写的根相对地址
        raw = client.get(f"/api/v1/books/{book_slug}/chapters/{chapter_slug}").json()
        assert raw["section"]["content_raw"].startswith("![图](/media/")


# ------------------------------------------------------------------ 公开读取


def _upload(client, csrf, book_slug, *, filename="arch.png", data=PNG, url=None):
    endpoint = url or f"/admin/books/{book_slug}/media"
    return client.post(
        endpoint,
        data={"csrf_token": csrf},
        files={"upload": (filename, io.BytesIO(data), "image/png")},
    )


def test_public_media_route_requires_login_for_unlisted(admin, db, settings) -> None:
    book = _book(db, visibility=VISIBILITY_UNLISTED)
    asset = media_service.save_media(
        db, book=book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    path = f"/media/{book.slug}/{asset.stored_name}"
    assert admin.get(path).status_code == 200
    admin.cookies.clear()
    assert admin.get(path).status_code == 401


def test_public_media_route_serves_public_book(client, db, settings) -> None:
    book = _book(db)
    asset = media_service.save_media(
        db, book=book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    response = client.get(f"/media/{book.slug}/{asset.stored_name}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert "immutable" in response.headers["cache-control"]
    assert response.content == PNG


def test_unlisted_media_requires_token_covering_the_book(client, db, settings) -> None:
    """解包 unlisted 媒体的 API Token 必须自身范围覆盖该 Book。"""
    book = _book(db, visibility=VISIBILITY_UNLISTED)
    other = books_service.create_book(db, title="范围外手册", fmt="markdown")
    db.commit()
    asset = media_service.save_media(
        db, book=book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    _outside, raw_outside = token_service.issue_token(
        db, name="media-outside", scopes=["read"], book_ids=[other.id]
    )
    _inside, raw_inside = token_service.issue_token(
        db, name="media-inside", scopes=["read"], book_ids=[book.id]
    )
    db.commit()
    path = f"/media/{book.slug}/{asset.stored_name}"
    assert client.get(path, headers={"Authorization": f"Bearer {raw_outside}"}).status_code == 401
    assert client.get(path, headers={"Authorization": f"Bearer {raw_inside}"}).status_code == 200


def test_svg_media_is_served_with_sandbox_csp(client, db, settings) -> None:
    """SVG 是同源可执行的“图片”，必须带 CSP sandbox 才能 inline 返回。"""
    book = _book(db)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    asset = media_service.save_media(
        db, book=book, filename="pic.svg", data=svg, settings=settings, actor=None
    )
    db.commit()
    response = client.get(f"/media/{book.slug}/{asset.stored_name}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    csp = response.headers["content-security-policy"]
    assert "sandbox" in csp
    assert "default-src 'none'" in csp


def test_public_media_route_404_for_deleted_asset_and_bad_path(client, db, settings) -> None:
    book = _book(db)
    asset = media_service.save_media(
        db, book=book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    media_service.delete_media(db, book=book, asset=asset, actor=None)
    db.commit()
    assert client.get(f"/media/{book.slug}/{asset.stored_name}").status_code == 404
    assert client.get(f"/media/{book.slug}/..%2fescape.png").status_code == 404
    assert client.get("/media/nope/abc.png").status_code == 404


# ------------------------------------------------------------------ 管理端上传


def test_admin_upload_returns_json_and_inserts_reference(admin, db) -> None:
    book = _book(db)
    token = csrf_token(admin, f"/admin/books/{book.id}/chapters/new")
    response = admin.post(
        f"/admin/books/{book.id}/media",
        data={"csrf_token": token},
        files={"upload": ("架构图.png", io.BytesIO(PNG), "image/png")},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["kind"] == "image"
    assert payload["url"].startswith(f"/media/{book.slug}/")
    assert payload["filename"] == "架构图.png"


def test_admin_upload_requires_csrf(admin, db) -> None:
    book = _book(db)
    response = admin.post(
        f"/admin/books/{book.id}/media",
        files={"upload": ("arch.png", io.BytesIO(PNG), "image/png")},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_admin_upload_error_is_json(admin, db) -> None:
    book = _book(db)
    token = csrf_token(admin, f"/admin/books/{book.id}/chapters/new")
    response = admin.post(
        f"/admin/books/{book.id}/media",
        data={"csrf_token": token},
        files={"upload": ("evil.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_media_page_lists_assets_and_marks_usage(admin, db, settings) -> None:
    book = _book(db)
    asset = media_service.save_media(
        db, book=book, filename="arch.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    html = admin.get(f"/admin/books/{book.id}/media").text
    assert "媒体库" in html
    assert asset.stored_name in html
    assert "未引用" in html
    assert 'data-media-upload' in html


def test_media_page_delete_and_cleanup(admin, db, settings) -> None:
    book = _book(db)
    media_service.save_media(
        db, book=book, filename="orphan.png", data=PNG, settings=settings, actor=None
    )
    db.commit()
    token = csrf_token(admin, f"/admin/books/{book.id}/media")
    cleaned = admin.post(
        f"/admin/books/{book.id}/media/cleanup",
        data={"csrf_token": token, "confirm": "1"},
        follow_redirects=False,
    )
    assert cleaned.status_code == 303
    assert media_service.list_media(db, book.id) == []

    other = media_service.save_media(
        db, book=book, filename="other.png", data=PNG_ALT, settings=settings, actor=None
    )
    db.commit()
    deleted = admin.post(
        f"/admin/books/{book.id}/media/{other.id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert media_service.list_media(db, book.id) == []


def test_chapter_form_has_media_hooks(admin, db) -> None:
    book = _book(db)
    html = admin.get(f"/admin/books/{book.id}/chapters/new").text
    assert "data-media-upload" in html
    assert f'data-upload-url="/admin/books/{book.id}/media"' in html
    assert re.search(r'data-format="markdown"', html)
