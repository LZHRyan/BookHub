"""站点设置：数据库覆盖环境变量默认值。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SiteSetting, utcnow
from app.services.render import sanitize_html

EDITABLE_KEYS = ("site_name", "site_footer", "home_intro")
# 首页说明允许少量排版标记，但同样走白名单净化，避免管理员往首页注入任意 HTML
HTML_KEYS = ("home_intro",)


def load_settings(session: Session, settings: Settings) -> dict[str, str]:
    values = {
        "site_name": settings.site_name,
        "site_footer": settings.site_footer,
        "home_intro": settings.home_intro,
    }
    rows = session.execute(select(SiteSetting)).scalars().all()
    for row in rows:
        if row.key in values:
            values[row.key] = row.value
    return values


def save_settings(session: Session, values: dict[str, str]) -> dict[str, str]:
    saved: dict[str, str] = {}
    for key in EDITABLE_KEYS:
        if key not in values:
            continue
        value = (values.get(key) or "").strip()
        if key in HTML_KEYS and value:
            value = sanitize_html(value).strip()
        row = session.get(SiteSetting, key)
        if row is None:
            row = SiteSetting(key=key, value=value)
            session.add(row)
        else:
            row.value = value
            row.updated_at = utcnow()
        saved[key] = value
    return saved


def reset_setting(session: Session, key: str) -> None:
    row = session.get(SiteSetting, key)
    if row is not None:
        session.delete(row)
