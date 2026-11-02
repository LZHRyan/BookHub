"""Book 分组：服务的增删改查与排序、Book 归属、网页端分区与管理 API 契约。

契约见 openspec/changes/add-book-groups/specs/。
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app.errors import NotFound, ValidationFailed
from app.main import create_app
from app.services import book_groups, ranking
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import sections as sections_service

from .conftest import csrf_token, make_settings, run_migrations

API_TOKEN = "bh_bookgroups_token_0123456789"
AUTH = {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.fixture()
def api(tmp_path):
    """管理 API 用的客户端：独立库 + 一个 admin 作用域的 bootstrap token。"""
    settings = make_settings(tmp_path, admin_api_token=API_TOKEN)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def _group(db, *, title: str, slug: str = ""):
    group = book_groups.create(db, title=title, slug_raw=slug)
    db.commit()
    return group


def _book(db, *, title: str, group: str | None = None):
    book = books_service.create_book(db, title=title, group=group)
    db.commit()
    return book


def _books(db, **kwargs) -> list:
    """list_books 返回 (rows, total)，测试里只关心 rows。"""
    rows, _total = books_service.list_books(db, **kwargs)
    return rows


# ------------------------------------------------------------------ 服务层：默认分组与创建


def test_ensure_default_is_idempotent(db) -> None:
    first = book_groups.ensure_default(db)
    second = book_groups.ensure_default(db)
    db.commit()

    assert first.id == second.id
    assert first.slug == book_groups.DEFAULT_SLUG
    assert first.title == book_groups.DEFAULT_TITLE
    # 迁移已建好默认分组，运行时的兜底只应返回它，不能再插一条
    defaults = [item for item in book_groups.list_groups(db) if item.slug == "default"]
    assert len(defaults) == 1


def test_create_requires_title_and_appends_sort_order(db) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        book_groups.create(db, title="   ")
    assert "标题" in str(excinfo.value)

    default = book_groups.ensure_default(db)
    first = _group(db, title="基础设施", slug="infra")
    second = _group(db, title="规范制度", slug="policy")

    assert first.title == "基础设施"
    assert first.sort_order == default.sort_order + 10
    assert second.sort_order == first.sort_order + 10
    assert [item.id for item in book_groups.list_groups(db)] == [
        default.id,
        first.id,
        second.id,
    ]


def test_create_dedupes_slug(db) -> None:
    first = _group(db, title="基础设施", slug="infra")
    duplicated = _group(db, title="基础设施（副本）", slug="infra")
    third = _group(db, title="基础设施（三）", slug="infra")

    assert first.slug == "infra"
    assert duplicated.slug == "infra-2"
    assert third.slug == "infra-3"
    assert [item.title for item in book_groups.list_groups(db)][1:] == [
        "基础设施",
        "基础设施（副本）",
        "基础设施（三）",
    ]


# ------------------------------------------------------------------ 服务层：列表、排序与修改


def test_list_groups_sorted_and_move_rewrites_order(db) -> None:
    default = book_groups.ensure_default(db)
    first = _group(db, title="第一组", slug="first")
    second = _group(db, title="第二组", slug="second")

    assert [item.slug for item in book_groups.list_groups(db)] == [
        "default",
        "first",
        "second",
    ]

    book_groups.move(db, second, -1)
    db.commit()
    assert [item.slug for item in book_groups.list_groups(db)] == [
        "default",
        "second",
        "first",
    ]
    # 位置序号被整体重写成 10/20/30，Book 数据不受影响
    assert [item.sort_order for item in book_groups.list_groups(db)] == [10, 20, 30]
    by_slug = {item.slug: item for item in book_groups.list_groups(db)}
    assert by_slug["default"].sort_order == 10
    assert by_slug["second"].sort_order == 20
    assert by_slug["first"].sort_order == 30
    assert {default.id, first.id, second.id} == {item.id for item in by_slug.values()}

    # 已在首位时上移是空操作
    book_groups.move(db, default, -1)
    db.commit()
    assert [item.slug for item in book_groups.list_groups(db)] == [
        "default",
        "second",
        "first",
    ]

    book_groups.move(db, first, -1)
    db.commit()
    assert [item.slug for item in book_groups.list_groups(db)] == [
        "default",
        "first",
        "second",
    ]
    # 已在末位时下移也是空操作
    book_groups.move(db, second, 1)
    db.commit()
    assert [item.slug for item in book_groups.list_groups(db)][-1] == "second"


def test_update_changes_all_editable_fields(db) -> None:
    group = _group(db, title="旧标题", slug="old-slug")
    book_groups.update(
        db,
        group,
        title="新标题",
        slug_raw="new-slug",
        description="机房、网络与发布流程",
        icon="🏗",
    )
    db.commit()

    refreshed = book_groups.get_group(db, "new-slug")
    assert refreshed.id == group.id
    assert refreshed.title == "新标题"
    assert refreshed.description == "机房、网络与发布流程"
    assert refreshed.icon == "🏗"
    with pytest.raises(NotFound):
        book_groups.get_group(db, "old-slug")


# ------------------------------------------------------------------ 服务层：删除约束


def test_delete_refuses_non_empty_group(db) -> None:
    group = _group(db, title="非空组", slug="busy")
    _book(db, title="运维手册", group="busy")

    with pytest.raises(ValidationFailed) as excinfo:
        book_groups.delete(db, group)
    message = str(excinfo.value)
    assert "还有 1 个 Book" in message
    # 组与 Book 都不变
    assert book_groups.get_group(db, "busy").id == group.id
    assert len(_books(db, visibility=None)) == 1


def test_delete_counts_soft_deleted_books(db) -> None:
    """回收站里的 Book 仍持有 group_id 外键，必须继续拦住删组。"""
    group = _group(db, title="待清理组", slug="trash")
    book = _book(db, title="旧手册", group="trash")
    books_service.soft_delete_book(db, book)
    db.commit()

    with pytest.raises(ValidationFailed) as excinfo:
        book_groups.delete(db, group)
    message = str(excinfo.value)
    assert "含回收站" in message
    assert "1 个 Book" in message
    assert book_groups.get_group(db, "trash").id == group.id


def test_delete_empty_group_removes_section(db) -> None:
    group = _group(db, title="空组", slug="empty-group")
    assert book_groups.count_books(db, group.id) == 0

    book_groups.delete(db, group)
    db.commit()

    assert [item.slug for item in book_groups.list_groups(db)] == ["default"]
    with pytest.raises(NotFound):
        book_groups.get_group(db, "empty-group")


def test_delete_refuses_default_group(db) -> None:
    """默认分组随系统创建：哪怕只剩它一个，也不能删。"""
    only = book_groups.ensure_default(db)
    db.commit()
    assert [item.id for item in book_groups.list_groups(db)] == [only.id]

    with pytest.raises(ValidationFailed) as excinfo:
        book_groups.delete(db, only)
    assert "默认分组" in str(excinfo.value)
    assert book_groups.get_group(db, "default").id == only.id


def test_default_group_survives_even_with_other_groups(db) -> None:
    """有别的组时默认分组依然不能删；其它空组照常可删。"""
    book_groups.ensure_default(db)
    other = _group(db, title="另一组", slug="other")
    db.commit()
    default = book_groups.get_group(db, "default")

    with pytest.raises(ValidationFailed) as excinfo:
        book_groups.delete(db, default)
    assert "默认分组" in str(excinfo.value)

    book_groups.delete(db, other)
    db.commit()
    assert [item.slug for item in book_groups.list_groups(db)] == ["default"]


def test_default_group_slug_is_immutable_but_title_can_change(db) -> None:
    """默认分组靠 slug=default 识别：标识不能改，标题/简介/图标可以改。"""
    default = book_groups.ensure_default(db)
    db.commit()

    with pytest.raises(ValidationFailed) as excinfo:
        book_groups.update(db, default, slug_raw="misc")
    assert "访问标识" in str(excinfo.value)
    db.rollback()

    book_groups.update(db, default, title="未分组", description="兜底归属")
    db.commit()
    refreshed = book_groups.get_group(db, "default")
    assert refreshed.title == "未分组"
    assert refreshed.description == "兜底归属"
    assert refreshed.slug == book_groups.DEFAULT_SLUG


# ------------------------------------------------------------------ 服务层：首页分区


def test_overview_sections_follow_group_order(db) -> None:
    infra = _group(db, title="基础设施", slug="infra")
    policy = _group(db, title="规范制度", slug="policy")
    _group(db, title="空组", slug="empty-group")
    infra_book = _book(db, title="部署手册", group="infra")
    policy_book = _book(db, title="制度汇编", group="policy")

    sections = book_groups.overview(db, visibility="public")

    # 组顺序决定分区顺序；没有 Book 的组不出现
    assert [section["group"].slug for section in sections] == ["infra", "policy"]
    assert [section["group"].id for section in sections] == [infra.id, policy.id]
    assert [[book.id for book in section["books"]] for section in sections] == [
        [infra_book.id],
        [policy_book.id],
    ]
    assert [section["total"] for section in sections] == [1, 1]


def test_overview_orders_books_by_pinned_then_heat(db) -> None:
    _group(db, title="基础设施", slug="infra")
    cold = _book(db, title="冷门手册", group="infra")
    hot = _book(db, title="热门手册", group="infra")
    _cold_chapter, cold_section = chapters_service.create_chapter_with_section(
        db, cold, title="正文", raw="# 冷门"
    )
    for _ in range(3):
        ranking.add_view(db, cold_section.id)
    db.commit()

    section = book_groups.overview(db, visibility="public")[0]
    assert [book.id for book in section["books"]] == [cold.id, hot.id]

    # 置顶在组内同样优先，压过热度
    books_service.update_book(db, hot, pinned=True)
    db.commit()
    section = book_groups.overview(db, visibility="public")[0]
    assert [book.id for book in section["books"]] == [hot.id, cold.id]


def test_overview_group_ref_only_returns_that_group(db) -> None:
    _group(db, title="基础设施", slug="infra")
    _group(db, title="规范制度", slug="policy")
    infra_book = _book(db, title="部署手册", group="infra")
    _book(db, title="制度汇编", group="policy")

    sections = book_groups.overview(db, visibility="public", group_ref="policy")

    assert [section["group"].slug for section in sections] == ["policy"]
    assert infra_book.id not in [book.id for book in sections[0]["books"]]


# ------------------------------------------------------------------ Book 归属


def test_create_book_uses_group_or_default(db) -> None:
    infra = _group(db, title="基础设施", slug="infra")

    explicit = _book(db, title="部署手册", group="infra")
    assert explicit.group_id == infra.id

    fallback = _book(db, title="随手记")
    default = book_groups.ensure_default(db)
    db.commit()
    assert fallback.group_id == default.id
    assert [book.id for book in _books(db, group="default")] == [fallback.id]


def test_update_book_group_moves_book_and_keeps_sections(db) -> None:
    old = _group(db, title="旧组", slug="old-group")
    new = _group(db, title="新组", slug="new-group")
    book = _book(db, title="迁移手册", group="old-group")
    chapter, section = chapters_service.create_chapter_with_section(
        db, book, title="第一章", raw="# 第一章"
    )
    db.commit()
    chapter_ids = [item.id for item in chapters_service.ordered_chapters(db, book.id)]
    version_count = len(sections_service.list_versions(db, section))
    assert chapter_ids == [chapter.id]
    assert version_count == 1

    books_service.update_book(db, book, group="new-group")
    db.commit()

    assert book.group_id == new.id
    assert book.group_id != old.id
    assert [item.id for item in _books(db, visibility=None, group="new-group")] == [
        book.id
    ]
    assert _books(db, visibility=None, group="old-group") == []
    sections = book_groups.overview(db, visibility="public")
    assert [section["group"].slug for section in sections] == ["new-group"]
    assert [item.id for item in sections[0]["books"]] == [book.id]
    # 章节与节版本不受归属变化影响
    assert [item.id for item in chapters_service.ordered_chapters(db, book.id)] == chapter_ids
    assert len(sections_service.list_versions(db, section)) == version_count


# ------------------------------------------------------------------ 网页端：组管理


def test_admin_groups_page_shows_titles_and_counts(admin, db) -> None:
    group = _group(db, title="基础设施甲", slug="infra-a")
    _book(db, title="运维手册甲", group="infra-a")

    response = admin.get("/admin/groups")

    assert response.status_code == 200
    html = response.text
    assert group.title in html
    assert "默认分组" in html
    assert "?group=infra-a\">1</a>" in html
    assert "共 2 个分组" in html


def test_admin_default_group_has_no_delete_entry(admin, db) -> None:
    """默认分组在列表与编辑页都没有删除入口，直接 POST 也会被拒。"""
    default = book_groups.ensure_default(db)
    db.commit()

    listing = admin.get("/admin/groups").text
    assert "系统内置" in listing
    assert f"/admin/groups/{default.id}/delete" not in listing

    form = admin.get(f"/admin/groups/{default.id}/edit").text
    assert "readonly" in form
    assert "固定为" in form
    assert f"/admin/groups/{default.id}/delete" not in form

    token = csrf_token(admin, "/admin/groups")
    blocked = admin.post(
        f"/admin/groups/{default.id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert "error=" in blocked.headers["location"]
    assert "默认分组" in unquote(blocked.headers["location"])
    db.expire_all()
    assert book_groups.get_group(db, "default").id == default.id

    # 标题仍可改：保存后 slug 还是 default
    token = csrf_token(admin, f"/admin/groups/{default.id}/edit")
    saved = admin.post(
        f"/admin/groups/{default.id}/edit",
        data={"csrf_token": token, "title": "未分组", "slug": "default", "description": ""},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert "error" not in saved.headers["location"]
    db.expire_all()
    assert book_groups.get_group(db, "default").title == "未分组"


def test_admin_group_create_then_blocked_delete(admin, db) -> None:
    token = csrf_token(admin, "/admin/groups")
    created = admin.post(
        "/admin/groups/new",
        data={
            "csrf_token": token,
            "title": "网络组乙",
            "slug": "network-b",
            "description": "网络相关",
            "icon": "🌐",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert "error" not in created.headers["location"]

    db.expire_all()
    group = book_groups.get_group(db, "network-b")
    assert group.title == "网络组乙"
    assert "网络组乙" in admin.get("/admin/groups").text

    _book(db, title="网络手册乙", group="network-b")

    token = csrf_token(admin, "/admin/groups")
    blocked = admin.post(
        f"/admin/groups/{group.id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    location = blocked.headers["location"]
    assert "error=" in location
    assert "Book" in unquote(location)
    assert "Book" in admin.get(location).text

    db.expire_all()
    assert book_groups.get_group(db, "network-b").id == group.id


def test_admin_group_move_reorders(admin, db) -> None:
    first = _group(db, title="第一组", slug="first-web")
    second = _group(db, title="第二组", slug="second-web")

    token = csrf_token(admin, "/admin/groups")
    moved = admin.post(
        f"/admin/groups/{second.id}/move",
        data={"csrf_token": token, "direction": -1},
        follow_redirects=False,
    )

    assert moved.status_code == 303
    db.expire_all()
    assert [item.slug for item in book_groups.list_groups(db)] == [
        "default",
        "second-web",
        "first-web",
    ]
    assert book_groups.get_group(db, "first-web").id == first.id


def test_admin_book_list_filters_by_group(admin, db) -> None:
    _group(db, title="基础设施丙", slug="infra-c")
    _group(db, title="规范制度丙", slug="policy-c")
    _book(db, title="部署手册丙", group="infra-c")
    _book(db, title="制度汇编丙", group="policy-c")

    everything = admin.get("/admin").text
    assert "部署手册丙" in everything
    assert "制度汇编丙" in everything

    filtered = admin.get("/admin?group=infra-c").text
    assert "部署手册丙" in filtered
    assert "制度汇编丙" not in filtered


# ------------------------------------------------------------------ 网页端：Book 表单与读者端


def test_admin_book_form_requires_group(admin, db) -> None:
    group = _group(db, title="运维组丁", slug="ops-d")

    form = admin.get("/admin/books/new").text
    assert 'name="group"' in form
    assert "请选择分组" in form
    assert group.title in form

    token = csrf_token(admin, "/admin/books/new")
    rejected = admin.post(
        "/admin/books/new",
        data={"csrf_token": token, "title": "缺组手册丁", "group": ""},
        follow_redirects=False,
    )
    assert rejected.status_code == 400
    assert "必须选择分组" in rejected.text
    db.expire_all()
    assert _books(db, visibility=None) == []

    accepted = admin.post(
        "/admin/books/new",
        data={
            "csrf_token": token,
            "title": "运维手册丁",
            "group": str(group.id),
            "format": "markdown",
        },
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    db.expire_all()
    books = _books(db, visibility=None)
    assert [book.title for book in books] == ["运维手册丁"]
    assert books[0].group_id == group.id


def test_public_index_sections_and_group_filter(client, db) -> None:
    _group(db, title="基础设施戊", slug="infra-e")
    _group(db, title="规范制度戊", slug="policy-e")
    _book(db, title="部署手册戊", group="infra-e")
    _book(db, title="制度汇编戊", group="policy-e")

    html = client.get("/").text
    assert "基础设施戊" in html
    assert "规范制度戊" in html
    blocks = html.split('class="group-section"')
    # 两个组 -> 两段分区（空着的默认分组不渲染）
    assert len(blocks) == 3
    assert "部署手册戊" in blocks[1]
    assert "制度汇编戊" not in blocks[1]
    assert "制度汇编戊" in blocks[2]
    assert "部署手册戊" not in blocks[2]

    filtered = client.get("/?group=infra-e").text
    assert "查看全部分组" in filtered
    assert "部署手册戊" in filtered
    assert "制度汇编戊" not in filtered


def test_public_book_page_breadcrumb_shows_group(client, db) -> None:
    _group(db, title="运维手册组己", slug="ops-f")
    book = _book(db, title="面包屑手册己", group="ops-f")

    response = client.get(f"/b/{book.slug}")

    assert response.status_code == 200
    html = response.text
    assert 'class="breadcrumb"' in html
    assert "运维手册组己" in html
    assert "?group=ops-f" in html


# ------------------------------------------------------------------ 管理 API


def test_api_group_lifecycle(api) -> None:
    created = api.post(
        "/api/v1/admin/groups",
        json={"title": "基础设施", "slug": "infra", "description": "机房与网络", "icon": "🏗"},
        headers=AUTH,
    )
    assert created.status_code == 201, created.text
    group = created.json()
    assert (group["slug"], group["title"], group["book_count"]) == ("infra", "基础设施", 0)
    assert group["description"] == "机房与网络"
    assert group["icon"] == "🏗"

    listed = api.get("/api/v1/admin/groups", headers=AUTH)
    assert listed.status_code == 200
    assert [item["slug"] for item in listed.json()["items"]] == ["default", "infra"]
    assert listed.json()["items"][-1]["sort_order"] > listed.json()["items"][0]["sort_order"]

    patched = api.patch(
        "/api/v1/admin/groups/infra", json={"title": "基础设施与网络"}, headers=AUTH
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "基础设施与网络"

    moved = api.post("/api/v1/admin/groups/infra/move", json={"direction": -1}, headers=AUTH)
    assert moved.status_code == 200, moved.text
    assert [item["slug"] for item in moved.json()["items"]] == ["infra", "default"]

    deleted = api.delete("/api/v1/admin/groups/infra", headers=AUTH)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert [item["slug"] for item in api.get("/api/v1/admin/groups", headers=AUTH).json()["items"]] == [
        "default"
    ]


def test_api_delete_non_empty_group_rejected(api) -> None:
    assert (
        api.post("/api/v1/admin/groups", json={"title": "有书组", "slug": "busy"}, headers=AUTH).status_code
        == 201
    )
    book = api.post("/api/v1/admin/books", json={"title": "手册", "group": "busy"}, headers=AUTH)
    assert book.status_code == 201, book.text

    blocked = api.delete("/api/v1/admin/groups/busy", headers=AUTH)

    assert blocked.status_code == 400
    assert "还有" in blocked.json()["error"]["message"]
    counts = {
        item["slug"]: item["book_count"]
        for item in api.get("/api/v1/admin/groups", headers=AUTH).json()["items"]
    }
    assert counts["busy"] == 1


def test_api_default_group_cannot_be_deleted(api) -> None:
    items = api.get("/api/v1/admin/groups", headers=AUTH).json()["items"]
    assert [item["slug"] for item in items] == ["default"]
    assert items[0]["is_default"] is True

    blocked = api.delete("/api/v1/admin/groups/default", headers=AUTH)

    assert blocked.status_code == 400
    assert "默认分组" in blocked.json()["error"]["message"]
    assert api.get("/api/v1/admin/groups", headers=AUTH).json()["items"][0]["slug"] == "default"


def test_api_default_group_slug_is_immutable(api) -> None:
    blocked = api.patch("/api/v1/admin/groups/default", json={"slug": "misc"}, headers=AUTH)

    assert blocked.status_code == 400
    assert "访问标识" in blocked.json()["error"]["message"]
    items = api.get("/api/v1/admin/groups", headers=AUTH).json()["items"]
    assert [item["slug"] for item in items] == ["default"]

    # 标题/简介仍可改，且 is_default 不因改名而丢失
    renamed = api.patch("/api/v1/admin/groups/default", json={"title": "未分组"}, headers=AUTH)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "未分组"
    assert renamed.json()["is_default"] is True


def test_api_create_book_requires_existing_group(api) -> None:
    missing = api.post("/api/v1/admin/books", json={"title": "没组手册"}, headers=AUTH)
    assert missing.status_code == 400
    assert "分组" in missing.json()["error"]["message"]

    unknown = api.post(
        "/api/v1/admin/books", json={"title": "错组手册", "group": "no-such-group"}, headers=AUTH
    )
    assert unknown.status_code == 404

    assert api.get("/api/v1/admin/books", headers=AUTH).json()["total"] == 0


def test_api_book_payload_and_public_filter_carry_group(api) -> None:
    assert (
        api.post("/api/v1/admin/groups", json={"title": "规范制度", "slug": "policy"}, headers=AUTH).status_code
        == 201
    )
    in_policy = api.post("/api/v1/admin/books", json={"title": "制度汇编", "group": "policy"}, headers=AUTH)
    assert in_policy.status_code == 201, in_policy.text
    assert in_policy.json()["group"]["slug"] == "policy"
    assert in_policy.json()["group"]["title"] == "规范制度"

    in_default = api.post("/api/v1/admin/books", json={"title": "杂项手册", "group": "default"}, headers=AUTH)
    assert in_default.status_code == 201, in_default.text

    managed = api.get("/api/v1/admin/books", headers=AUTH).json()["items"]
    assert {item["title"]: item["group"]["slug"] for item in managed} == {
        "制度汇编": "policy",
        "杂项手册": "default",
    }

    public = api.get("/api/v1/books").json()
    assert {item["group"]["slug"] for item in public["items"]} == {"policy", "default"}

    filtered = api.get("/api/v1/books?group=policy")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert [item["title"] for item in filtered.json()["items"]] == ["制度汇编"]

    assert api.get("/api/v1/books?group=no-such-group").status_code == 404
