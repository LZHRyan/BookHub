"""界面表现契约：主题、站点标识、可访问性标记、CSP 与对比度。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import books as books_service
from app.services import chapters as chapters_service

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "app" / "static" / "style.css"
PYGMENTS = ROOT / "app" / "static" / "pygments.css"


# ------------------------------------------------------------------ 静态资源


def test_static_assets_present(client) -> None:
    for path, expected in (
        ("/static/theme.js", "javascript"),
        ("/static/favicon.svg", "image/svg+xml"),
        ("/static/style.css", "text/css"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert expected in response.headers["content-type"], path


def test_style_tokens_and_dark_theme() -> None:
    css = STYLE.read_text(encoding="utf-8")
    for token in ("--bg:", "--surface:", "--text:", "--accent:", "--radius:", "--shadow-sm:", "--measure:"):
        assert token in css, token
    assert ':root[data-theme="dark"]' in css
    assert ":root:not([data-theme])" in css, "必须保留未手动选择时跟随系统的分支"
    assert "prefers-reduced-motion" in css
    assert "@media print" in css


def test_dark_theme_defines_same_tokens() -> None:
    css = STYLE.read_text(encoding="utf-8")
    light = set(re.findall(r"(--[a-z0-9-]+):", css.split(':root[data-theme="dark"]')[0]))
    dark_block = css.split(':root[data-theme="dark"]')[1].split("/* 未手动选择时跟随系统")[0]
    dark = set(re.findall(r"(--[a-z0-9-]+):", dark_block))
    color_like = {
        name
        for name in light
        if any(
            key in name
            for key in (
                "bg",
                "surface",
                "text",
                "border",
                "accent",
                "danger",
                "success",
                "warning",
                "shadow",
            )
        )
    }
    assert color_like, "亮色令牌解析失败"
    assert color_like - dark == set(), f"暗色缺少令牌：{sorted(color_like - dark)}"


def test_components_reference_tokens_only() -> None:
    css = STYLE.read_text(encoding="utf-8")
    _, _, body = css.partition("/* ---------------------------------------------------------------- 2. 基础 */")
    # 打印样式会重新定义令牌（白纸黑字），属于令牌层，检查前先剔除
    body = re.sub(r"@media print \{.*", "", body, flags=re.S)
    leaked = re.findall(r"#[0-9a-fA-F]{3,8}\b", body)
    assert leaked == [], f"组件层出现硬编码色值：{leaked[:5]}"


def test_pygments_follows_theme() -> None:
    css = PYGMENTS.read_text(encoding="utf-8")
    assert ':root[data-theme="dark"]' in css
    assert ":root:not([data-theme])" in css


def test_static_assets_are_cache_busted(client) -> None:
    """静态资源必须带版本号，否则升级镜像后浏览器会继续用旧 CSS/JS。"""
    html = client.get("/").text
    assert re.search(r"/static/style\.css\?v=\d+", html), "style.css 未带 ?v="
    assert re.search(r"/static/pygments\.css\?v=\d+", html)
    assert re.search(r"/static/theme\.js\?v=\d+", html)
    assert re.search(r"/static/app\.js\?v=\d+", html)


# ------------------------------------------------------------------ 页面标记


def test_base_page_has_theme_and_brand(client) -> None:
    html = client.get("/").text
    assert "/static/theme.js" in html
    assert "favicon.svg" in html
    assert 'name="theme-color"' in html
    assert 'data-theme-choice="auto"' in html
    assert 'data-theme-choice="dark"' in html


def test_no_inline_script_blocks(client) -> None:
    """CSP 是 script-src 'self'，页面里不允许内联脚本。"""
    for path in ("/", "/search", "/admin/login"):
        html = client.get(path).text
        inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html, re.IGNORECASE)
        assert inline == [], f"{path} 存在内联脚本：{inline}"


def test_csp_not_relaxed(client) -> None:
    policy = client.get("/").headers["content-security-policy"]
    assert "script-src 'self'" in policy
    assert "unsafe-inline" not in policy.split("style-src")[0], "脚本策略不允许放宽"
    assert "frame-ancestors 'none'" in policy


def test_pages_have_landmarks(client, db) -> None:
    book = books_service.create_book(db, title="标记手册")
    chapters_service.create_chapter_with_section(
        db, book, title="正文", raw="# 标题\n\n内容", slug_raw="doc", status="published"
    )
    db.commit()
    for path in ("/", f"/b/{book.slug}", f"/b/{book.slug}/doc", "/search?q=正文"):
        html = client.get(path).text
        assert 'id="main"' in html, path
        assert 'class="skip-link"' in html, path
        assert "<footer" in html, path


def test_error_page_shape(client) -> None:
    html = client.get("/b/does-not-exist").text
    assert "error-page" in html
    assert "404" in html
    assert "返回首页" in html


def test_nav_current_marker(admin) -> None:
    html = admin.get("/admin/trash").text
    assert 'aria-current="page"' in html
    match = re.search(
        r'aria-current="page"[^>]*>\s*<svg.*?</svg>\s*<span>([^<]+)</span>', html, re.S
    )
    assert match and match.group(1) == "回收站", html[:200]


# ------------------------------------------------------------------ 对比度


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block))


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_contrast_meets_aa(theme: str) -> None:
    css = STYLE.read_text(encoding="utf-8")
    if theme == "light":
        block = css.split(":root {")[1].split("/* 手动选择暗色 */")[0]
    else:
        block = css.split(':root[data-theme="dark"] {')[1].split("/* 未手动选择时跟随系统")[0]
    tokens = _tokens(block)
    pairs = [("--text", "--bg"), ("--text", "--surface"), ("--text-muted", "--surface")]
    for foreground, background in pairs:
        assert tokens.get(foreground) and tokens.get(background), (theme, foreground, background)
        ratio = _contrast(tokens[foreground], tokens[background])
        assert ratio >= 4.5, f"{theme} 主题 {foreground}/{background} 对比度只有 {ratio:.2f}"
