"""渲染管线：Markdown 扩展、锚点、TOC 与 HTML 净化。"""

from __future__ import annotations

import pytest

from app.services.encoding import (
    EmptyContent,
    EncodingError,
    UnsupportedFormat,
    decode_bytes,
    detect_format,
    title_from_filename,
)
from app.services.render import render_content, render_html_document, render_markdown, to_plain_text
from app.services.slug import slugify, unique_slug


def test_markdown_table_and_strikethrough() -> None:
    html, _ = render_markdown("| a | b |\n| --- | --- |\n| 1 | 2 |\n\n~~old~~")
    assert "<table>" in html
    assert "<s>old</s>" in html


def test_markdown_tasklist_state() -> None:
    html, _ = render_markdown("- [x] done\n- [ ] todo")
    assert 'checked="checked"' in html
    assert html.count("<input") == 2


def test_code_highlight_and_escaping() -> None:
    html, _ = render_markdown("```python\ndef f(x):\n    return x < 2\n```")
    assert "<pre>" in html
    assert 'class="language-python"' in html
    assert "&lt;" in html
    assert "<span" in html


def test_unknown_language_still_renders() -> None:
    html, _ = render_markdown("```nope-lang\nplain <b>\n```")
    assert "plain" in html
    assert "&lt;b&gt;" in html


def test_heading_anchors_and_duplicates() -> None:
    html, toc = render_markdown("# 部署\n\n## 部署\n\n### Guide")
    assert 'id="部署"' in html
    assert 'id="部署-2"' in html
    assert [item["level"] for item in toc] == [1, 2, 3]
    assert toc[0]["anchor"] != toc[1]["anchor"]


def test_markdown_raw_html_not_executed() -> None:
    html, _ = render_markdown("<script>alert(1)</script>\n\n正常文本")
    assert "<script" not in html
    assert "正常文本" in html


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        '<a href="javascript:alert(1)">x</a>',
        '<iframe src="https://evil.example"></iframe>',
        '<form action="/x"><input name="a"></form>',
        '<object data="x"></object>',
        '<div onclick="alert(1)">click</div>',
    ],
)
def test_html_sanitizer_removes_dangerous_markup(payload: str) -> None:
    cleaned, _ = render_html_document(payload)
    lowered = cleaned.lower()
    assert "<script" not in lowered
    assert "onerror" not in lowered
    assert "onclick" not in lowered
    assert "javascript:" not in lowered
    assert "<iframe" not in lowered
    assert "<object" not in lowered
    assert "<form" not in lowered


def test_html_sanitizer_keeps_structure() -> None:
    cleaned, toc = render_html_document(
        "<h1>标题</h1><p>文本</p><table><tr><th>a</th></tr></table><pre><code>code</code></pre>"
    )
    assert "<h1 id=" in cleaned
    assert "<table>" in cleaned
    assert "<code>code</code>" in cleaned
    assert toc[0]["text"] == "标题"


def test_render_content_switches_format() -> None:
    md_html, _ = render_content("# T", "markdown")
    html_doc, _ = render_content("<h1>T</h1>", "html")
    assert md_html.startswith("<h1")
    assert html_doc.startswith("<h1")


def test_plain_text_and_word_count() -> None:
    html, _ = render_markdown("# 标题\n\nhello world 中文")
    plain = to_plain_text(html)
    assert "标题" in plain
    assert "<" not in plain


def test_encoding_utf8_bom_stripped() -> None:
    text = decode_bytes("\ufeff中文".encode("utf-8"))
    assert text == "中文"


def test_encoding_gb18030() -> None:
    assert decode_bytes("部署指南".encode("gb18030")) == "部署指南"


def test_encoding_rejects_binary() -> None:
    with pytest.raises(EncodingError):
        decode_bytes(b"\x00\x01\x02binary")


def test_encoding_rejects_empty() -> None:
    with pytest.raises(EmptyContent):
        decode_bytes(b"")


def test_detect_format_and_title() -> None:
    assert detect_format("a.md") == "markdown"
    assert detect_format("a.HTML") == "html"
    with pytest.raises(UnsupportedFormat):
        detect_format("a.pdf")
    assert title_from_filename("部署指南.md") == "部署指南"


def test_slugify_and_unique() -> None:
    assert slugify("Ops_Handbook 2024") == "ops-handbook-2024"
    assert slugify("运维手册") == ""
    assert unique_slug("", lambda candidate: False, prefix="book").startswith("book-")
    taken = {"guide"}
    assert unique_slug("guide", lambda candidate: candidate in taken, prefix="book") == "guide-2"
