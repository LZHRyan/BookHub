"""Book / 分组图标：内置 SVG 图标集、渲染兜底与表单面板。"""

from __future__ import annotations

import re

from app.services.icons import ICON_GROUPS, ICON_PATHS, all_icons, icon, resolve_icon, total_icons


def test_catalog_shape() -> None:
    assert len(ICON_GROUPS) >= 5, "至少要覆盖 5 个分组"
    names = all_icons()
    assert total_icons() >= 100, f"预置图标不足 100 个，当前 {total_icons()}"
    assert len(names) == len(set(names)), "存在重复图标"
    for _, items in ICON_GROUPS:
        assert items, "分组不能为空"
        for name, label in items:
            assert name and label
            assert name in ICON_PATHS, f"{name} 没有对应的 SVG"


def test_icons_render_inline_svg() -> None:
    for name in all_icons():
        svg = str(icon(name, 20))
        assert svg.startswith("<svg")
        assert 'width="20"' in svg and 'height="20"' in svg
        assert "stroke=" in svg and svg.endswith("</svg>")


def test_resolve_and_fallback() -> None:
    assert resolve_icon("book-open") == "book-open"
    assert resolve_icon("🤖") == "cpu"
    assert resolve_icon("🛠️") == "wrench", "带变体选择符的 emoji 也要能认"
    assert resolve_icon("这不是图标") is None
    # 未知自由文本原样输出（老数据兜底），空值回退默认图标
    assert str(icon("自定义")) == "自定义"
    assert str(icon("")).startswith("<svg")


def test_book_form_renders_picker(admin) -> None:
    html = admin.get("/admin/books/new").text
    options = re.findall(r'data-icon="', html)
    assert len(options) >= 100, f"面板只渲染了 {len(options)} 个图标"
    assert "从预置图标中选择" in html
    assert "data-icon-preview" in html
    assert "data-icon-clear" in html
    # 面板不允许引入外部资源或内联脚本
    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html, re.IGNORECASE)
    assert inline == []


def test_create_book_with_picked_icon(admin, csrf, db) -> None:
    token = csrf(admin)
    response = admin.post(
        "/admin/books/new",
        data={
            "title": "图标书",
            "slug": "icon-book",
            "group": "default",
            "summary": "",
            "icon": "pin",
            "format": "markdown",
            "visibility": "public",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    home = admin.get("/").text
    assert "<svg" in home, "首页应把图标渲染成内联 SVG"
    payload = admin.get("/api/v1/books/icon-book").json()
    assert payload["icon"] == "pin"


def test_legacy_emoji_renders_as_vector(admin, csrf, db) -> None:
    """老数据存的是 emoji：页面不能再直接吐 emoji，而要映射成 SVG。"""
    token = csrf(admin)
    admin.post(
        "/admin/books/new",
        data={
            "title": "老图标书",
            "slug": "legacy-icon",
            "group": "default",
            "summary": "",
            "icon": "🎯",
            "format": "markdown",
            "visibility": "public",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    home = admin.get("/").text
    assert "🎯" not in home, "emoji 不应原样出现在页面上"
    assert "<svg" in home


def test_empty_icon_falls_back_to_vector(admin, csrf, db) -> None:
    token = csrf(admin)
    admin.post(
        "/admin/books/new",
        data={
            "title": "无图标书",
            "slug": "no-icon",
            "group": "default",
            "summary": "",
            "icon": "",
            "format": "markdown",
            "visibility": "public",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    home = admin.get("/").text
    assert "no-icon" in home
    assert "book-cover" in home
    # 空图标时用内联 SVG 兜底，而不是空白方块
    assert home.count("book-cover-fallback") >= 1
