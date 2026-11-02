"""生成 Pygments 高亮样式：亮/暗两套，跟随 data-theme。

产物提交进仓库（容器内不装生成脚本的运行依赖，Pygments 本来就在运行依赖里）。
"""

from __future__ import annotations

import re
from pathlib import Path

from pygments.formatters import HtmlFormatter
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound

SELECTOR = ".prose pre code"
LIGHT_STYLE = "default"
DARK_STYLE = "github-dark"
FALLBACK_DARK = "native"
TARGET = Path(__file__).resolve().parents[1] / "app" / "static" / "pygments.css"


def pick_dark_style() -> str:
    try:
        get_style_by_name(DARK_STYLE)
        return DARK_STYLE
    except ClassNotFound:
        return FALLBACK_DARK


def defs(style: str, selector: str) -> str:
    """生成样式，并把基础选择器上的背景色去掉（背景由设计系统掌管）。"""
    css = HtmlFormatter(style=style).get_style_defs(selector)
    return re.sub(
        rf"({re.escape(selector)}\s*\{{[^}}]*?)\bbackground(-color)?:[^;}}]*;?",
        r"\1",
        css,
    )


def main() -> None:
    dark = pick_dark_style()
    light_css = defs(LIGHT_STYLE, SELECTOR)
    dark_css = defs(dark, ':root[data-theme="dark"] ' + SELECTOR)
    dark_auto_css = defs(dark, ":root:not([data-theme]) " + SELECTOR)

    css = (
        "/* 由 scripts/gen_pygments.py 生成，请勿手工修改。\n"
        f" * 亮色：{LIGHT_STYLE} / 暗色：{dark}\n"
        " * 背景与边框由 style.css 的 --bg-subtle / --border 控制，这里只管 token 颜色。*/\n\n"
        + light_css
        + "\n\n/* 手动选择暗色 */\n"
        + dark_css
        + "\n\n/* 跟随系统暗色（未手动选择时） */\n@media (prefers-color-scheme: dark) {\n"
        + dark_auto_css
        + "\n}\n"
    )
    TARGET.write_text(css, encoding="utf-8")
    print(f"wrote {TARGET} ({len(css)} chars, dark={dark})")


if __name__ == "__main__":
    main()
