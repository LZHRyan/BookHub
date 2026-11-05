"""治理：Token 的 Book 范围、审计导出与保留清理。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.errors import ValidationFailed
from app.models import ApiToken, AuditLog, utcnow
from app.services import audit as audit_service
from app.services import books as books_service
from app.services import tokens as token_service

BOOTSTRAP = "bh_gov_bootstrap_token_0123456789"
AUTH = {"Authorization": f"Bearer {BOOTSTRAP}"}


def _book(db, title="治理手册"):
    book = books_service.create_book(db, title=title, fmt="markdown")
    db.commit()
    return book


def _old_audit(db, days_ago: int, action: str = "chapter.create") -> AuditLog:
    entry = AuditLog(
        actor_name="api:old",
        action=action,
        target_type="chapter",
        target_id=1,
        target_label="旧记录",
        detail="{}",
        created_at=utcnow() - timedelta(days=days_ago),
    )
    db.add(entry)
    db.commit()
    return entry


# ------------------------------------------------------------------ 服务层


def test_token_book_scope_roundtrip(db) -> None:
    token, _raw = token_service.issue_token(db, name="scoped", scopes=["write"], book_ids=[2, 1])
    db.commit()
    assert token_service.book_scope_of(token) == [1, 2]
    assert token_service.describe(token)["book_ids"] == [1, 2]


def test_token_book_scope_empty_means_all(db) -> None:
    token, _raw = token_service.issue_token(db, name="all", scopes=["read"])
    db.commit()
    assert token_service.book_scope_of(token) == []


def test_audit_export_csv_has_bom_and_header(db) -> None:
    _old_audit(db, 1, action="book.update")
    rows = audit_service.query_rows(db, limit=10)
    text = audit_service.export_csv(rows)
    assert text.startswith("\ufeff")
    assert text.splitlines()[0].lstrip("\ufeff").startswith("created_at,actor,action")
    assert "book.update" in text


def test_audit_query_filters(db) -> None:
    _old_audit(db, 1, action="chapter.create")
    _old_audit(db, 2, action="book.delete")
    assert len(audit_service.query_rows(db, action="chapter", limit=10)) == 1
    assert len(audit_service.query_rows(db, action="book.delete", limit=10)) == 1
    assert audit_service.count_rows(db) == 2


def test_audit_cleanup_respects_retention(db) -> None:
    _old_audit(db, 400)
    _old_audit(db, 10)
    result = audit_service.cleanup(db, 180)
    db.commit()
    assert result["deleted"] == 1
    assert audit_service.count_rows(db) == 1


def test_audit_cleanup_disabled(db) -> None:
    _old_audit(db, 400)
    result = audit_service.cleanup(db, 0)
    assert result["deleted"] == 0
    assert audit_service.count_rows(db) == 1


# ------------------------------------------------------------------ 网页端


def test_token_page_renders_scope_controls(admin, db) -> None:
    _book(db, title="范围测试书")
    html = admin.get("/admin/tokens").text
    assert 'name="book_ids"' in html
    assert "范围测试书" in html
    assert "可操作的 Book" in html
    # 选择器带分组筛选、搜索与分页控件（Book 多时不用一屏铺开）
    assert "data-book-picker" in html
    assert "data-book-group" in html
    assert "data-book-search" in html
    assert "data-book-prev" in html
    # admin 与 Book 范围互斥的提示必须写在表单上，否则用户会以为范围生效了
    assert "admin 作用域不能与 Book 范围共存" in html


def test_token_page_deletes_only_revoked(admin, csrf, db) -> None:
    """吊销只让它失效；页面上的「删除」只对已吊销的行出现，删完从列表消失。"""
    token, _raw = token_service.issue_token(db, name="临时脚本", scopes="read")
    db.commit()
    token_id = token.id

    # 有效时：只有「吊销」，构造删除表单也会被拒
    html = admin.get("/admin/tokens").text
    assert f"/admin/tokens/{token_id}/revoke" in html
    assert f"/admin/tokens/{token_id}/delete" not in html
    blocked = admin.post(
        f"/admin/tokens/{token_id}/delete",
        data={"csrf_token": csrf(admin)},
        follow_redirects=False,
    )
    assert blocked.status_code == 400

    # 吊销后：出现「删除」，删完记录不再出现在列表里
    revoked = admin.post(
        f"/admin/tokens/{token_id}/revoke",
        data={"csrf_token": csrf(admin)},
        follow_redirects=False,
    )
    assert revoked.status_code == 303
    assert f"/admin/tokens/{token_id}/delete" in admin.get("/admin/tokens").text

    removed = admin.post(
        f"/admin/tokens/{token_id}/delete",
        data={"csrf_token": csrf(admin)},
        follow_redirects=False,
    )
    assert removed.status_code == 303
    assert "临时脚本" not in admin.get("/admin/tokens").text
    # 审计里必须留下这次删除
    assert audit_service.count_rows(db) >= 1


def test_token_book_scope_endpoint_pages_and_filters(admin, db) -> None:
    from app.services import book_groups

    infra = book_groups.create(db, title="基础设施", slug_raw="infra")
    for index in range(1, 26):
        books_service.create_book(db, title=f"手册 {index:02d}", fmt="markdown", group="default")
    books_service.create_book(db, title="网络专册", fmt="markdown", group="infra")
    db.commit()
    assert infra.slug == "infra"

    first = admin.get("/admin/tokens/books.json").json()
    assert first["total"] == 26
    assert first["page"] == 1
    assert first["pages"] == 2
    # 每页 20 本：一屏能看更多，不用频繁翻页
    assert len(first["books"]) == first["page_size"] == 20

    second = admin.get("/admin/tokens/books.json?page=2").json()
    assert second["page"] == 2
    assert len(second["books"]) == 6
    assert {item["title"] for item in first["books"]}.isdisjoint(
        {item["title"] for item in second["books"]}
    )

    scoped = admin.get("/admin/tokens/books.json?group=infra").json()
    assert scoped["total"] == 1
    assert scoped["books"][0]["title"] == "网络专册"
    assert scoped["books"][0]["group"] == "基础设施"

    searched = admin.get("/admin/tokens/books.json?q=手册 0").json()
    assert searched["total"] == 9
    assert all("手册 0" in item["title"] for item in searched["books"])

    # LIKE 通配符按字面处理：% 不会匹配所有书
    literal = admin.get("/admin/tokens/books.json?q=%25").json()
    assert literal["total"] == 0


def test_token_page_initial_page_respects_filters(admin, db) -> None:
    from app.services import book_groups

    book_groups.create(db, title="基础设施", slug_raw="infra")
    books_service.create_book(db, title="网络专册", fmt="markdown", group="infra")
    books_service.create_book(db, title="杂项手册", fmt="markdown", group="default")
    db.commit()

    html = admin.get("/admin/tokens?bgroup=infra").text
    assert "网络专册" in html
    assert "杂项手册" not in html
    assert "共 1 本" in html


def test_web_audit_csv(admin, db) -> None:
    _old_audit(db, 1)
    response = admin.get("/admin/audit.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith("\ufeff".encode())


def test_audit_page_has_export_link(admin) -> None:
    html = admin.get("/admin/audit").text
    assert "audit.csv" in html
    assert "导出 CSV" in html


# ------------------------------------------------------------------ 管理 API


@pytest.fixture()
def api(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    from .conftest import make_settings, run_migrations

    settings = make_settings(
        tmp_path, admin_api_token=BOOTSTRAP, audit_retention_days=180
    )
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, settings, app


def _make_book(client, title) -> dict:
    response = client.post(
        "/api/v1/admin/books",
        json={"title": title, "format": "markdown", "group": "default"},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _scoped_token(api, refs: list[str], scopes=("write",), name: str | None = None) -> str:
    client, _settings, _app = api
    label = name or f"scoped-{abs(hash((tuple(refs), tuple(scopes)))) % 10000}"
    response = client.post(
        "/api/v1/admin/tokens",
        json={"name": label, "scopes": list(scopes), "books": refs},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert [b["slug"] for b in body["books"]] == refs
    return body["token"]


def test_scoped_token_blocks_other_books(api) -> None:
    client, _settings, _app = api
    first = _make_book(client, "范围一")
    second = _make_book(client, "范围二")
    raw = _scoped_token(api, [first["slug"]])
    scoped = {"Authorization": f"Bearer {raw}"}

    assert client.get(f"/api/v1/admin/books/{first['slug']}/chapters", headers=scoped).status_code == 200
    blocked = client.get(f"/api/v1/admin/books/{second['slug']}/chapters", headers=scoped)
    assert blocked.status_code == 403
    assert "无权操作" in blocked.json()["error"]["message"]

    write_blocked = client.post(
        f"/api/v1/admin/books/{second['slug']}/chapters",
        json={"title": "越界", "content": "# x"},
        headers=scoped,
    )
    assert write_blocked.status_code == 403

    # 全站级只读端点仍然可用（Book 范围只约束带 book_ref 的端点）
    assert client.get("/api/v1/admin/meta", headers=scoped).status_code == 200


def test_token_create_rejects_unknown_book(api) -> None:
    client, _settings, _app = api
    response = client.post(
        "/api/v1/admin/tokens",
        json={"name": "bad-scope", "scopes": ["read"], "books": ["no-such-book"]},
        headers=AUTH,
    )
    assert response.status_code == 404
    listed = client.get("/api/v1/admin/tokens", headers=AUTH).json()["items"]
    assert all(item["name"] != "bad-scope" for item in listed)


def test_api_audit_export_and_cleanup(api) -> None:
    client, settings, app = api
    with app.state.sessionmaker() as session:
        session.add(
            AuditLog(
                actor_name="api:old",
                action="chapter.create",
                target_type="chapter",
                target_id=1,
                detail="{}",
                created_at=utcnow() - timedelta(days=400),
            )
        )
        session.commit()

    exported = client.get("/api/v1/admin/audit.csv", headers=AUTH)
    assert exported.status_code == 200
    assert exported.content.startswith("\ufeff".encode())
    assert b"created_at,actor,action" in exported.content

    preview = client.post("/api/v1/admin/audit/cleanup", headers=AUTH)
    assert preview.status_code == 200
    assert preview.json()["applied"] is False
    assert preview.json()["would_delete"] == 1

    applied = client.post("/api/v1/admin/audit/cleanup?confirm=true", headers=AUTH)
    assert applied.status_code == 200
    assert applied.json()["applied"] is True
    assert applied.json()["deleted"] == 1


def test_api_audit_export_needs_admin_scope(api) -> None:
    client, _settings, app = api
    reader = _scoped_token(api, [], scopes=("read",))
    # 无效 Token 401；read 作用域不够（审计含全站其它 Book 的操作记录）
    assert client.get("/api/v1/admin/audit.csv", headers={"Authorization": "Bearer bad"}).status_code == 401
    assert client.get("/api/v1/admin/audit.csv", headers={"Authorization": f"Bearer {reader}"}).status_code == 403
    admin = _scoped_token(api, [], scopes=("admin",), name="audit-admin")
    exported = client.get("/api/v1/admin/audit.csv", headers={"Authorization": f"Bearer {admin}"})
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")


def test_admin_scope_cannot_combine_with_book_range(db) -> None:
    with pytest.raises(ValidationFailed):
        token_service.issue_token(db, name="admin-with-books", scopes=["admin"], book_ids=[1])


def test_api_token_create_rejects_admin_with_books(api) -> None:
    client, _settings, _app = api
    book = _make_book(client, "范围书")
    response = client.post(
        "/api/v1/admin/tokens",
        json={"name": "admin-with-books", "scopes": ["admin"], "books": [book["slug"]]},
        headers=AUTH,
    )
    assert response.status_code == 400
    assert "admin" in response.json()["error"]["message"]
    listed = client.get("/api/v1/admin/tokens", headers=AUTH).json()["items"]
    assert all(item["name"] != "admin-with-books" for item in listed)


def test_legacy_admin_scoped_token_is_rejected(api) -> None:
    """存量数据里可能已有 admin + Book 范围的 Token：任何 admin 端点都必须拒绝。"""
    client, _settings, app = api
    book = _make_book(client, "遗留书")
    raw = "bh_legacy_admin_scoped_0123456789"
    with app.state.sessionmaker() as session:
        session.add(
            ApiToken(
                name="legacy-admin-scoped",
                token_hash=token_service.hash_token(raw),
                prefix=raw[:11],
                scopes="admin",
                book_scope=str(book["id"]),
            )
        )
        session.commit()

    response = client.get("/api/v1/admin/books", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 403
    assert "admin" in response.json()["error"]["message"]


def test_scoped_token_filters_books_and_trash(api) -> None:
    client, _settings, _app = api
    inside = _make_book(client, "范围内")
    outside = _make_book(client, "范围外")
    raw = _scoped_token(api, [inside["slug"]], name="list-scoped")
    scoped = {"Authorization": f"Bearer {raw}"}

    listed = client.get("/api/v1/admin/books", headers=scoped)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert [item["slug"] for item in body["items"]] == [inside["slug"]]

    assert client.post(f"/api/v1/admin/books/{outside['slug']}/delete?confirm=true", headers=AUTH).status_code == 200
    assert client.post(f"/api/v1/admin/books/{inside['slug']}/delete?confirm=true", headers=AUTH).status_code == 200

    trash = client.get("/api/v1/admin/trash", headers=scoped)
    assert trash.status_code == 200
    slugs = [item["slug"] for item in trash.json()["books"]]
    assert inside["slug"] in slugs
    assert outside["slug"] not in slugs

    # 审计涉及全站其它 Book，受限 Token 一律拒绝
    assert client.get("/api/v1/admin/audit", headers=scoped).status_code == 403
    assert client.get("/api/v1/admin/audit.csv", headers=scoped).status_code == 403


def test_idempotency_key_is_namespaced_per_token(api) -> None:
    client, _settings, _app = api
    first = _scoped_token(api, [], name="idem-a")
    second = _scoped_token(api, [], name="idem-b")
    payload = {"title": "幂等书", "format": "markdown", "group": "default"}
    key = "shared-idempotency-key"

    one = client.post(
        "/api/v1/admin/books",
        json=payload,
        headers={"Authorization": f"Bearer {first}", "Idempotency-Key": key},
    )
    assert one.status_code == 201, one.text
    two = client.post(
        "/api/v1/admin/books",
        json=payload,
        headers={"Authorization": f"Bearer {second}", "Idempotency-Key": key},
    )
    # 不同 Token 用同一个键互不影响：不会回放别人的响应，也不会 409
    assert two.status_code == 201, two.text
    assert two.json()["id"] != one.json()["id"]

    # 同一 Token 重复同键同内容 → 回放首次结果
    replay = client.post(
        "/api/v1/admin/books",
        json=payload,
        headers={"Authorization": f"Bearer {first}", "Idempotency-Key": key},
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == one.json()["id"]


def test_api_reads_single_book_and_section_with_content(api) -> None:
    """AI 的读写闭环：能按 Book / 节 ref 读回刚写进去的正文。"""
    client, _settings, _app = api
    book = _make_book(client, "闭环书")
    created = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "第一章", "content": "# 小标题\n\n正文内容"},
        headers=AUTH,
    )
    assert created.status_code == 201, created.text
    chapter = created.json()
    section = chapter["sections"][0]

    detail = client.get(f"/api/v1/admin/books/{book['slug']}", headers=AUTH)
    assert detail.status_code == 200
    assert detail.json()["slug"] == book["slug"]

    section_url = (
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter['slug']}/sections/{section['slug']}"
    )
    read_back = client.get(section_url, headers=AUTH)
    assert read_back.status_code == 200
    body = read_back.json()
    assert body["slug"] == section["slug"]
    assert "正文内容" in body["content_raw"]
    assert body["toc"]

    metadata_only = client.get(f"{section_url}?with_content=0", headers=AUTH)
    assert metadata_only.status_code == 200
    assert "content_raw" not in metadata_only.json()

    assert client.get("/api/v1/admin/books/no-such-book", headers=AUTH).status_code == 404


def test_trash_lists_deleted_sections(api) -> None:
    """单节软删不会进 Book/章回收站，必须在 sections 里能看到并能恢复。"""
    client, _settings, _app = api
    book = _make_book(client, "节回收站书")
    created = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters",
        json={"title": "第一章", "content": "# 一节\n\n正文"},
        headers=AUTH,
    ).json()
    chapter = created
    section = chapter["sections"][0]
    deleted = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter['slug']}/sections/{section['slug']}/delete?confirm=true",
        headers=AUTH,
    )
    assert deleted.status_code == 200, deleted.text

    trash = client.get("/api/v1/admin/trash", headers=AUTH).json()
    slugs = [item["slug"] for item in trash["sections"]]
    assert section["slug"] in slugs
    entry = next(item for item in trash["sections"] if item["slug"] == section["slug"])
    assert entry["book"]["slug"] == book["slug"]
    assert entry["chapter"]["slug"] == chapter["slug"]

    restored = client.post(
        f"/api/v1/admin/books/{book['slug']}/chapters/{chapter['slug']}/sections/{section['slug']}/restore",
        headers=AUTH,
    )
    assert restored.status_code == 200, restored.text
