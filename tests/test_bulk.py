"""拖拽排序、批量操作与 Book 置顶。"""

from __future__ import annotations

import pytest

from app.errors import ValidationFailed
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import ranking
from app.services import sections as sections_service

from .conftest import csrf_token

AUTH = {"Authorization": "Bearer bh_bulk_token_0123456789"}


def _book(db, *, fmt="markdown", title="批量手册"):
    book = books_service.create_book(db, title=title, fmt=fmt)
    db.commit()
    return book


def _chapter(db, book, title, *, status="draft"):
    chapter, _section = chapters_service.create_chapter_with_section(
        db, book, title=title, raw=f"# {title}", status=status
    )
    db.commit()
    return chapter


# ------------------------------------------------------------------ 章排序


def test_reorder_chapters_rewrites_order(db) -> None:
    book = _book(db)
    a = _chapter(db, book, "一")
    b = _chapter(db, book, "二")
    c = _chapter(db, book, "三")
    db.commit()

    chapters_service.reorder_chapters(db, book.id, [b.id, c.id, a.id])
    db.commit()
    rows = chapters_service.ordered_chapters(db, book.id)
    assert [item.id for item in rows] == [b.id, c.id, a.id]
    assert [item.sort_order for item in rows] == [10, 20, 30]


def test_reorder_rejects_incomplete_list(db) -> None:
    book = _book(db)
    a = _chapter(db, book, "一")
    b = _chapter(db, book, "二")
    other_book = _book(db, title="另一本")
    foreign = _chapter(db, other_book, "别处")
    db.commit()

    with pytest.raises(ValidationFailed):
        chapters_service.reorder_chapters(db, book.id, [a.id])
    with pytest.raises(ValidationFailed):
        chapters_service.reorder_chapters(db, book.id, [a.id, b.id, foreign.id])
    assert [item.id for item in chapters_service.ordered_chapters(db, book.id)] == [a.id, b.id]


def test_section_reorder_stays_inside_chapter(db) -> None:
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="章")
    db.commit()
    first = sections_service.create_section(db, chapter, title="一", raw="a")
    second = sections_service.create_section(db, chapter, title="二", raw="b")
    db.commit()

    sections_service.reorder_sections(db, chapter, [second.id, first.id])
    db.commit()
    assert [item.id for item in sections_service.ordered_sections(db, chapter.id)] == [
        second.id,
        first.id,
    ]
    other = chapters_service.create_chapter(db, book, title="另一章")
    db.commit()
    with pytest.raises(ValidationFailed):
        sections_service.reorder_sections(db, other, [first.id])


def test_web_reorder_endpoint(admin, db) -> None:
    book = _book(db)
    a = _chapter(db, book, "一")
    b = _chapter(db, book, "二")
    token = csrf_token(admin, f"/admin/books/{book.id}")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/reorder",
        json={"chapter_ids": [b.id, a.id]},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200, response.text
    assert response.json()["order"] == [b.id, a.id]
    db.expire_all()
    assert [item.id for item in chapters_service.ordered_chapters(db, book.id)] == [b.id, a.id]


def test_web_reorder_requires_csrf(admin, db) -> None:
    book = _book(db)
    a = _chapter(db, book, "一")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/reorder",
        json={"chapter_ids": [a.id]},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


# ------------------------------------------------------------------ 批量


def test_web_batch_publish(admin, db) -> None:
    book = _book(db)
    first = _chapter(db, book, "一")
    second = _chapter(db, book, "二")
    token = csrf_token(admin, f"/admin/books/{book.id}")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/batch",
        data={"csrf_token": token, "action": "publish", "chapter_id": [first.id, second.id]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "batch=publish:2,0" in response.headers["location"]
    db.expire_all()
    assert {c.status for c in chapters_service.ordered_chapters(db, book.id)} == {"published"}


def test_web_batch_counts_failures(admin, db) -> None:
    book = _book(db)
    alive = _chapter(db, book, "在的")
    gone = _chapter(db, book, "删掉的")
    chapters_service.soft_delete_chapter(db, gone)
    db.commit()
    token = csrf_token(admin, f"/admin/books/{book.id}")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/batch",
        data={
            "csrf_token": token,
            "action": "publish",
            "chapter_id": [alive.id, 999999],
        },
        follow_redirects=False,
    )
    assert "batch=publish:1,1" in response.headers["location"]
    db.expire_all()
    assert alive.status == "published"


