"""运行时加固：登录等时与限流、上传/请求体上限、webhook 两阶段投递、500 兜底。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import PayloadTooLarge
from app.main import create_app
from app.security import DUMMY_PASSWORD_HASH, verify_password
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import webhooks
from app.services.ratelimit import RateLimiter
from app.uploads import read_limited

from .conftest import make_settings, run_migrations


class FakeUpload:
    """只实现 read(size) 的假上传对象，记录调用次数以验证"没有读完整个流"。"""

    def __init__(self, chunk: bytes, chunks: int) -> None:
        self.chunk = chunk
        self.remaining = chunks
        self.reads = 0

    async def read(self, size: int = -1) -> bytes:
        self.reads += 1
        if self.remaining <= 0:
            return b""
        self.remaining -= 1
        return self.chunk


# ------------------------------------------------------------------ 登录


def test_dummy_hash_is_valid_bcrypt() -> None:
    """假 hash 必须能被 bcrypt 解析，否则"等时"分支等于没算（还会抛异常）。"""
    assert DUMMY_PASSWORD_HASH.startswith("$2b$12$")
    assert len(DUMMY_PASSWORD_HASH) == 60
    assert verify_password("anything", DUMMY_PASSWORD_HASH) is False
    # 超过 72 字节也不能抛异常（旧实现会在这一支上 500）
    assert verify_password("p" * 100, DUMMY_PASSWORD_HASH) is False
    assert verify_password("", DUMMY_PASSWORD_HASH) is False


def test_unknown_user_with_long_password_is_401_not_500(client) -> None:
    response = client.post(
        "/admin/login",
        data={"username": "no-such-user", "password": "p" * 100},
    )
    assert response.status_code == 401
    assert "用户名或密码错误" in response.text


def test_login_ip_limit_stops_username_spray(tmp_path) -> None:
    """换用户名刷登录会被"每 IP 总闸"拦下，不会无限尝试。"""
    settings = make_settings(tmp_path, login_fail_limit=2, login_fail_window=300)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        codes = [
            client.post(
                "/admin/login",
                data={"username": f"spray-{index}", "password": "wrong-password-1"},
            ).status_code
            for index in range(20)
        ]
    assert 429 in codes
    assert codes.count(429) >= 5


def test_login_success_still_works_with_limiters(client) -> None:
    from .conftest import ADMIN_PASSWORD, ADMIN_USER

    response = client.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


# ------------------------------------------------------------------ 限流器内存


def test_rate_limiter_has_hard_cap_on_buckets() -> None:
    limiter = RateLimiter(limit=5, window_seconds=60, max_entries=10)
    for index in range(200):
        limiter.check(f"key-{index}")
    assert len(limiter._hits) <= 10


# ------------------------------------------------------------------ 上传与请求体


def test_read_limited_stops_on_oversize() -> None:
    upload = FakeUpload(b"a" * 1024, chunks=100)

    async def run() -> None:
        with pytest.raises(PayloadTooLarge):
            await read_limited(upload, 4096)

    asyncio.run(run())
    # 4 KiB 上限 + 1 KiB 分块：最多读 5 次就该抛，绝不能读完 100 块
    assert upload.reads <= 5


def test_read_limited_returns_full_content_when_within_limit() -> None:
    upload = FakeUpload(b"a" * 1024, chunks=3)
    data = asyncio.run(read_limited(upload, 10 * 1024))
    assert data == b"a" * 3072


def test_request_body_over_limit_returns_413(tmp_path) -> None:
    settings = make_settings(tmp_path, max_request_bytes=64 * 1024)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/admin/login",
            content=b"x" * (128 * 1024),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


# ------------------------------------------------------------------ webhook 两阶段投递


def test_webhook_dispatch_is_deferred_until_commit(db, monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(url, body, headers):
        calls.append(url)
        return webhooks.DeliveryResult(status_code=200, error="")

    monkeypatch.setattr(webhooks, "_post", fake_post)
    hook, _secret = webhooks.create(
        db, url="https://example.com/hook", events=["chapter.published"]
    )
    db.commit()
    book = books_service.create_book(db, title="延迟投递", fmt="markdown")
    db.commit()
    chapter = chapters_service.create_chapter(db, book, title="章", slug_raw="c1")
    db.commit()

    chapters_service.set_status(db, chapter, "published")
    assert calls == []  # 事务里只落库，不发网络请求

    db.commit()
    assert calls == ["https://example.com/hook"]

    delivery = webhooks.list_deliveries(db, hook.id)[0]
    assert delivery.status_code == 200


def test_webhook_dispatch_rollback_drops_pending(db, monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(url, body, headers):
        calls.append(url)
        return webhooks.DeliveryResult(status_code=200, error="")

    monkeypatch.setattr(webhooks, "_post", fake_post)
    webhooks.create(db, url="https://example.com/hook", events=["book.created"])
    db.commit()
    books_service.create_book(db, title="回滚书", fmt="markdown")
    assert calls == []
    db.rollback()  # 回滚掉的待投递记录不该被发送
    assert calls == []


# ------------------------------------------------------------------ 500 兜底


def test_unhandled_error_returns_unified_body(tmp_path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    run_migrations(settings.database_url)

    def boom(*args, **kwargs):
        raise RuntimeError("内部细节不该出现在响应里")

    monkeypatch.setattr(books_service, "list_books", boom)
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/books")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"]
    assert "内部细节" not in response.text


def test_settings_default_request_limit_covers_full_batch() -> None:
    settings = Settings.from_env(
        {
            "SECRET_KEY": "unit-test-secret-key-abcdefghijklmnop",
            "MAX_UPLOAD_BYTES": "2000",
            "MAX_UPLOAD_FILES": "3",
        }
    )
    assert settings.max_request_bytes == 3 * 2000 + 1024 * 1024
