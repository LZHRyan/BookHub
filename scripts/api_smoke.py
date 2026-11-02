#!/usr/bin/env python3
"""管理 API 冒烟：用 API Token 跑一遍完整内容生命周期。

    python scripts/api_smoke.py --base-url http://localhost:8000 --token "bh_xxx"

只依赖标准库；任一步失败退出码 1。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"
TOKEN = ""
STEPS = 0


def call(method: str, path: str, *, body: dict | None = None, headers: dict[str, str] | None = None,
         raw: bytes | None = None, content_type: str | None = None) -> tuple[int, dict, dict]:
    url = BASE + path
    data = None
    merged = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        merged["Content-Type"] = "application/json"
    elif raw is not None:
        data = raw
        merged["Content-Type"] = content_type or "application/octet-stream"
    if headers:
        merged.update(headers)
    request = urllib.request.Request(url, data=data, method=method, headers=merged)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read() or b"{}")
            return response.status, payload, dict(response.headers)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(text or "{}")
        except json.JSONDecodeError:
            payload = {"raw": text}
        return exc.code, payload, dict(exc.headers)


def tiny_png() -> bytes:
    """一张 1x1 的合法 PNG：不依赖外部素材，浏览器也能正常解码。"""
    import binascii
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", binascii.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x4f\x46\xe5", 9))
        + chunk(b"IEND", b"")
    )


def fetch_status(path: str) -> tuple[int, bytes, dict]:
    """取二进制资源（图片）时用：只回状态码、原始字节与响应头，不解析 JSON。"""
    request = urllib.request.Request(BASE + path, method="GET", headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def step(title: str, fn):
    global STEPS
    STEPS += 1
    try:
        detail = fn()
    except AssertionError as exc:
        print(f"FAIL [{STEPS:02d}] {title}: {exc}")
        raise SystemExit(1) from exc
    print(f"OK   [{STEPS:02d}] {title}{('  · ' + detail) if detail else ''}")


def multipart(fields: dict[str, str], filename: str, content: bytes, *,
              field: str = "file", content_type: str = "text/markdown") -> tuple[bytes, str]:
    boundary = "----bookhub" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )
    chunks.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
    )
    chunks.append(content)
    chunks.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def main() -> int:
    global BASE, TOKEN
    parser = argparse.ArgumentParser(description="BookHub 管理 API 冒烟")
    parser.add_argument("--base-url", default=BASE)
    parser.add_argument("--token", required=True, help="管理 API Token（bh_ 开头）")
    args = parser.parse_args()
    BASE = args.base_url.rstrip("/")
    TOKEN = args.token

    stamp = uuid.uuid4().hex[:6]
    book_slug = ""
    chapter_slug = ""
    section_slug = ""
    media_url = ""

    def meta():
        status, body, _ = call("GET", "/api/v1/admin/meta")
        assert status == 200, f"{status} {body}"
        assert "write" in body["token"]["scopes"] or "admin" in body["token"]["scopes"], body["token"]
        return f"scopes={body['token']['scopes']}"

    def create_book():
        nonlocal book_slug
        # Book 必须属于某个分组（book-groups 规格），先取一个已有分组的 slug
        status, groups, _ = call("GET", "/api/v1/admin/groups")
        assert status == 200, f"{status} {groups}"
        items = groups.get("items") or []
        assert items, "站点里没有任何分组，无法创建 Book"
        group_slug = items[0]["slug"]
        status, body, _ = call(
            "POST",
            "/api/v1/admin/books",
            body={
                "title": f"API 冒烟 {stamp}",
                "format": "markdown",
                "summary": "smoke",
                "group": group_slug,
            },
            headers={"Idempotency-Key": f"smoke-book-{stamp}"},
        )
        assert status == 201, f"{status} {body}"
        book_slug = body["slug"]
        return f"slug={book_slug} group={group_slug}"

    def upload_chapter():
        nonlocal chapter_slug, section_slug
        content, content_type = multipart(
            {"title": "冒烟章节", "status": "published", "note": "smoke"},
            "smoke.md",
            "# 冒烟\n\n这是 API 冒烟写入的内容。\n".encode(),
        )
        status, body, _ = call(
            "POST",
            f"/api/v1/admin/books/{book_slug}/chapters",
            raw=content,
            content_type=content_type,
            headers={"Idempotency-Key": f"smoke-chapter-{stamp}"},
        )
        assert status == 201, f"{status} {body}"
        chapter_slug = body["slug"]
        sections = body.get("sections") or []
        assert sections, f"章节下面没有生成节：{body}"
        section_slug = sections[0]["slug"]
        return f"chapter={chapter_slug} section={section_slug} v{sections[0]['version']}"

    def replace_chapter():
        # 正文与版本都在节上：章级 PATCH 现在只改标题 / slug
        status, body, _ = call(
            "PATCH",
            f"/api/v1/admin/books/{book_slug}/chapters/{chapter_slug}/sections/{section_slug}",
            body={"content": "# 冒烟 v2", "base_version": 1},
        )
        assert status == 200, f"{status} {body}"
        assert body["version"] == 2, body
        return f"v{body['version']}"

    def rollback():
        status, body, _ = call(
            "POST",
            f"/api/v1/admin/books/{book_slug}/chapters/{chapter_slug}"
            f"/sections/{section_slug}/rollback/1",
        )
        assert status == 200, f"{status} {body}"
        assert body["version"] == 3, body
        return f"v{body['version']}"

    def dry_run_delete():
        status, body, _ = call(
            "POST", f"/api/v1/admin/books/{book_slug}/chapters/{chapter_slug}/delete?dry_run=true"
        )
        assert status == 200, f"{status} {body}"
        assert body.get("dry_run") is True, body
        assert call("GET", f"/api/v1/books/{book_slug}/chapters/{chapter_slug}")[0] == 200
        return "未落库"

    def confirm_delete():
        status, body, _ = call(
            "POST", f"/api/v1/admin/books/{book_slug}/chapters/{chapter_slug}/delete?confirm=true"
        )
        assert status == 200, f"{status} {body}"
        assert call("GET", f"/api/v1/books/{book_slug}/chapters/{chapter_slug}")[0] == 404
        return "已软删除"

    def restore():
        status, body, _ = call("POST", f"/api/v1/admin/books/{book_slug}/chapters/{chapter_slug}/restore")
        assert status == 200, f"{status} {body}"
        assert call("GET", f"/api/v1/books/{book_slug}/chapters/{chapter_slug}")[0] == 200
        return "已恢复"

    def audit():
        status, body, _ = call("GET", "/api/v1/admin/audit?actor=api")
        assert status == 200, f"{status} {body}"
        assert body["total"] >= 1, body
        return f"{body['total']} 条 api 来源记录"

    def upload_media():
        nonlocal media_url
        png = tiny_png()
        content, content_type = multipart(
            {}, "smoke.png", png, field="file", content_type="image/png"
        )
        status, body, _ = call(
            "POST",
            f"/api/v1/admin/books/{book_slug}/media",
            raw=content,
            content_type=content_type,
            headers={"Idempotency-Key": f"smoke-media-{stamp}"},
        )
        assert status == 201, f"{status} {body}"
        assert body["kind"] == "image", body
        media_url = body["url"]
        return f"url={media_url}"

    def reference_media():
        status, body, _ = call(
            "PATCH",
            f"/api/v1/admin/books/{book_slug}/chapters/{chapter_slug}/sections/{section_slug}",
            body={"content": f"# 冒烟\n\n![架构]({media_url})\n"},
        )
        assert status == 200, f"{status} {body}"
        listed = call("GET", f"/api/v1/admin/books/{book_slug}/media")
        assert listed[0] == 200, listed
        assert listed[1]["items"][0]["referenced"] is True, listed[1]
        status, data, headers = fetch_status(media_url)
        lowered = {key.lower(): value for key, value in headers.items()}
        assert status == 200, f"{status} {data[:80]!r}"
        assert data.startswith(b"\x89PNG"), data[:8]
        assert "immutable" in lowered.get("cache-control", ""), headers
        return "已引用且公开可读"

    def cleanup_media():
        status, body, _ = call("POST", f"/api/v1/admin/books/{book_slug}/media/cleanup")
        assert status == 200, f"{status} {body}"
        assert body["applied"] is False, body
        assert body["deleted"] == [], body
        return "无可清理资源（预览）"

    step("读取 meta（作用域/限制）", meta)
    step("创建 Book", create_book)
    step("上传 Markdown 章节", upload_chapter)
    step("替换内容（版本 +1）", replace_chapter)
    step("回滚到 v1（生成 v3）", rollback)
    step("上传图片", upload_media)
    step("正文引用图片并可公开读取", reference_media)
    step("清理预览（不误删被引用资源）", cleanup_media)
    step("删除预览（dry_run）", dry_run_delete)
    step("确认删除", confirm_delete)
    step("从回收站恢复", restore)
    step("审计可追溯", audit)

    print(f"\n全部 {STEPS} 步通过。测试 Book：{BASE}/b/{book_slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
