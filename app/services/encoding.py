"""上传文件的编码识别与文本归一化。"""

from __future__ import annotations

from pathlib import Path

UTF8_BOM = b"\xef\xbb\xbf"
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd", ".txt"}
HTML_SUFFIXES = {".html", ".htm", ".xhtml"}


class EncodingError(ValueError):
    """无法解码上传内容。"""


class UnsupportedFormat(ValueError):
    """扩展名不在白名单内。"""


class EmptyContent(ValueError):
    """上传内容为空。"""


def decode_bytes(data: bytes) -> str:
    """按 UTF-8 BOM → UTF-8 → GB18030 顺序解码，失败即报错。

    GB18030 几乎能吃下任意字节，所以额外拒绝包含 NUL 的内容，
    否则二进制文件会被"成功"解码成乱码。
    """
    if not data:
        raise EmptyContent("文件内容为空")
    if b"\x00" in data:
        raise EncodingError("文件疑似二进制内容，无法作为文本识别")

    if data.startswith(UTF8_BOM):
        try:
            return _normalize(data[len(UTF8_BOM) :].decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise EncodingError("文件带 UTF-8 BOM 但内容不是合法 UTF-8") from exc

    for encoding in ("utf-8", "gb18030"):
        try:
            return _normalize(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    raise EncodingError("无法识别文件编码（已尝试 UTF-8 与 GB18030），请另存为 UTF-8 后重试")


def decode_with_hint(data: bytes, encoding: str | None = None) -> str:
    """表单显式指定编码时优先使用该编码。"""
    if not encoding:
        return decode_bytes(data)
    try:
        return _normalize(data.decode(encoding))
    except (LookupError, UnicodeDecodeError) as exc:
        raise EncodingError(f"按指定编码 {encoding} 无法解码该文件") from exc


def _normalize(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_text(text: str) -> str:
    return _normalize(text or "")


def detect_format(filename: str) -> str:
    """按扩展名判定节的内容格式；不支持时抛 UnsupportedFormat。"""
    suffix = Path(filename or "").suffix.lower()
    if suffix in MARKDOWN_SUFFIXES:
        return "markdown"
    if suffix in HTML_SUFFIXES:
        return "html"
    raise UnsupportedFormat(f"不支持的文件类型 {suffix or '(无扩展名)'}，仅接受 .md/.markdown/.txt 或 .html/.htm")


def title_from_filename(filename: str) -> str:
    return Path(filename or "").stem.strip() or "未命名节"
