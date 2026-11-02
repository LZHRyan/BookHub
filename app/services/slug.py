"""slug 规范化与唯一化。"""

from __future__ import annotations

import re
import secrets
import unicodedata
from collections.abc import Callable

_ALLOWED = re.compile(r"[^a-z0-9]+")
_MAX_LEN = 120


def slugify(value: str) -> str:
    """转成 `[a-z0-9-]`。中文等非 ASCII 字符会被丢弃（由调用方决定回退）。"""
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    dashed = _ALLOWED.sub("-", lowered)
    return dashed.strip("-")[:_MAX_LEN].strip("-")


def fallback_slug(prefix: str) -> str:
    """无法从标题派生时使用：`book-3f9a1c` 这类短稳定标识。"""
    return f"{prefix}-{secrets.token_hex(3)}"


def unique_slug(base: str, exists: Callable[[str], bool], *, prefix: str) -> str:
    """冲突时追加 `-2`、`-3`……；base 为空时直接生成回退值。"""
    candidate = base or fallback_slug(prefix)
    if not exists(candidate):
        return candidate
    index = 2
    while index < 10_000:
        attempt = f"{candidate}-{index}"
        if not exists(attempt):
            return attempt
        index += 1
    return f"{candidate}-{secrets.token_hex(4)}"


def anchor_slug(text: str, used: set[str] | None = None) -> str:
    """标题锚点：保留字母、数字与中文，其余转连字符。"""
    cleaned = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\s-]", "", text or "")
    base = re.sub(r"[\s-]+", "-", cleaned).strip("-").lower() or "section"
    if used is None:
        return base
    candidate = base
    counter = 2
    while candidate in used:
        candidate = f"{base}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate
