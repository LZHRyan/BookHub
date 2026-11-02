"""集成：Webhook 投递/重试、sitemap 与 metrics。"""

from __future__ import annotations

import json

import pytest

from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import sections as sections_service
from app.services import webhooks as webhook_service

AUTH = {"Authorization": "Bearer bh_integration_token_0123456789"}


def _book(db, title="集成手册"):
    book = books_service.create_book(db, title=title, fmt="markdown")
    db.commit()
    return book


class Recorder:
    """替换 webhooks._post，记录请求并返回预设结果。"""

    def __init__(self, status=200, error=""):
        self.status = status
        self.error = error
        self.calls: list[dict] = []

    def __call__(self, url, body, headers):
        self.calls.append({"url": url, "body": body, "headers": headers})
        return webhook_service.DeliveryResult(status_code=self.status, error=self.error)


@pytest.fixture()
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(webhook_service, "_post", rec)
    return rec


# ------------------------------------------------------------------ 签名与登记


def test_sign_is_hmac_sha256() -> None:
    signature = webhook_service.sign("s3cret", b'{"a":1}')
    assert signature.startswith("sha256=")
    assert len(signature) == len("sha256=") + 64


def test_create_returns_secret_and_hides_it_in_list(db) -> None:
    hook, secret = webhook_service.create(
        db, url="https://example.com/hook", events=["chapter.published"]
    )
    db.commit()
    assert secret and hook.secret == secret
    detail = webhook_service.detail_of(hook)
    assert "secret" not in detail
    assert detail["events"] == ["chapter.published"]


def test_create_rejects_bad_input(db) -> None:
    from app.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        webhook_service.create(db, url="ftp://example.com", events=["chapter.published"])
    with pytest.raises(ValidationFailed):
        webhook_service.create(db, url="https://example.com", events=[])
    with pytest.raises(ValidationFailed):
        webhook_service.create(db, url="https://example.com", events=["nope"])


# ------------------------------------------------------------------ 投递


def test_publish_triggers_signed_delivery(db, recorder) -> None:
    book = _book(db)
    hook, _secret = webhook_service.create(
        db, url="https://example.com/hook", events=["chapter.published"]
    )
    db.commit()
    chapter = chapters_service.create_chapter_with_section(db, book, title="第一章", raw="# 1")[0]
    db.commit()

    chapters_service.set_status(db, chapter, "published")
    db.commit()

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    body = json.loads(call["body"].decode())
    assert body["event"] == "chapter.published"
    assert body["chapter_slug"] == chapter.slug
    assert call["headers"]["X-BookHub-Event"] == "chapter.published"
    assert call["headers"]["X-BookHub-Signature"] == webhook_service.sign(
        hook.secret, call["body"]
    )

    deliveries = webhook_service.list_deliveries(db, hook.id)
    assert deliveries[0].status_code == 200
    assert deliveries[0].delivered_at is not None


def test_failed_delivery_does_not_block_publish(db, monkeypatch) -> None:
    monkeypatch.setattr(webhook_service, "_post", Recorder(status=500, error="HTTP 500"))
    book = _book(db)
    webhook_service.create(db, url="https://example.com/hook", events=["chapter.published"])
    db.commit()
    chapter = chapters_service.create_chapter_with_section(db, book, title="一章", raw="# 1")[0]
    db.commit()

    chapters_service.set_status(db, chapter, "published")
    db.commit()
    db.refresh(chapter)
    assert chapter.status == "published"

    hook = webhook_service.list_hooks(db)[0]
    delivery = webhook_service.list_deliveries(db, hook.id)[0]
    assert delivery.status_code == 500
    assert delivery.delivered_at is None
    assert hook.last_status == 500


def test_inactive_hook_not_delivered(db, recorder) -> None:
    book = _book(db)
    hook, _secret = webhook_service.create(
        db, url="https://example.com/hook", events=["chapter.published"]
    )
    db.commit()
    webhook_service.deactivate(db, hook)
    db.commit()

    chapter = chapters_service.create_chapter_with_section(db, book, title="一章", raw="# 1")[0]
    db.commit()
    chapters_service.set_status(db, chapter, "published")
    db.commit()
    assert recorder.calls == []


def test_retry_updates_delivery(db, monkeypatch) -> None:
    monkeypatch.setattr(webhook_service, "_post", Recorder(status=502, error="HTTP 502"))
    book = _book(db)
    webhook_service.create(db, url="https://example.com/hook", events=["chapter.published"])
    db.commit()
    chapter = chapters_service.create_chapter_with_section(db, book, title="一章", raw="# 1")[0]
    db.commit()
    chapters_service.set_status(db, chapter, "published")
    db.commit()

    hook = webhook_service.list_hooks(db)[0]
    delivery = webhook_service.list_deliveries(db, hook.id)[0]
    assert delivery.status_code == 502

    monkeypatch.setattr(webhook_service, "_post", Recorder(status=200))
    webhook_service.deliver_now(db, delivery)
    db.commit()
    assert delivery.status_code == 200
    assert delivery.attempts == 2
    assert delivery.delivered_at is not None


# ------------------------------------------------------------------ 页面与端点


