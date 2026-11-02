"""认证、会话、CSRF 与账号管理。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import User
from app.security import (
    PasswordError,
    hash_password,
    issue_csrf,
    issue_session,
    password_policy_errors,
    read_session,
    verify_csrf,
    verify_password,
)
from app.services.users import (
    authenticate,
    create_user,
    ensure_initial_admin,
    set_active,
    set_password,
)

from .conftest import ADMIN_PASSWORD, ADMIN_USER, csrf_token, make_settings, run_migrations


def test_password_hash_roundtrip() -> None:
    digest = hash_password("AdminPass123")
    assert digest.startswith("$2b$")
    assert verify_password("AdminPass123", digest) is True
    assert verify_password("wrong", digest) is False


def test_password_over_72_bytes_rejected() -> None:
    with pytest.raises(PasswordError):
        hash_password("a" * 100)
    assert verify_password("a" * 100, hash_password("AdminPass123")) is False


def test_password_policy() -> None:
    assert password_policy_errors("AdminPass123") == []
    assert password_policy_errors("short1") != []
    assert password_policy_errors("onlyletters") != []
    assert password_policy_errors("1234567890") != []
    assert password_policy_errors("AdminPass123", username="adminpass123") != []


def test_session_sign_and_expiry() -> None:
    token = issue_session("secret-key-value-1234567890", 7, 3)
    data = read_session("secret-key-value-1234567890", token, 60)
    assert data is not None and data.user_id == 7 and data.epoch == 3
    assert read_session("othersecret-key-value-123", token, 60) is None
    assert read_session("secret-key-value-1234567890", token + "x", 60) is None


def test_csrf_bound_to_session() -> None:
    secret = "secret-key-value-1234567890"
    first = read_session(secret, issue_session(secret, 1, 1), 60)
    second = read_session(secret, issue_session(secret, 1, 1), 60)
    assert first and second
    token = issue_csrf(secret, first)
    assert verify_csrf(secret, first, token, 60) is True
    assert verify_csrf(secret, second, token, 60) is False
    assert verify_csrf(secret, first, token + "x", 60) is False


def test_initial_admin_idempotent(db, settings) -> None:
    assert ensure_initial_admin(db, settings) is True
    db.commit()
    first_hash = db.execute(select(User)).scalars().one().password_hash
    assert ensure_initial_admin(db, settings) is False
    db.commit()
    users = db.execute(select(User)).scalars().all()
    assert len(users) == 1
    assert users[0].password_hash == first_hash


def test_initial_admin_skipped_without_env(db, tmp_path) -> None:
    silent = make_settings(tmp_path, initial_admin_user=None, initial_admin_password=None)
    assert ensure_initial_admin(db, silent) is False
    db.commit()
    assert db.execute(select(User)).scalars().all() == []


def test_authenticate_disabled_account(db, settings) -> None:
    create_user(db, username="ops01", password="OpsPass1234", role="admin")
    db.commit()
    user = authenticate(db, "ops01", "OpsPass1234")
    assert user is not None
    set_active(user, False)
    db.commit()
    assert authenticate(db, "ops01", "OpsPass1234") is None


def test_password_change_invalidates_session(admin, csrf, db) -> None:
    assert admin.get("/admin").status_code == 200
    target = db.execute(select(User).where(User.username == ADMIN_USER)).scalar_one()
    set_password(target, "AnotherPass123")
    db.commit()
    response = admin.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert "/admin/login" in response.headers["location"]


def test_csrf_token_from_other_session_rejected(admin, settings) -> None:
    token = csrf_token(admin, "/admin")
    with TestClient(admin.app) as other:
        assert other.get("/admin", follow_redirects=False).status_code == 303
        with admin.app.state.sessionmaker() as session:
            session.execute(select(User))
    response = admin.post(
        "/admin/books/new",
        data={"title": "X", "csrf_token": token + "tampered"},
    )
    assert response.status_code == 403


def test_login_rate_limited(tmp_path) -> None:
    settings = make_settings(tmp_path, login_fail_limit=2, login_fail_window=60)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.post("/admin/login", data={"username": "admin", "password": "bad"}).status_code == 401
        assert client.post("/admin/login", data={"username": "admin", "password": "bad"}).status_code == 401
        limited = client.post("/admin/login", data={"username": "admin", "password": "bad"})
        assert limited.status_code == 429
        assert "秒后再试" in limited.text
        ok = client.post(
            "/admin/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
            follow_redirects=False,
        )
        assert ok.status_code == 429


def test_successful_login_resets_counter(tmp_path) -> None:
    settings = make_settings(tmp_path, login_fail_limit=2, login_fail_window=60)
    run_migrations(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/admin/login", data={"username": "admin", "password": "bad"})
        client.post(
            "/admin/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
            follow_redirects=False,
        )
        again = client.post("/admin/login", data={"username": "admin", "password": "bad"})
        assert again.status_code == 401


def test_user_management_audit(admin, csrf, db) -> None:
    token = csrf(admin, "/admin/users")
    response = admin.post(
        "/admin/users/new",
        data={
            "username": "audit01",
            "password": "AuditPass123",
            "display_name": "审计",
            "role": "editor",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = admin.get("/admin/audit")
    assert "user.create" in page.text
