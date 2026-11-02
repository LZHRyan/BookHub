"""Book 图标：预置 emoji 清单与表单面板。"""

from __future__ import annotations

import re

from app.services.emoji import EMOJI_GROUPS, all_emojis, is_known_emoji, total_emojis


def test_catalog_shape() -> None:
    assert len(EMOJI_GROUPS) >= 6, "至少要覆盖 6 个分组"
    emojis = all_emojis()
    assert total_emojis() >= 100, f"预置图标不足 100 个，当前 {total_emojis()}"
    assert len(emojis) == len(set(emojis)), "存在重复图标"
    for _, items in EMOJI_GROUPS:
        assert items, "分组不能为空"
        for emoji, label in items:
            assert emoji and label
            assert len(emoji) <= 16, f"{emoji} 过长，会被输入框截断"


def test_is_known_emoji() -> None:
    assert is_known_emoji("📘") is True
    assert is_known_emoji(" 📘 ") is True
    assert is_known_emoji("🎉") is True
    assert is_known_emoji("A") is False
    assert is_known_emoji("") is False


def test_book_form_renders_picker(admin) -> None:
    html = admin.get("/admin/books/new").text
    options = re.findall(r'data-emoji="', html)
    assert len(options) >= 100, f"面板只渲染了 {len(options)} 个图标"
    assert "从预置图标中选择" in html
    assert "data-emoji-preview" in html
    assert "data-emoji-clear" in html
    # 面板不允许引入外部资源或内联脚本
    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html, re.IGNORECASE)
    assert inline == []


def test_create_book_with_picked_emoji(admin, csrf, db) -> None:
    token = csrf(admin)
    response = admin.post(
        "/admin/books/new",
        data={
            "title": "图标书",
            "slug": "icon-book",
            "group": "default",
            "summary": "",
            "icon": "🎯",
            "format": "markdown",
            "visibility": "public",
            "sort_order": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    home = admin.get("/").text
    assert "🎯" in home, "首页应显示选中的图标"
    payload = admin.get("/api/v1/books/icon-book").json()
    assert payload["icon"] == "🎯"


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
            "sort_order": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    home = admin.get("/").text
    assert "no-icon" in home
    assert "book-cover" in home
    # 空图标时用内联 SVG 兜底，而不是空白方块
    assert home.count("book-cover-fallback") >= 1
