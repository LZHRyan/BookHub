"""Book 封面：引用校验、自动解绑、页面回退与 API 字段。"""

from __future__ import annotations

import pytest

from app.errors import ValidationFailed
from app.services import books as books_service
from app.services import media as media_service

from .conftest import csrf_token

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"x" * 32
AUTH = {"Authorization": "Bearer bh_cover_token_0123456789"}


def _book(db, *, title="封面手册"):
    book = books_service.create_book(db, title=title, fmt="markdown")
    db.commit()
    return book


def _image(db, settings, book, name="cover.png"):
    asset = media_service.save_media(
        db, book=book, filename=name, data=PNG, settings=settings, actor=None
    )
    db.commit()
    return asset


def _attachment(db, settings, book):
    asset = media_service.save_media(
        db, book=book, filename="doc.pdf", data=PDF, settings=settings, actor=None
    )
    db.commit()
    return asset


# ------------------------------------------------------------------ 服务层


def test_set_cover_and_clear(db, settings) -> None:
    book = _book(db)
    asset = _image(db, settings, book)
    books_service.set_cover(db, book, asset.id)
    db.commit()
    assert book.cover_media_id == asset.id

    books_service.set_cover(db, book, None)
    db.commit()
    assert book.cover_media_id is None


def test_set_cover_rejects_foreign_resource(db, settings) -> None:
    book = _book(db)
    other = _book(db, title="另一本")
    foreign = _image(db, settings, other)
    with pytest.raises(ValidationFailed) as excinfo:
        books_service.set_cover(db, book, foreign.id)
    assert "Book" in str(excinfo.value)
    assert book.cover_media_id is None


def test_set_cover_rejects_attachment_and_missing(db, settings) -> None:
    book = _book(db)
    doc = _attachment(db, settings, book)
    with pytest.raises(ValidationFailed):
        books_service.set_cover(db, book, doc.id)
    with pytest.raises(ValidationFailed):
        books_service.set_cover(db, book, 999999)


def test_set_cover_rejects_deleted_asset(db, settings) -> None:
    book = _book(db)
    asset = _image(db, settings, book)
    media_service.delete_media(db, book=book, asset=asset, actor=None)
    db.commit()
    with pytest.raises(ValidationFailed):
        books_service.set_cover(db, book, asset.id)


def test_deleting_cover_image_unbinds(db, settings) -> None:
    book = _book(db)
    asset = _image(db, settings, book)
    books_service.set_cover(db, book, asset.id)
    db.commit()
    assert book.cover_media_id == asset.id

    media_service.delete_media(db, book=book, asset=asset, actor=None)
    db.commit()
    assert book.cover_media_id is None


# ------------------------------------------------------------------ 页面


def test_media_page_offers_set_cover(admin, db, settings) -> None:
    book = _book(db)
    asset = _image(db, settings, book)
    html = admin.get(f"/admin/books/{book.id}/media").text
    assert "设为封面" in html
    assert str(asset.id) in html

    token = csrf_token(admin, f"/admin/books/{book.id}/media")
    response = admin.post(
        f"/admin/books/{book.id}/cover",
        data={"csrf_token": token, "media_id": str(asset.id)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db.expire_all()
    assert book.cover_media_id == asset.id

    page = admin.get(f"/admin/books/{book.id}/media").text
    assert "当前封面" in page
    assert "取消封面" in page


def test_book_form_shows_cover(admin, db, settings) -> None:
    book = _book(db)
    asset = _image(db, settings, book)
    books_service.set_cover(db, book, asset.id)
    db.commit()
    html = admin.get(f"/admin/books/{book.id}/edit").text
    assert "cover-preview" in html
    assert asset.stored_name in html


def test_home_and_book_page_render_cover(client, db, settings) -> None:
    book = _book(db)
    asset = _image(db, settings, book)
    books_service.set_cover(db, book, asset.id)
    db.commit()

    home = client.get("/").text
    assert f"/media/{book.slug}/{asset.stored_name}" in home
    assert "book-cover" in home

    page = client.get(f"/b/{book.slug}").text
    assert "book-cover-sm" in page
    assert f"/media/{book.slug}/{asset.stored_name}" in page


def test_home_falls_back_to_icon_without_cover(client, db) -> None:
    book = _book(db)
    db.commit()
    home = client.get("/").text
    assert "book-cover-fallback" in home
    assert f"/media/{book.slug}/" not in home


# ------------------------------------------------------------------ 管理 API


@pytest.fixture()
def api(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    from .conftest import make_settings, run_migrations

    settings = make_settings(tmp_path, admin_api_token=AUTH["Authorization"].split()[-1])
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, settings


def _upload_png(client, book_slug) -> dict:
    response = client.post(
        f"/api/v1/admin/books/{book_slug}/media",
        files={"file": ("cover.png", PNG, "image/png")},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_api_set_and_clear_cover(api) -> None:
    client, _settings = api
    book = client.post(
        "/api/v1/admin/books",
        json={"title": "API 封面", "format": "markdown", "group": "default"},
        headers=AUTH,
    ).json()
    asset = _upload_png(client, book["slug"])

    patched = client.patch(
        f"/api/v1/admin/books/{book['slug']}",
        json={"cover_media_id": asset["id"]},
        headers=AUTH,
    )
    assert patched.status_code == 200, patched.text
    cover = patched.json()["cover"]
    assert cover["id"] == asset["id"]
    assert cover["url"].endswith(asset["url"].split("/", 1)[-1])

    public = client.get(f"/api/v1/books/{book['slug']}").json()
    assert public["cover"]["id"] == asset["id"]

    cleared = client.patch(
        f"/api/v1/admin/books/{book['slug']}",
        json={"cover_media_id": None},
        headers=AUTH,
    )
    assert cleared.status_code == 200
    assert cleared.json()["cover"] is None


def test_api_rejects_foreign_cover(api) -> None:
    client, _settings = api
    first = client.post(
        "/api/v1/admin/books",
        json={"title": "第一本", "format": "markdown", "group": "default"},
        headers=AUTH,
    ).json()
    second = client.post(
        "/api/v1/admin/books",
        json={"title": "第二本", "format": "markdown", "group": "default"},
        headers=AUTH,
    ).json()
    asset = _upload_png(client, first["slug"])

    response = client.patch(
        f"/api/v1/admin/books/{second['slug']}",
        json={"cover_media_id": asset["id"]},
        headers=AUTH,
    )
    assert response.status_code == 400
    assert "自己的图片" in response.json()["error"]["message"]
