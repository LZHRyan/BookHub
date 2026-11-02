"""配置读取与校验。"""

from __future__ import annotations

import pytest

from app.config import ConfigError, Settings


def base_env(**overrides: str) -> dict[str, str]:
    env = {"SECRET_KEY": "x" * 32}
    env.update(overrides)
    return env


def test_missing_secret_key_fails() -> None:
    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env({})
    assert "SECRET_KEY" in str(excinfo.value)


def test_short_secret_key_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"SECRET_KEY": "short"})


def test_defaults() -> None:
    settings = Settings.from_env(base_env())
    assert settings.session_max_age == 8 * 3600
    assert settings.max_upload_bytes == 5 * 1024 * 1024
    assert settings.max_content_chars == 500_000
    assert settings.version_retention == 50
    assert settings.rate_limit_per_minute == 120
    assert settings.api_docs_enabled is True
    assert settings.root_path == ""
    assert settings.is_sqlite is True


def test_invalid_bool_raises() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(base_env(RATE_LIMIT_ENABLED="maybe"))


def test_invalid_int_raises() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(base_env(MAX_CONTENT_CHARS="lots"))


def test_root_path_normalized() -> None:
    assert Settings.from_env(base_env(ROOT_PATH="/kb/")).root_path == "/kb"
    assert Settings.from_env(base_env(ROOT_PATH="kb")).root_path == "/kb"
    assert Settings.from_env(base_env(ROOT_PATH="/")).root_path == ""


def test_cors_origins_parsed() -> None:
    settings = Settings.from_env(base_env(CORS_ORIGINS="https://a.example, https://b.example"))
    assert settings.cors_origins == ("https://a.example", "https://b.example")


def test_public_dict_masks_secret() -> None:
    settings = Settings.from_env(base_env())
    assert settings.public_dict()["secret_key"] == "***"
