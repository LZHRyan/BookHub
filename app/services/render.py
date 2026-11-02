"""Markdown/HTML 渲染管线：CommonMark → 净化 → 高亮 → 锚点与 TOC。"""

from __future__ import annotations

import html as html_lib
import re
from collections import Counter

import nh3
from markdown_it import MarkdownIt
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from app.services.slug import anchor_slug

ALLOWED_TAGS: set[str] = {
    "a", "abbr", "b", "blockquote", "br", "caption", "code", "col", "colgroup",
    "dd", "del", "details", "div", "dl", "dt", "em", "figcaption", "figure",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "input", "ins", "kbd",
    "li", "mark", "ol", "p", "pre", "q", "s", "samp", "section", "small", "span",
    "strong", "sub", "summary", "sup", "table", "tbody", "td", "tfoot", "th",
    "thead", "tr", "u", "ul", "var",
}

ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {"id", "class", "title", "align", "lang", "dir"},
    "a": {"href", "title", "target", "name"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "input": {"type", "checked", "disabled", "class"},
    "ol": {"start", "type"},
    "td": {"colspan", "rowspan", "align"},
    "th": {"colspan", "rowspan", "align", "scope"},
    "col": {"span"},
    "colgroup": {"span"},
    "details": {"open"},
}

ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}

_FORMATTER = HtmlFormatter(nowrap=True)
_HEADING_RE = re.compile(r"<h([1-6])((?:\s[^>]*)?)>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)
_ID_ATTR_RE = re.compile(r"\bid\s*=\s*\"([^\"]*)\"", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\u00a0]+")


def _highlight(code: str, lang: str, _attrs: str) -> str:
    if not lang:
        return ""
    try:
        lexer = get_lexer_by_name(lang, stripall=False)
    except ClassNotFound:
        return ""
    return highlight(code, lexer, _FORMATTER)


def build_markdown() -> MarkdownIt:
    md = MarkdownIt(
        "commonmark",
        {"html": False, "linkify": False, "typographer": False, "breaks": False},
    )
    md.enable(["table", "strikethrough"])
    md.use(tasklists_plugin, enabled=False)
    md.use(footnote_plugin)
    md.use(deflist_plugin)
    md.options["highlight"] = _highlight
    return md


MARKDOWN = build_markdown()


def sanitize_html(fragment: str) -> str:
    """白名单净化。脚本、事件属性、危险协议、iframe/form 一律剔除。"""
    if not fragment:
        return ""
    return nh3.clean(
        fragment,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )


def _add_token_anchors(tokens) -> list[dict[str, object]]:
    toc: list[dict[str, object]] = []
    used: set[str] = set()
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].type != "inline":
            continue
        text = tokens[index + 1].content.strip()
        anchor = anchor_slug(text, used)
        token.attrSet("id", anchor)
        toc.append({"level": int(token.tag[1]), "text": text, "anchor": anchor})
    return toc


def render_markdown(raw: str) -> tuple[str, list[dict[str, object]]]:
    text = raw or ""
    tokens = MARKDOWN.parse(text)
    toc = _add_token_anchors(tokens)
    rendered = MARKDOWN.renderer.render(tokens, MARKDOWN.options, {})
    return sanitize_html(rendered), toc


def _inject_html_anchors(fragment: str) -> tuple[str, list[dict[str, object]]]:
    toc: list[dict[str, object]] = []
    used: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        level, attrs, inner = match.group(1), match.group(2), match.group(3)
        text = html_lib.unescape(_TAG_RE.sub("", inner)).strip()
        existing = _ID_ATTR_RE.search(attrs or "")
        if existing and existing.group(1).strip():
            anchor = existing.group(1).strip()
            if anchor in used:
                anchor = anchor_slug(text, used)
                attrs_new = _ID_ATTR_RE.sub(f'id="{anchor}"', attrs, count=1)
            else:
                used.add(anchor)
                attrs_new = attrs
        else:
            anchor = anchor_slug(text, used)
            attrs_new = f'{attrs} id="{anchor}"' if attrs else f' id="{anchor}"'
        toc.append({"level": int(level), "text": text, "anchor": anchor})
        return f"<h{level}{attrs_new}>{inner}</h{level}>"

    updated = _HEADING_RE.sub(replace, fragment or "")
    return updated, toc


def render_html_document(raw: str) -> tuple[str, list[dict[str, object]]]:
    """HTML 章节：先净化再补锚点，保证净化后的内容才是最终产物。"""
    return _inject_html_anchors(sanitize_html(raw or ""))


def public_source(raw: str, fmt: str) -> str:
    """对外"原文"通道的内容：HTML 章节返回净化后的版本，Markdown 原样返回。

    管理端仍保留管理员上传的原始内容（`content_raw`），这里只是不把未净化的
    HTML 交到站外调用方手里。
    """
    if fmt == "html":
        return sanitize_html(raw or "")
    return raw or ""


def render_content(raw: str, fmt: str) -> tuple[str, list[dict[str, object]]]:
    if fmt == "html":
        return render_html_document(raw)
    return render_markdown(raw)


def to_plain_text(rendered_html: str) -> str:
    """供检索与字数统计使用的纯文本。"""
    text = _TAG_RE.sub(" ", rendered_html or "")
    text = html_lib.unescape(text)
    text = _WS_RE.sub(" ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def count_words(plain: str) -> int:
    """中文按字计，英文按词计——够用的粗略字数。"""
    cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", plain))
    words = len(re.findall(r"[A-Za-z0-9_]+", plain))
    return cjk + words


def heading_levels(toc: list[dict[str, object]]) -> list[int]:
    return [int(item["level"]) for item in toc]


def toc_summary(toc: list[dict[str, object]]) -> Counter[int]:
    return Counter(heading_levels(toc))