def test_sitemap_lists_public_content(client, db) -> None:
    public = _book(db, title="公开书")
    single, single_section = chapters_service.create_chapter_with_section(
        db, public, title="公开章", raw="# x", status="published"
    )
    multi = chapters_service.create_chapter(db, public, title="多节章", status="published")
    first = sections_service.create_section(db, multi, title="第一节", raw="# a")
    second = sections_service.create_section(db, multi, title="第二节", raw="# b")
    draft = chapters_service.create_chapter_with_section(db, public, title="草稿章", raw="# y")[0]
    hidden = books_service.create_book(db, title="隐藏书", visibility="unlisted")
    db.commit()

    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    text = response.text
    assert f"/b/{public.slug}" in text
    assert f"/b/{public.slug}/{single.slug}" in text
    # 单节章的章地址就是正文地址：不再重复收录三段式地址
    assert f"/b/{public.slug}/{single.slug}/{single_section.slug}" not in text
    assert f"/b/{public.slug}/{multi.slug}" in text
    assert f"/b/{public.slug}/{multi.slug}/{first.slug}" in text
    assert f"/b/{public.slug}/{multi.slug}/{second.slug}" in text
    assert f"/b/{public.slug}/{draft.slug}" not in text
    assert f"/b/{hidden.slug}" not in text


def test_metrics_exposes_minimal_set(client, db) -> None:
    book = _book(db)
    chapters_service.create_chapter_with_section(db, book, title="章", raw="# x", status="published")
    db.commit()
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    for name in (
        "bookhub_books_total",
        "bookhub_chapters_published_total",
        "bookhub_sections_published_total",
        "bookhub_media_bytes_total",
    ):
        assert f"# TYPE {name} gauge" in body
        assert any(line.startswith(name + " ") for line in body.splitlines())


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


def test_api_webhook_lifecycle(api, monkeypatch) -> None:
    client = api
    created = client.post(
        "/api/v1/admin/webhooks",
        json={"url": "https://example.com/hook", "events": ["chapter.published"]},
        headers=AUTH,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["secret"]
    hook_id = body["id"]

    listed = client.get("/api/v1/admin/webhooks", headers=AUTH).json()
    assert listed["items"][0]["url"] == "https://example.com/hook"
    assert "secret" not in listed["items"][0]

    monkeypatch.setattr(webhook_service, "_post", Recorder(status=200))
    tested = client.post(f"/api/v1/admin/webhooks/{hook_id}/test", headers=AUTH)
    assert tested.status_code == 200
    assert tested.json()["ok"] is True

    deliveries = client.get(f"/api/v1/admin/webhooks/{hook_id}/deliveries", headers=AUTH).json()
    assert deliveries["items"][0]["event"] == "webhook.test"

    delivery_id = deliveries["items"][0]["id"]
    retried = client.post(f"/api/v1/admin/deliveries/{delivery_id}/retry", headers=AUTH)
    assert retried.status_code == 200
    assert retried.json()["attempts"] == 2

    removed = client.delete(f"/api/v1/admin/webhooks/{hook_id}", headers=AUTH)
    assert removed.status_code == 200
    assert client.post(f"/api/v1/admin/webhooks/{hook_id}/test", headers=AUTH).status_code == 400


def test_api_webhook_needs_admin_scope(api) -> None:
    client = api
    raw = client.post(
        "/api/v1/admin/tokens",
        json={"name": "writer", "scopes": ["write"]},
        headers=AUTH,
    ).json()["token"]
    response = client.post(
        "/api/v1/admin/webhooks",
        json={"url": "https://example.com/hook", "events": ["chapter.published"]},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert response.status_code == 403


def test_webhook_create_rejects_internal_targets(api) -> None:
    """回调地址不能指向本机/内网，否则 webhook 就是一台 SSRF 跳板。"""
    client = api
    for url in (
        "http://127.0.0.1:8080/hook",
        "http://localhost:8080/hook",
        "http://app.localhost/hook",
        "http://[::1]/hook",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/hook",
        "http://192.168.1.10/hook",
        "http://user:pass@example.com/hook",
    ):
        response = client.post(
            "/api/v1/admin/webhooks",
            json={"url": url, "events": ["chapter.published"]},
            headers=AUTH,
        )
        assert response.status_code == 400, f"{url} → {response.status_code} {response.text}"

    # 公网域名仍可登记（登记时不做 DNS，避免依赖网络）
    ok = client.post(
        "/api/v1/admin/webhooks",
        json={"url": "https://example.com/hook", "events": ["chapter.published"]},
        headers=AUTH,
    )
    assert ok.status_code == 201, ok.text


def test_webhook_delivery_rejects_hostname_resolving_to_internal(monkeypatch) -> None:
    """域名可以在登记后把 A 记录改成内网（DNS rebinding），投递前必须再查一次。"""

    def fake_getaddrinfo(host, port, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(webhook_service.socket, "getaddrinfo", fake_getaddrinfo)
    result = webhook_service._post("https://rebind.example.com/hook", b"{}", {})
    assert result.status_code is None
    assert "内网" in (result.error or "")
