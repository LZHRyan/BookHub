"""自动排序权重：权重公式、列表顺序、访问计数与去重、管理端与 API 展示。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import SectionViewDaily, utcnow
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import ranking


def _total_views(app) -> int:
    with app.state.sessionmaker() as session:
        total = session.execute(select(func.sum(SectionViewDaily.views))).scalar_one()
        return int(total or 0)


def _section_of(db, book, title="正文", raw="# 正文", status="published"):
    """建一节并返回它（热度计数挂在节上）。"""
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title=title, raw=raw, status=status, section_slug="main"
    )
    db.commit()
    return chapter, section


# ---------------------------------------------------------------- 权重公式


def test_weight_grows_with_views() -> None:
    now = datetime(2026, 5, 1, 12, 0)
    created = now - timedelta(days=3)
    quiet = ranking.compute_weight(recent_views=0, total_views=0, created_at=created, now=now)
    warm = ranking.compute_weight(recent_views=5, total_views=5, created_at=created, now=now)
    hot = ranking.compute_weight(recent_views=50, total_views=50, created_at=created, now=now)
    assert quiet < warm < hot


def test_weight_prefers_newer_books() -> None:
    now = datetime(2026, 5, 1, 12, 0)
    fresh = ranking.compute_weight(
        recent_views=0, total_views=0, created_at=now - timedelta(hours=1), now=now
    )
    old = ranking.compute_weight(
        recent_views=0, total_views=0, created_at=now - timedelta(days=28), now=now
    )
    # 半衰期 14 天：28 天前的书新鲜度只剩 1/4
    assert fresh == pytest.approx(ranking.FRESHNESS_WEIGHT, rel=0.01)
    assert old == pytest.approx(ranking.FRESHNESS_WEIGHT / 4, rel=0.01)
    assert fresh > old


def test_weight_counts_recent_views_more_than_historical_ones() -> None:
    now = datetime(2026, 5, 1, 12, 0)
    created = now - timedelta(days=30)
    recent = ranking.compute_weight(recent_views=10, total_views=10, created_at=created, now=now)
    historical = ranking.compute_weight(recent_views=0, total_views=10, created_at=created, now=now)
    assert recent > historical


def test_weight_never_negative_for_future_timestamps() -> None:
    now = datetime(2026, 5, 1, 12, 0)
    weight = ranking.compute_weight(
        recent_views=0, total_views=0, created_at=now + timedelta(days=2), now=now
    )
    assert weight == pytest.approx(ranking.FRESHNESS_WEIGHT)


# ---------------------------------------------------------------- 列表顺序


def test_hot_book_ranks_first(client, db) -> None:
    old = books_service.create_book(db, title="老手册")
    new = books_service.create_book(db, title="新手册")
    db.commit()
    _old_chapter, old_section = _section_of(db, old, title="老正文")
    # 两本都没有访问：创建更晚的排在前面
    rows, _ = books_service.list_books(db)
    assert [book.id for book in rows] == [new.id, old.id]

    for _ in range(10):
        ranking.add_view(db, old_section.id)
    db.commit()
    rows, _ = books_service.list_books(db)
    assert [book.id for book in rows] == [old.id, new.id]

    home = client.get("/")
    assert home.text.index("老手册") < home.text.index("新手册")


def test_order_stable_when_view_counts_unchanged(db) -> None:
    first = books_service.create_book(db, title="甲")
    second = books_service.create_book(db, title="乙")
    db.commit()
    now = utcnow()
    morning = ranking.rank_books(db, [first, second], now=now)
    later = ranking.rank_books(db, [first, second], now=now + timedelta(days=3))
    assert [book.id for book in morning] == [book.id for book in later]


def test_pagination_covers_every_book_once(db) -> None:
    created = [books_service.create_book(db, title=f"手册 {index}") for index in range(5)]
    db.commit()
    seen: list[int] = []
    for page in (1, 2, 3):
        rows, total = books_service.list_books(db, page=page, page_size=2)
        assert total == len(created)
        seen.extend(book.id for book in rows)
    assert len(seen) == len(set(seen)) == len(created)


# ---------------------------------------------------------------- 访问计数


def test_section_read_counts_toward_book(client, db, app) -> None:
    book = books_service.create_book(db, title="部署手册")
    chapters_service.create_chapter_with_section(
        db, book, title="上线", raw="# 上线\n\n步骤", slug_raw="release", status="published"
    )
    db.commit()

    assert client.get(f"/b/{book.slug}/release").status_code == 200
    assert _total_views(app) == 1
    with app.state.sessionmaker() as session:
        row = session.execute(select(SectionViewDaily)).scalars().one()
        assert row.section_id is not None


def test_book_page_visit_does_not_count_heat(client, db, app) -> None:
    """Book 目录页不计热度：只有真的读到某一节才算。"""
    book = books_service.create_book(db, title="目录页手册")
    _chapter_row, _section = _section_of(db, book, title="正文")
    db.commit()
    assert client.get(f"/b/{book.slug}").status_code == 200
    assert _total_views(app) == 0


def test_section_page_visit_counter_dedupes_same_visitor(client, db, app) -> None:
    book = books_service.create_book(db, title="运维手册")
    chapter, section = _section_of(db, book, title="正文")
    url = f"/b/{book.slug}/{chapter.slug}/{section.slug}"

    assert client.get(url).status_code == 200
    assert _total_views(app) == 1
    # 同一访客刷新不刷热度
    assert client.get(url).status_code == 200
    assert _total_views(app) == 1

    client.app.state.visit_deduper.clear()
    assert client.get(url).status_code == 200
    assert _total_views(app) == 2


def test_logged_in_visit_is_not_counted(admin, db, app) -> None:
    book = books_service.create_book(db, title="编辑自己的书")
    chapter, section = _section_of(db, book, title="正文")
    assert admin.get(f"/b/{book.slug}/{chapter.slug}/{section.slug}").status_code == 200
    assert _total_views(app) == 0


def test_visit_count_resets_per_day(db, app) -> None:
    book = books_service.create_book(db, title="按天统计")
    db.commit()
    _chapter_row, section = _section_of(db, book, title="正文")
    yesterday = utcnow() - timedelta(days=1)
    ranking.add_view(db, section.id, now=yesterday)
    ranking.add_view(db, section.id, now=yesterday)
    ranking.add_view(db, section.id)
    db.commit()

    stats = ranking.stats_of(db, book)
    assert stats.total_views == 3
    assert stats.recent_views == 3
    assert db.execute(select(func.count()).select_from(SectionViewDaily)).scalar_one() == 2

    # 窗口外的旧访问只计入累计值
    long_ago = utcnow() - timedelta(days=30)
    ranking.add_view(db, section.id, now=long_ago)
    db.commit()
    stats = ranking.stats_of(db, book)
    assert stats.total_views == 4
    assert stats.recent_views == 3


# ---------------------------------------------------------------- 管理端与 API


def test_admin_form_has_no_manual_weight(admin, db) -> None:
    book = books_service.create_book(db, title="无权重表单")
    db.commit()
    for path in ("/admin/books/new", f"/admin/books/{book.id}/edit"):
        html = admin.get(path).text
        assert 'name="sort_order"' not in html
        assert "排序权重" not in html
    detail = admin.get(f"/admin/books/{book.id}").text
    assert "热度权重" in detail
    assert "次访问" in detail
    # 管理端列表用「近 7 天访问」解释排序，而不是显示一个可编辑的权重
    assert "近 7 天访问" in admin.get("/admin").text


def test_api_book_payload_exposes_weight(client, db) -> None:
    book = books_service.create_book(db, title="接口手册")
    db.commit()
    _chapter_row, section = _section_of(db, book, title="正文")
    ranking.add_view(db, section.id)
    db.commit()

    item = client.get("/api/v1/books").json()["items"][0]
    assert "sort_order" not in item
    assert item["view_count"] == 1
    assert item["recent_view_count"] == 1
    assert item["weight"] > 0

    detail = client.get(f"/api/v1/books/{book.slug}").json()
    assert detail["weight"] == item["weight"]
    assert detail["view_count"] == 1


def test_api_book_list_is_ranked(client, db) -> None:
    old = books_service.create_book(db, title="冷门手册")
    old.created_at = utcnow() - timedelta(days=90)
    fresh = books_service.create_book(db, title="刚建的手册")
    db.commit()
    _chapter_row, old_section = _section_of(db, old, title="老正文")

    slugs = [item["slug"] for item in client.get("/api/v1/books").json()["items"]]
    assert slugs == [fresh.slug, old.slug]

    for _ in range(20):
        ranking.add_view(db, old_section.id)
    db.commit()
    slugs = [item["slug"] for item in client.get("/api/v1/books").json()["items"]]
    assert slugs == [old.slug, fresh.slug]
