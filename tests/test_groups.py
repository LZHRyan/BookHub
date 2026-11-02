"""章与节：结构约束、排序作用域、目录编号与对外契约。

（这个文件原来测「分卷」；分卷删除后，同一批用例迁到「章 → 节」结构上：
原来的“分卷装章节”对应“章装节”，其余结构约束逐条对应。）
"""

from __future__ import annotations

import pytest

from app.errors import NotFound, ValidationFailed
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import sections as sections_service

from .conftest import csrf_token

AUTH = {"Authorization": "Bearer bh_group_token_0123456789"}


def _book(db, *, fmt="markdown"):
    book = books_service.create_book(db, title="研发手册", fmt=fmt)
    db.commit()
    return book


# ------------------------------------------------------------------ 服务层


def test_chapter_has_no_content_or_versions(db, settings) -> None:
    """章只是容器：没有正文、没有格式、没有版本号。"""
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="部署与运维")
    db.commit()
    assert chapter.title == "部署与运维"
    assert chapter.status == "draft"
    for attribute in ("content_raw", "content_safe", "content_rendered", "word_count"):
        assert not hasattr(chapter, attribute), attribute
    assert not hasattr(chapter, "current_version_no")
    assert sections_service.list_sections(db, chapter) == []


def test_section_cannot_be_nested_and_chapter_is_not_a_section(db) -> None:
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="章 1")
    db.commit()
    section = sections_service.create_section(db, chapter, title="节 1", raw="# 1")
    db.commit()

    # 节只挂在章下：模型里没有 parent 概念
    assert not hasattr(section, "parent_id")
    assert section.chapter_id == chapter.id
    # 章 id 不是节：按章定位节会失败
    with pytest.raises(NotFound):
        sections_service.get_section(db, chapter, chapter.id + 1000)
    # 跨章移动节被显式拒绝
    other = chapters_service.create_chapter(db, book, title="章 2")
    db.commit()
    with pytest.raises(ValidationFailed):
        sections_service.move_to_chapter(db, section, other)


def test_section_must_belong_to_the_same_book(db) -> None:
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="章 1")
    db.commit()
    section = sections_service.create_section(db, chapter, title="节 1", raw="# 1")
    other_book = books_service.create_book(db, title="另一本")
    other_chapter = chapters_service.create_chapter(db, other_book, title="别处的章")
    db.commit()

    with pytest.raises(NotFound):
        sections_service.get_section(db, other_chapter, section.id)
    with pytest.raises(NotFound):
        sections_service.get_section(db, other_chapter, "no-such-section")


def test_tree_numbers_and_scope(db) -> None:
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="安装")
    db.commit()
    a = sections_service.create_section(db, chapter, title="准备", raw="# a")
    b = sections_service.create_section(db, chapter, title="执行", raw="# b")
    other = chapters_service.create_chapter_with_section(db, book, title="附录", raw="# c")[0]
    db.commit()

    rows = chapters_service.tree(db, book.id)
    assert [row["chapter"].title for row in rows] == ["安装", "附录"]
    assert [no for _section, no in rows[0]["sections"]] == ["1.1", "1.2"]
    assert rows[0]["sections"][0][0].id == a.id
    assert rows[0]["sections"][1][0].id == b.id
    assert [(section.id, no) for section, no in rows[1]["sections"]] == [
        (chapters_service.ordered_chapters(db, book.id)[1].sections[0].id, "2.1")
    ]
    assert other.id == rows[1]["chapter"].id

    # 章内移动不改动章的顺序
    sections_service.move_section(db, b, -1)
    db.commit()
    rows = chapters_service.tree(db, book.id)
    assert [section.id for section, _no in rows[0]["sections"]] == [b.id, a.id]
    assert [row["chapter"].id for row in rows] == [chapter.id, other.id]


def test_move_section_is_bounded_by_chapter(db) -> None:
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="章 A")
    db.commit()
    first = sections_service.create_section(db, chapter, title="一", raw="#1")
    second = sections_service.create_section(db, chapter, title="二", raw="#2")
    third = sections_service.create_section(db, chapter, title="三", raw="#3")
    db.commit()

    sections_service.move_section(db, third, -1)
    db.commit()
    assert [item.id for item in sections_service.ordered_sections(db, chapter.id)] == [
        first.id,
        third.id,
        second.id,
    ]
    # 已经在头/尾再移是空操作
    sections_service.move_section(db, first, -1)
    sections_service.move_section(db, second, 1)
    db.commit()
    assert [item.id for item in sections_service.ordered_sections(db, chapter.id)] == [
        first.id,
        third.id,
        second.id,
    ]
    assert [item.sort_order for item in sections_service.ordered_sections(db, chapter.id)] == [
        10,
        20,
        30,
    ]


