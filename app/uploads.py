"""上传读取：分块读、边读边计数，绝不先把超大文件整个读进内存。

Starlette 的 `UploadFile.read()` 不带参数时会把整份内容读成 bytes；对一个 2 GB
的文件，那意味着先吃 2 GB 内存再判断"超过 5 MiB"，结果是 OOM 而不是 413。
所有上传入口统一走 `read_limited()`：按 1 MiB 分块累加，一旦越界立刻抛 413。
"""

from __future__ import annotations

from typing import Protocol

from app.errors import PayloadTooLarge

CHUNK_SIZE = 1024 * 1024


class ReadableUpload(Protocol):
    """只依赖 `read(size)`——`starlette.UploadFile` 与测试里的假对象都满足。"""

    async def read(self, size: int = -1) -> bytes: ...


def _limit_label(max_bytes: int) -> str:
    if max_bytes >= 1024 * 1024:
        return f"{max_bytes / 1024 / 1024:.1f} MiB".replace(".0 ", " ")
    return f"{max_bytes // 1024} KiB"


async def read_limited(
    upload: ReadableUpload,
    max_bytes: int,
    *,
    label: str = "文件",
) -> bytes:
    """读完整份内容，超出 `max_bytes` 立刻抛 `PayloadTooLarge`（413）。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLarge(f"{label}超过上限（{_limit_label(max_bytes)}）")
        chunks.append(chunk)
    return b"".join(chunks)
