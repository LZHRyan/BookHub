"""pytest 夹具：每个测试一个独立 SQLite 库，跑真实迁移。"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient

from alembic import command
from app.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
ADMIN_USER = "admin"
ADMIN_PASSWORD = "AdminPass123"


def run_migrations(database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    config = AlembicConfig(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(config, "head")


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    base = {
        "secret_key": "unit-test-secret-key-abcdefghijklmnop",
        "database_url": f"sqlite:///{(tmp_path / 'bookhub.db').as_posix()}",
        "data_dir": str(tmp_path),
        "site_name": "测试知识库",
        "site_footer": "内部文档",
        "home_intro": "欢迎",
        "initial_admin_user": ADMIN_USER,
        "initial_admin_password": ADMIN_PASSWORD,
        "rate_limit_enabled": False,
        "api_docs_enabled": True,
        # 测试默认不建内置指南：多数用例断言的是「空库」或精确计数，
        # 需要它的用例显式传 builtin_guide=True。
        "builtin_guide": False,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _inline_webhooks():
    """测试里把 webhook 投递改成同步执行：断言不需要等后台线程。

    生产默认走线程池（`webhooks._ThreadExecutor`），提交后才投递；这里只替换执行器，
    仍然走「先落库 → commit 后投递」的真实路径。
    """
    from app.services import webhooks

    original = webhooks.EXECUTOR
    webhooks.use_executor(webhooks.InlineExecutor())
    try:
        yield
    finally:
        webhooks.use_executor(original)


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture()
def app(settings: Settings):
    run_migrations(settings.database_url)
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db(app):
    session = app.state.sessionmaker()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def admin(client):
    response = client.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return client


def csrf_token(client, path: str = "/admin") -> str:
    html = client.get(path).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, f"页面 {path} 没有 csrf_token"
    return match.group(1)


@pytest.fixture()
def csrf():
    return csrf_token