def test_web_batch_delete_requires_confirm(admin, db) -> None:
    book = _book(db)
    chapter = _chapter(db, book, "待删")
    token = csrf_token(admin, f"/admin/books/{book.id}")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/batch",
        data={"csrf_token": token, "action": "delete", "chapter_id": [chapter.id]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db.expire_all()
    assert chapter.deleted_at is None

    confirmed = admin.post(
        f"/admin/books/{book.id}/chapters/batch",
        data={
            "csrf_token": token,
            "action": "delete",
            "confirm": "1",
            "chapter_id": [chapter.id],
        },
        follow_redirects=False,
    )
    assert "batch=delete:1,0" in confirmed.headers["location"]
    db.expire_all()
    assert chapter.deleted_at is not None


def test_web_batch_without_selection_reports_error(admin, db) -> None:
    book = _book(db)
    token = csrf_token(admin, f"/admin/books/{book.id}")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/batch",
        data={"csrf_token": token, "action": "publish"},
        follow_redirects=False,
    )
    assert "error=" in response.headers["location"]


def test_book_page_has_batch_and_drag_hooks(admin, db) -> None:
    book = _book(db)
    _chapter(db, book, "一")
    html = admin.get(f"/admin/books/{book.id}").text
    assert 'id="batch-form"' in html
    assert "data-sortable" in html
    assert 'draggable="true"' in html
    assert "drag-handle" in html
    assert "置顶到首页" in html


# ------------------------------------------------------------------ 置顶


def _view_section(db, book):
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="正文", raw="# 正文"
    )
    db.commit()
    return chapter, section


def test_pinned_books_sort_first(db) -> None:
    hot = _book(db, title="热门")
    cold = _book(db, title="冷门")
    db.commit()
    _chapter_row, hot_section = _view_section(db, hot)
    for _ in range(20):
        ranking.add_view(db, hot_section.id)
    db.commit()

    assert [book.slug for book in ranking.rank_books(db, [hot, cold])] == [hot.slug, cold.slug]

    books_service.update_book(db, cold, pinned=True)
    db.commit()
    order = [book.slug for book in ranking.rank_books(db, [hot, cold])]
    assert order == [cold.slug, hot.slug]

    books_service.update_book(db, cold, pinned=False)
    db.commit()
    assert [book.slug for book in ranking.rank_books(db, [hot, cold])] == [hot.slug, cold.slug]


def test_pinned_books_still_sorted_by_weight(db) -> None:
    first = _book(db, title="置顶冷门")
    second = _book(db, title="置顶热门")
    db.commit()
    books_service.update_book(db, first, pinned=True)
    books_service.update_book(db, second, pinned=True)
    db.commit()
    _chapter_row, second_section = _view_section(db, second)
    for _ in range(10):
        ranking.add_view(db, second_section.id)
    db.commit()
    assert [book.slug for book in ranking.rank_books(db, [first, second])] == [
        second.slug,
        first.slug,
    ]


def test_web_pin_toggle(admin, db) -> None:
    book = _book(db)
    token = csrf_token(admin, f"/admin/books/{book.id}")
    admin.post(
        f"/admin/books/{book.id}/pin", data={"csrf_token": token}, follow_redirects=False
    )
    db.expire_all()
    assert book.pinned is True
    admin.post(
        f"/admin/books/{book.id}/pin", data={"csrf_token": token}, follow_redirects=False
    )
    db.expire_all()
    assert book.pinned is False


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
        yield client


def test_api_reorder_and_pin(api) -> None:
    client = api
    book = client.post(
        "/api/v1/admin/books",
        json={"title": "API 排序", "format": "markdown", "group": "default"},
        headers=AUTH,
    ).json()
    first = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "一", "content": "# 1", "status": "published"},
        headers=AUTH,
    ).json()
    second = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "二", "content": "# 2", "status": "published"},
        headers=AUTH,
    ).json()

    reordered = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters/reorder",
        json={"chapter_ids": [second["id"], first["id"]]},
        headers=AUTH,
    )
    assert reordered.status_code == 200, reordered.text
    assert reordered.json()["order"] == [second["id"], first["id"]]

    bad = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters/reorder",
        json={"chapter_ids": [first["id"]]},
        headers=AUTH,
    )
    assert bad.status_code == 400

    pinned = client.patch(
        f"/api/v1/admin/books/{book['slug']}", json={"pinned": True}, headers=AUTH
    )
    assert pinned.status_code == 200
    assert pinned.json()["pinned"] is True

    public = client.get(f"/api/v1/books/{book['slug']}").json()
    assert public["pinned"] is True
