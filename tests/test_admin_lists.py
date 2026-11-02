"""管理端列表的卡片化：分组页与 Book 列表不再用表格。"""

from __future__ import annotations

from app.services import book_groups
from app.services import books as books_service


def _group(db, title, slug):
    return book_groups.create(db, title=title, slug_raw=slug)


def _book(db, title, group):
    book = books_service.create_book(db, title=title, group=group)
    db.commit()
    return book


def test_groups_page_uses_cards(admin, db) -> None:
    group = _group(db, "卡片组甲", "card-a")
    _book(db, "卡片书甲", "card-a")
    db.commit()

    html = admin.get("/admin/groups").text
    assert "<table" not in html
    assert "admin-card-grid" in html
    assert "group-card" in html
    # 仍保留「点数量看该组 Book」的入口
    assert '?group=card-a">1</a>' in html
    # 删除仍是带二次确认的表单
    assert "data-confirm" in html
    assert "admin-card-foot" in html
    assert group.title in html


def test_book_list_uses_cards(admin, db) -> None:
    _group(db, "卡片组乙", "card-b")
    _book(db, "卡片书乙", "card-b")
    db.commit()

    html = admin.get("/admin").text
    assert "<table" not in html
    assert "admin-card-grid" in html
    assert "book-admin-card" in html
    assert "卡片书乙" in html
    assert "编辑" in html and "查看" in html and "删除" in html
    assert "近 7 天访问" in html


def test_book_list_filter_still_works_with_cards(admin, db) -> None:
    _group(db, "卡片组丙", "card-c")
    _group(db, "卡片组丁", "card-d")
    _book(db, "丙书", "card-c")
    _book(db, "丁书", "card-d")
    db.commit()

    page = admin.get("/admin?group=card-c").text
    assert "丙书" in page
    assert "丁书" not in page
    assert "清除筛选" in page


def test_group_card_order_controls_are_inline(admin, db) -> None:
    _group(db, "卡片组戊", "card-e")
    _group(db, "卡片组己", "card-f")
    db.commit()
    html = admin.get("/admin/groups").text
    # 上下移仍是两个独立表单（一次点击一次提交），但放在卡片头部的工具区
    assert html.count("/move") >= 4
    assert 'aria-label="上移分组' in html

def test_filter_bars_align_controls_to_inputs(admin, db) -> None:
    """筛选栏里的按钮要对齐到输入框（flex-end），而不是对齐到「标签+输入框」整体。"""
    _group(db, "对齐组", "align-a")
    _book(db, "对齐书", "align-a")
    db.commit()

    for path in ("/admin", "/admin/audit"):
        html = admin.get(path).text
        assert "filter-bar" in html, path


def test_filter_bar_css_aligns_to_bottom() -> None:
    from pathlib import Path

    css = Path("app/static/style.css").read_text(encoding="utf-8")
    assert ".filter-bar { align-items: flex-end; }" in css
    assert ".filter-bar .btn { min-height: 38px; }" in css
def test_small_option_sets_use_radio_cards(admin, db) -> None:
    """≤5 个固定选项不再用下拉，改成可并排对比的单选卡片。"""
    _group(db, "选项组", "choice-a")
    book = _book(db, "选项书", "choice-a")
    db.commit()

    new_book = admin.get("/admin/books/new").text
    assert '<fieldset class="choices"' in new_book
    for name in ("format", "html_view", "visibility"):
        assert f'type="radio" name="{name}"' in new_book
        assert f'<select id="{name}"' not in new_book
    # 分组是动态列表，仍保留下拉
    assert '<select id="group" name="group"' in new_book

    new_chapter = admin.get(f"/admin/books/{book.id}/chapters/new").text
    for name in ("status", "encoding"):
        assert f'type="radio" name="{name}"' in new_chapter
        assert f'<select id="{name}"' not in new_chapter

    users = admin.get("/admin/users").text
    assert 'type="radio" name="role"' in users
    assert '<select id="new-role"' not in users


def test_format_choice_locked_once_chapters_exist(admin, db) -> None:
    """整本单一格式：有章之后文档类型锁定，radio 禁用并靠 hidden 字段保留原值。"""
    _group(db, "锁定组", "choice-b")
    book = _book(db, "锁定书", "choice-b")
    from app.services import chapters as chapters_service

    chapters_service.create_chapter_with_section(db, book, title="第一章", raw="# x")
    db.commit()

    html = admin.get(f"/admin/books/{book.id}/edit").text
    assert 'name="format" value="markdown" disabled' in html or "disabled" in html
    assert '<input type="hidden" name="format" value="markdown">' in html
    assert "已锁定" in html


def test_users_list_is_row_cards_without_table(admin, db) -> None:
    """账号列表用整行卡片：没有表格、没有横向滚动的宽表；操作区在行内。"""
    html = admin.get("/admin/users").text
    assert "<table" not in html
    assert "user-list" in html
    assert "user-row" in html
    # 重置密码的输入框仍在行内表单里（不能退化成弹窗/新页面）
    assert 'name="password"' in html
    assert "重置密码" in html