def test_section_cannot_move_to_another_chapter(db) -> None:
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="章 A")
    other = chapters_service.create_chapter(db, book, title="章 B")
    db.commit()
    section = sections_service.create_section(db, chapter, title="一", raw="#1")
    db.commit()
    with pytest.raises(ValidationFailed):
        sections_service.move_to_chapter(db, section, other)


def test_delete_chapter_takes_its_sections_offline(db) -> None:
    """删章连带下架它的节：访客视角看不到，恢复章后节回到原样。"""
    book = _book(db)
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="章", raw="#x", status="published"
    )
    db.commit()
    assert len(chapters_service.published_chapters(db, book.id)) == 1

    chapters_service.soft_delete_chapter(db, chapter)
    db.commit()
    assert chapter.deleted_at is not None
    assert section.deleted_at is None
    assert chapters_service.published_chapters(db, book.id) == []
    with pytest.raises(NotFound):
        sections_service.find_section(db, book.slug, chapter.slug, section.slug)

    chapters_service.restore_chapter(db, chapter)
    db.commit()
    assert chapter.deleted_at is None
    assert len(sections_service.ordered_sections(db, chapter.id)) == 1
    found = sections_service.find_section(db, book.slug, chapter.slug, section.slug)
    assert found[2].id == section.id


def test_restore_chapter_keeps_sections_when_slug_taken(db) -> None:
    book = _book(db)
    chapter, _section = chapters_service.create_chapter_with_section(
        db, book, title="章", raw="#x", slug_raw="intro"
    )
    db.commit()
    chapters_service.soft_delete_chapter(db, chapter)
    replacement, _ = chapters_service.create_chapter_with_section(
        db, book, title="新章", raw="#y", slug_raw="intro"
    )
    db.commit()
    assert replacement.slug == "intro"

    chapters_service.restore_chapter(db, chapter)
    db.commit()
    assert chapter.slug == "intro-2"
    assert len(sections_service.ordered_sections(db, chapter.id)) == 1


def test_empty_chapter_is_excluded_from_search_and_sections(db) -> None:
    book = _book(db)
    chapters_service.create_chapter(db, book, title="唯一标题章", status="published")
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="章", raw="#x", status="published"
    )
    db.commit()
    published = chapters_service.published_chapters(db, book.id)
    assert [c.id for c in published] == [c.id for c in chapters_service.ordered_chapters(db, book.id)]
    flat = chapters_service.flat_published_sections(db, book.id)
    assert [item.id for _chapter, item in flat] == [section.id]
    # 没有节的章不产生任何索引行
    assert chapter.id is not None


# ------------------------------------------------------------------ 网页端


def test_admin_can_create_chapter_and_add_sections(admin, db) -> None:
    book = _book(db)
    token = csrf_token(admin, f"/admin/books/{book.id}/chapters/new")
    created = admin.post(
        f"/admin/books/{book.id}/chapters/new",
        data={
            "csrf_token": token,
            "title": "部署与运维",
            "slug": "ops",
            "content": "# 步骤",
            "status": "published",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    chapter = chapters_service.ordered_chapters(db, book.id)[0]
    assert chapter.title == "部署与运维"

    editor = admin.get(f"/admin/books/{book.id}/chapters/{chapter.id}").text
    assert "新增节" in editor
    assert "归属分卷" not in editor

    section_token = csrf_token(admin, f"/admin/books/{book.id}/chapters/{chapter.id}/sections/new")
    admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/sections/new",
        data={
            "csrf_token": section_token,
            "title": "首次部署",
            "content": "# 首次",
            "format": "markdown",
        },
        follow_redirects=False,
    )
    db.expire_all()
    sections = sections_service.ordered_sections(db, chapter.id)
    assert [item.title for item in sections] == ["部署与运维", "首次部署"]


def test_admin_book_page_renders_chapter_table(admin, db) -> None:
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="章标题甲")
    db.commit()
    sections_service.create_section(db, chapter, title="节甲", raw="#x")
    sections_service.create_section(db, chapter, title="节乙", raw="#y")
    db.commit()
    html = admin.get(f"/admin/books/{book.id}").text
    assert "章标题甲" in html
    assert "节数" in html
    assert "data-sortable" in html
    assert "新建分卷" not in html


