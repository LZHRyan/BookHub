"""环境变量配置。

所有运行配置只来自环境变量（.env 由 docker compose / 本地 shell 注入），
这样容器、测试与本地开发使用同一套读取逻辑。
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


class ConfigError(RuntimeError):
    """配置缺失或非法时抛出，启动阶段即失败。"""


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ConfigError(f"配置项 {key} 取值非法：{raw!r}，应为 true/false")


def _int(env: Mapping[str, str], key: str, default: int, minimum: int | None = None) -> int:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"配置项 {key} 取值非法：{raw!r}，应为整数") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"配置项 {key} 不能小于 {minimum}，当前为 {value}")
    return value


def _text(env: Mapping[str, str], key: str, default: str) -> str:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip()


def _optional(env: Mapping[str, str], key: str) -> str | None:
    raw = (env.get(key) or "").strip()
    return raw or None


def _origins(env: Mapping[str, str]) -> tuple[str, ...]:
    raw = _text(env, "CORS_ORIGINS", "*")
    items = tuple(part.strip() for part in raw.split(",") if part.strip())
    return items or ("*",)


def _trusted_proxies(env: Mapping[str, str]) -> tuple[str, ...]:
    """TRUSTED_PROXIES=10.0.0.0/8,172.16.0.1 —— 允许的代理网段；非法条目直接报配置错。"""
    raw = _text(env, "TRUSTED_PROXIES", "")
    items = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    for item in items:
        try:
            ipaddress.ip_network(item, strict=False)
        except ValueError as exc:
            raise ConfigError(f"TRUSTED_PROXIES 里的 {item!r} 不是合法 IP 或 CIDR") from exc
    return tuple(items)


def _normalize_root_path(raw: str) -> str:
    path = raw.strip()
    if not path or path == "/":
        return ""
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/")


@dataclass(frozen=True)
class Settings:
    """不可变配置对象。`from_env()` 是唯一入口。"""

    secret_key: str
    database_url: str = "sqlite:///./data/bookhub.db"
    data_dir: str = "./data"
    site_name: str = "BookHub 知识库"
    site_footer: str = "内部技术文档"
    home_intro: str = ""
    session_cookie_name: str = "bookhub_session"
    session_max_age: int = 8 * 3600
    cookie_secure: bool = False
    initial_admin_user: str | None = None
    initial_admin_password: str | None = None
    max_upload_bytes: int = 5 * 1024 * 1024
    max_upload_files: int = 50
    # 单次请求体上限（含 multipart 总量）：默认放得下"满批上传"，
    # 具体值在 from_env 里按 max_upload_files × max_upload_bytes 计算
    max_request_bytes: int = 256 * 1024 * 1024
    max_content_chars: int = 500_000
    media_max_bytes: int = 20 * 1024 * 1024
    media_quota_bytes: int = 500 * 1024 * 1024
    media_purge_grace_days: int = 7
    media_allowed_types: str = "png,jpg,jpeg,gif,webp,svg,avif,bmp,pdf,txt,md,csv,json,log,yaml,yml,zip"
    version_retention: int = 50
    api_key: str | None = None
    admin_api_token: str | None = None
    admin_api_rate_limit: int = 60
    audit_retention_days: int = 180
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120
    login_fail_limit: int = 5
    login_fail_window: int = 300
    # 只有直连 peer 落在这些 IP/CIDR 里时才采信 X-Forwarded-For / X-Real-IP
    trusted_proxies: tuple[str, ...] = ()
    cors_origins: tuple[str, ...] = field(default_factory=lambda: ("*",))
    api_docs_enabled: bool = True
    root_path: str = ""
    log_level: str = "INFO"
    seed_demo: bool = False
    # 启动时幂等创建内置《AI Agent 接入使用指南》（见 app/services/guide.py）
    builtin_guide: bool = True
    web_concurrency: int = 1

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source: Mapping[str, str] = os.environ if env is None else env
        secret_key = (source.get("SECRET_KEY") or "").strip()
        if not secret_key:
            raise ConfigError(
                "缺少必需配置 SECRET_KEY。请生成一个随机值后写入环境变量，"
                "例如：SECRET_KEY=$(python -c \"import secrets;print(secrets.token_urlsafe(48))\")"
            )
        if len(secret_key) < 16:
            raise ConfigError("配置项 SECRET_KEY 过短（至少 16 个字符），请使用随机长字符串")

        log_level = _text(source, "LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError(f"配置项 LOG_LEVEL 取值非法：{log_level}")

        upload_bytes = _int(source, "MAX_UPLOAD_BYTES", 5 * 1024 * 1024, minimum=1024)
        upload_files = _int(source, "MAX_UPLOAD_FILES", 50, minimum=1)
        # 请求体上限默认放得下"满批上传"（N 个文件 × 单文件上限 + 1 MiB 表单开销）
        request_bytes_default = upload_files * upload_bytes + 1024 * 1024

        return cls(
            secret_key=secret_key,
            database_url=_text(source, "DATABASE_URL", "sqlite:///./data/bookhub.db"),
            data_dir=_text(source, "DATA_DIR", "./data"),
            site_name=_text(source, "SITE_NAME", "BookHub 知识库"),
            site_footer=_text(source, "SITE_FOOTER", "内部技术文档"),
            home_intro=_text(source, "HOME_INTRO", ""),
            session_cookie_name=_text(source, "SESSION_COOKIE_NAME", "bookhub_session"),
            session_max_age=_int(source, "SESSION_MAX_AGE", 8 * 3600, minimum=60),
            cookie_secure=_bool(source, "COOKIE_SECURE", False),
            initial_admin_user=_optional(source, "BOOKHUB_INITIAL_ADMIN_USER"),
            initial_admin_password=_optional(source, "BOOKHUB_INITIAL_ADMIN_PASSWORD"),
            max_upload_bytes=upload_bytes,
            max_upload_files=upload_files,
            max_request_bytes=_int(
                source, "MAX_REQUEST_BYTES", request_bytes_default, minimum=1024
            ),
            max_content_chars=_int(source, "MAX_CONTENT_CHARS", 500_000, minimum=1000),
            media_max_bytes=_int(source, "MEDIA_MAX_BYTES", 20 * 1024 * 1024, minimum=1024),
            media_quota_bytes=_int(source, "MEDIA_QUOTA_BYTES", 500 * 1024 * 1024, minimum=1024),
            media_purge_grace_days=_int(source, "MEDIA_PURGE_GRACE_DAYS", 7, minimum=0),
            media_allowed_types=_text(
                source,
                "MEDIA_ALLOWED_TYPES",
                "png,jpg,jpeg,gif,webp,svg,avif,bmp,pdf,txt,md,csv,json,log,yaml,yml,zip",
            ).lower(),
            version_retention=_int(source, "VERSION_RETENTION", 50, minimum=1),
            api_key=_optional(source, "API_KEY"),
            admin_api_token=_optional(source, "ADMIN_API_TOKEN"),
            admin_api_rate_limit=_int(source, "ADMIN_API_RATE_LIMIT", 60, minimum=1),
            audit_retention_days=_int(source, "AUDIT_RETENTION_DAYS", 180, minimum=0),
            rate_limit_enabled=_bool(source, "RATE_LIMIT_ENABLED", True),
            rate_limit_per_minute=_int(source, "RATE_LIMIT_PER_MINUTE", 120, minimum=1),
            login_fail_limit=_int(source, "LOGIN_FAIL_LIMIT", 5, minimum=1),
            login_fail_window=_int(source, "LOGIN_FAIL_WINDOW", 300, minimum=10),
            trusted_proxies=_trusted_proxies(source),
            cors_origins=_origins(source),
            api_docs_enabled=_bool(source, "API_DOCS_ENABLED", True),
            root_path=_normalize_root_path(_text(source, "ROOT_PATH", "")),
            log_level=log_level,
            seed_demo=_bool(source, "SEED_DEMO", False),
            builtin_guide=_bool(source, "BUILTIN_GUIDE_ENABLED", True),
            web_concurrency=_int(source, "WEB_CONCURRENCY", 1, minimum=1),
        )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def public_dict(self) -> dict[str, object]:
        """可写进日志/接口的配置快照，敏感值一律脱敏。"""
        return {
            "database_url": self.database_url,
            "data_dir": self.data_dir,
            "site_name": self.site_name,
            "session_max_age": self.session_max_age,
            "cookie_secure": self.cookie_secure,
            "max_upload_bytes": self.max_upload_bytes,
            "max_upload_files": self.max_upload_files,
            "max_content_chars": self.max_content_chars,
            "media_max_bytes": self.media_max_bytes,
            "media_quota_bytes": self.media_quota_bytes,
            "media_purge_grace_days": self.media_purge_grace_days,
            "media_allowed_types": self.media_allowed_types,
            "version_retention": self.version_retention,
            "audit_retention_days": self.audit_retention_days,
            "api_key_enabled": bool(self.api_key),
            "rate_limit_enabled": self.rate_limit_enabled,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "api_docs_enabled": self.api_docs_enabled,
            "root_path": self.root_path,
            "log_level": self.log_level,
            "secret_key": "***",
        }
