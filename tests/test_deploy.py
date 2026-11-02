"""部署相关行为：探针、静态资源、日志格式、配置清单完整性。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.logging_setup import JsonFormatter
from app.main import create_app

from .conftest import run_migrations

ROOT = Path(__file__).resolve().parents[1]


def test_healthz(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    # 升级验证：version 来自镜像，schema 来自库，两者都要有
    assert payload["version"]
    assert payload["schema"], "迁移已执行时 /healthz 应暴露 alembic 版本"


def test_readyz(client) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["schema"]


def test_readyz_fails_when_db_unwritable(settings) -> None:
    run_migrations(settings.database_url)
    app = create_app(settings)

    class BrokenFactory:
        def __call__(self):
            raise RuntimeError("database is gone")

    with TestClient(app) as client:
        app.state.sessionmaker = BrokenFactory()  # type: ignore[assignment]
        response = client.get("/readyz")
        assert response.status_code == 503
        # 存活探针不受数据库影响，只是拿不到 schema
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").json()["schema"] is None


def test_static_assets(client) -> None:
    for path in ("/static/style.css", "/static/app.js", "/static/pygments.css"):
        response = client.get(path)
        assert response.status_code == 200, path


def test_docs_page(client) -> None:
    assert client.get("/docs").status_code == 200


def test_json_log_formatter_masks_secrets() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="bookhub",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="event",
        args=(),
        exc_info=None,
    )
    record.event = "auth.login"  # type: ignore[attr-defined]
    record.fields = {"password": "secret", "api_key": "k", "user": "admin"}  # type: ignore[attr-defined]
    payload = json.loads(formatter.format(record))
    assert payload["event"] == "auth.login"
    assert payload["level"] == "INFO"
    assert payload["ts"]
    assert payload["password"] == "***"
    assert payload["api_key"] == "***"
    assert payload["user"] == "admin"


def test_env_example_covers_all_settings() -> None:
    path = ROOT / ".env.example"
    if not path.exists():
        pytest.skip(".env.example 尚未生成")
    text = path.read_text(encoding="utf-8")
    fields = set(Settings.__dataclass_fields__)
    mapping = {
        "secret_key": "SECRET_KEY",
        "database_url": "DATABASE_URL",
        "data_dir": "DATA_DIR",
        "site_name": "SITE_NAME",
        "site_footer": "SITE_FOOTER",
        "home_intro": "HOME_INTRO",
        "session_cookie_name": "SESSION_COOKIE_NAME",
        "session_max_age": "SESSION_MAX_AGE",
        "cookie_secure": "COOKIE_SECURE",
        "initial_admin_user": "BOOKHUB_INITIAL_ADMIN_USER",
        "initial_admin_password": "BOOKHUB_INITIAL_ADMIN_PASSWORD",
        "max_upload_bytes": "MAX_UPLOAD_BYTES",
        "max_upload_files": "MAX_UPLOAD_FILES",
        "max_request_bytes": "MAX_REQUEST_BYTES",
        "max_content_chars": "MAX_CONTENT_CHARS",
        "media_max_bytes": "MEDIA_MAX_BYTES",
        "media_quota_bytes": "MEDIA_QUOTA_BYTES",
        "media_purge_grace_days": "MEDIA_PURGE_GRACE_DAYS",
        "media_allowed_types": "MEDIA_ALLOWED_TYPES",
        "version_retention": "VERSION_RETENTION",
        "api_key": "API_KEY",
        "admin_api_token": "ADMIN_API_TOKEN",
        "admin_api_rate_limit": "ADMIN_API_RATE_LIMIT",
        "audit_retention_days": "AUDIT_RETENTION_DAYS",
        "rate_limit_enabled": "RATE_LIMIT_ENABLED",
        "rate_limit_per_minute": "RATE_LIMIT_PER_MINUTE",
        "login_fail_limit": "LOGIN_FAIL_LIMIT",
        "login_fail_window": "LOGIN_FAIL_WINDOW",
        "trusted_proxies": "TRUSTED_PROXIES",
        "cors_origins": "CORS_ORIGINS",
        "api_docs_enabled": "API_DOCS_ENABLED",
        "root_path": "ROOT_PATH",
        "log_level": "LOG_LEVEL",
        "seed_demo": "SEED_DEMO",
        "builtin_guide": "BUILTIN_GUIDE_ENABLED",
        "web_concurrency": "WEB_CONCURRENCY",
    }
    assert set(mapping) == fields, "config.py 新增字段后需要同步更新本测试与 .env.example"
    missing = [env_name for env_name in mapping.values() if env_name not in text]
    assert missing == [], f".env.example 缺少：{missing}"


def test_initial_admin_bootstrap_from_env(settings) -> None:
    run_migrations(settings.database_url)
    app = create_app(settings)
    from sqlalchemy import select

    from app.models import User

    with TestClient(app):
        with app.state.sessionmaker() as session:
            users = session.execute(select(User)).scalars().all()
            assert [user.username for user in users] == ["admin"]