def test_admin_delete_chapter_is_allowed_now(admin, db) -> None:
    """章可以直接删（连同它的节一起下架），不再有“非空不能删”的限制。"""
    book = _book(db)
    chapter, _section = chapters_service.create_chapter_with_section(db, book, title="待删章", raw="#x")
    db.commit()
    token = csrf_token(admin, f"/admin/books/{book.id}")
    response = admin.post(
        f"/admin/books/{book.id}/chapters/{chapter.id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db.expire_all()
    assert chapter.deleted_at is not None
    assert "待删章" in admin.get("/admin/trash").text


# ------------------------------------------------------------------ 读者端


def test_public_book_page_renders_two_level_directory(client, db) -> None:
    book = _book(db)
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="安装指南", raw="#a", status="published", section_slug="intro"
    )
    multi = chapters_service.create_chapter(db, book, title="多节章", status="published")
    db.commit()
    sections_service.create_section(db, multi, title="环境准备", raw="#b", slug_raw="env")
    sections_service.create_section(db, multi, title="开机", raw="#c", slug_raw="boot")
    db.commit()

    html = client.get(f"/b/{book.slug}").text
    assert "安装指南" in html
    assert "多节章" in html
    assert "2.1" in html
    assert "环境准备" in html
    assert "开机" in html


def test_empty_chapter_page_shows_hint(client, db) -> None:
    """章页在没有节时给提示而不是 404（旧的分卷链接 302 的行为不再存在）。"""
    book = _book(db)
    chapter = chapters_service.create_chapter(db, book, title="安装指南", status="published")
    db.commit()
    response = client.get(f"/b/{book.slug}/{chapter.slug}")
    assert response.status_code == 200
    assert "这一章还没有节" in response.text


def test_section_page_breadcrumb_shows_chapter(client, db) -> None:
    book = _book(db)
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="安装指南", raw="#a", status="published"
    )
    db.commit()
    html = client.get(f"/b/{book.slug}/{chapter.slug}/{section.slug}").text
    assert f"/b/{book.slug}/{chapter.slug}" in html
    assert "安装指南" in html


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


def _create_book(client, title="API 分卷手册") -> dict:
    response = client.post(
        "/api/v1/admin/books",
        json={"title": title, "format": "markdown", "group": "default"},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_api_section_lifecycle(api) -> None:
    client = api
    book = _create_book(client)
    chapter = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "首次部署", "content": "# 步骤"},
        headers=AUTH,
    )
    assert chapter.status_code == 201, chapter.text
    chapter_body = chapter.json()
    assert len(chapter_body["sections"]) == 1

    created = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter_body['slug']}/sections",
        json={"title": "回滚方案", "content": "# 回滚", "slug": "rollback"},
        headers=AUTH,
    )
    assert created.status_code == 201, created.text
    section = created.json()
    assert section["slug"] == "rollback"

    listed = client.get(
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter_body['slug']}/sections",
        headers=AUTH,
    )
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 2

    replaced = client.patch(
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter_body['slug']}"
        f"/sections/{section['slug']}",
        json={"title": "回滚与恢复"},
        headers=AUTH,
    )
    assert replaced.status_code == 200
    assert replaced.json()["title"] == "回滚与恢复"

    versions = client.get(
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter_body['slug']}"
        f"/sections/{section['slug']}/versions",
        headers=AUTH,
    )
    assert versions.status_code == 200
    assert versions.json()["items"][0]["version_no"] == 2


def test_api_section_404_for_unknown_chapter(api) -> None:
    client = api
    book = _create_book(client)
    bad = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters/no-such-chapter/sections",
        json={"title": "挂错地方", "content": "# y"},
        headers=AUTH,
    )
    assert bad.status_code == 404
    assert "章节不存在" in bad.json()["error"]["message"]


def test_api_book_detail_includes_sections(api) -> None:
    client = api
    book = _create_book(client)
    chapter = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "前言", "content": "# 前言", "status": "published"},
        headers=AUTH,
    ).json()
    client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter['slug']}/sections",
        json={"title": "致谢", "content": "# 致谢", "slug": "thanks"},
        headers=AUTH,
    )
    detail = client.get(f"/api/v1/books/{book['slug']}").json()
    assert [item["title"] for item in detail["chapters"]] == ["前言"]
    section_titles = [item["title"] for item in detail["chapters"][0]["sections"]]
    assert section_titles == ["前言", "致谢"]

    # 多节章没有唯一的正文出口，api 的 section 字段不出现
    chapter_api = client.get(f"/api/v1/books/{book['slug']}/chapters/{chapter['slug']}").json()
    assert "section" not in chapter_api
    single = client.get(
        f"/api/v1/books/{book['slug']}/chapters/{chapter['slug']}?section=thanks"
    ).json()
    assert single["title"] == "致谢"


def test_meta_lists_sections_capability(api) -> None:
    body = api.get("/api/v1/admin/meta", headers=AUTH).json()
    assert "sections" in body["capabilities"]
    assert "groups" not in body["capabilities"]
