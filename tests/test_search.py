"""检索：切分、范围、同步与边界。"""

from __future__ import annotations

from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import sections as sections_service
from app.services.search import build_match_query, make_snippet, needs_like_fallback, tokenize
from app.services.search import search as run_search


def test_tokenize_chinese_bigrams() -> None:
    assert tokenize("知识库") == ["知识", "识库"]
    assert tokenize("知识") == ["知识"]
    assert tokenize("知") == ["知"]


def test_tokenize_mixed() -> None:
    tokens = tokenize("部署 Docker-Compose 指南")
    assert "部署" in tokens
    assert "docker-compose" in tokens
    assert all(token == token.lower() for token in tokens)


def test_match_query_quoted() -> None:
    query = build_match_query("部署 指南")
    assert query is not None
    assert query.startswith('"')
    assert " AND " in query


def test_single_char_needs_fallback() -> None:
    assert needs_like_fallback("知") is True
    assert needs_like_fallback("知识") is False
    assert needs_like_fallback("guide") is False


def test_snippet_highlights_only_query() -> None:
    snippet = make_snippet("这是关于部署的说明，部署很重要。", "部署")
    assert "<mark>部署</mark>" in snippet
    assert "<mark>说明</mark>" not in snippet
    assert "<script>" not in make_snippet("<script>alert(1)</script> 部署", "部署")


def _seed(db):
    book = books_service.create_book(db, title="研发手册")
    published = chapters_service.create_chapter_with_section(
        db, book, title="部署说明", raw="# 部署\n\n知识库部署流程与回滚", slug_raw="deploy", status="published"
    )
    draft = chapters_service.create_chapter_with_section(
        db, book, title="草稿", raw="知识库草稿内容", slug_raw="draft"
    )
    hidden = books_service.create_book(db, title="隐藏", visibility="unlisted")
    chapters_service.create_chapter_with_section(
        db, hidden, title="隐藏章节", raw="知识库隐藏内容", slug_raw="secret", status="published"
    )
    db.commit()
    return {"book": book, "published": published[0], "section": published[1], "draft": draft[0], "hidden": hidden}


def test_search_two_char_chinese(db) -> None:
    _seed(db)
    items, total = run_search(db, query="知识")
    assert total == 1
    assert items[0]["chapter_slug"] == "deploy"
    assert items[0]["section_id"] > 0


def test_search_excludes_draft_and_unlisted(db) -> None:
    _seed(db)
    _, total = run_search(db, query="知识库")
    assert total == 1


def test_search_english_case_insensitive(db) -> None:
    book = books_service.create_book(db, title="English")
    chapters_service.create_chapter_with_section(
        db, book, title="Guide", raw="BookHub deployment", slug_raw="guide", status="published"
    )
    db.commit()
    for query in ("bookhub", "BOOKHUB", "BookHub"):
        _, total = run_search(db, query=query)
        assert total == 1


def test_search_syncs_after_replace(db) -> None:
    seeded = _seed(db)
    sections_service.replace_content(db, seeded["section"], raw="# 部署\n\n完全不同的术语")
    db.commit()
    assert run_search(db, query="回滚")[1] == 0
    assert run_search(db, query="术语")[1] == 1


def test_search_empty_query(db) -> None:
    _seed(db)
    assert run_search(db, query="   ") == ([], 0)


def test_search_single_char(db) -> None:
    _seed(db)
    items, total = run_search(db, query="知")
    assert total >= 1
    assert items[0]["exact"] is True


def test_search_book_filter(db) -> None:
    seeded = _seed(db)
    _, total = run_search(db, query="部署", book_id=seeded["book"].id)
    assert total == 1
    _, other_total = run_search(db, query="部署", book_id=seeded["hidden"].id)
    assert other_total == 0


def test_search_after_delete(db) -> None:
    seeded = _seed(db)
    chapters_service.soft_delete_chapter(db, seeded["published"])
    db.commit()
    assert run_search(db, query="部署")[1] == 0


def test_search_after_unpublish(db) -> None:
    seeded = _seed(db)
    chapters_service.set_status(db, seeded["published"], "draft")
    db.commit()
    assert run_search(db, query="部署")[1] == 0
