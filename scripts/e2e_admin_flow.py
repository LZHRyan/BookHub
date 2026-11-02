#!/usr/bin/env python3
"""端到端演练：完全通过 HTTP 驱动管理端与 API，验证一条完整内容生命周期。

覆盖（任务 12.2）：
    登录 → 建 Book → 上传 Markdown 章节 → 上传 HTML 章节（含 XSS payload）
    → 发布 → API 取原文/渲染/搜索 → 替换（版本 +1、ETag 变化）→ 回滚
    → 删除（API 404 + changes 墓碑）→ 恢复 → 审计日志留痕

只用标准库，不依赖服务端代码；默认对着本机 8000 端口跑：

    python scripts/e2e_admin_flow.py --base-url http://127.0.0.1:8000 \
        --username admin --password 'AdminPass123'

失败任一步退出码 1，可直接放进流水线。会留下测试数据（Book 名带时间戳），
生产环境请勿执行。
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

MARKDOWN_V1 = """# 端到端章节

知识库端到端演练正文，关键词：初始化条款。

| 列 | 值 |
| --- | --- |
| a | 1 |
"""

MARKDOWN_V2 = """# 端到端章节

替换后的正文，关键词：替换条款。
"""

HTML_XSS = """<h1>HTML 章节</h1>
<p>正常段落</p>
<script>alert('xss')</script>
<img src=x onerror="alert(1)">
<a href="javascript:alert(1)">bad</a>
<iframe src="https://evil.example"></iframe>
<form action="/x"><input name="a"></form>
"""


class Failure(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str, *, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.steps = 0

    # ---------------------------------------------------------------- 基础

    def request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        follow: bool = False,
    ) -> tuple[int, dict[str, str], bytes]:
        url = self.base_url + path
        request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        opener = self.opener if follow else urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect()
        )
        try:
            with opener.open(request, timeout=self.timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def get(self, path: str, *, accept: str = "text/html") -> tuple[int, dict[str, str], bytes]:
        return self.request("GET", path, headers={"Accept": accept})

    def get_json(self, path: str) -> dict:
        status, _, body = self.request("GET", path, headers={"Accept": "application/json"})
        if status != 200:
            raise Failure(f"GET {path} -> {status}: {body[:300]!r}")
        return json.loads(body)

    def form(self, path: str, fields: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        payload = urllib.parse.urlencode(fields).encode()
        return self.request(
            "POST",
            path,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def csrf(self, path: str = "/admin") -> str:
        status, _, body = self.get(path)
        if status != 200:
            raise Failure(f"GET {path} -> {status}")
        match = re.search(r'name="csrf_token" value="([^"]+)"', body.decode("utf-8"))
        if not match:
            raise Failure(f"{path} 页面没有 csrf_token")
        return match.group(1)

    def upload(
        self,
        path: str,
        fields: dict[str, str],
        filename: str,
        content: bytes,
        content_type: str,
    ) -> tuple[int, dict[str, str], bytes]:
        boundary = "----bookhub" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
            )
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="upload"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        chunks.append(content)
        chunks.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        return self.request(
            "POST",
            path,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def step(client: Client, title: str, func) -> object:
    client.steps += 1
    try:
        result = func()
    except Failure as exc:
        print(f"FAIL [{client.steps:02d}] {title}: {exc}")
        raise SystemExit(1) from exc
    print(f"OK   [{client.steps:02d}] {title}")
    return result


def location_id(headers: dict[str, str], pattern: str) -> int:
    location = next((value for key, value in headers.items() if key.lower() == "location"), "")
    match = re.search(pattern, location)
    if not match:
        raise Failure(f"无法从跳转地址解析 id：{location!r}")
    return int(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser(description="BookHub 端到端演练")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()
    if not args.password:
        print("需要 --password（管理员密码）", file=sys.stderr)
        return 2

    client = Client(args.base_url)
    api_headers = {"X-API-Key": args.api_key} if args.api_key else {}

    def api(path: str, accept: str = "application/json") -> tuple[int, bytes]:
        headers = {"Accept": accept, **api_headers}
        status, _, body = client.request("GET", path, headers=headers)
        return status, body

    stamp = datetime.now(UTC).strftime("%H%M%S")
    book_title = f"E2E 演练 {stamp}"

    step(client, "登录管理端", lambda: _login(client, args.username, args.password))
    csrf = client.csrf("/admin")

    def create_book() -> int:
        status, headers, body = client.form(
            "/admin/books/new",
            {
                "title": book_title,
                "slug": f"e2e-{stamp.lower()}",
                "summary": "端到端演练数据，可删除",
                "icon": "",
                "format": "markdown",
                "visibility": "public",
                "sort_order": "",
                "csrf_token": csrf,
            },
        )
        if status != 303:
            raise Failure(f"创建 Book 返回 {status}: {body[:300]!r}")
        return location_id(headers, r"/admin/books/(\d+)")

    book_id = step(client, "新建 Book", create_book)
    book_slug = step(client, "读取 Book slug", lambda: _book_slug(client, book_id))

    def upload_markdown() -> int:
        token = client.csrf(f"/admin/books/{book_id}/chapters/new")
        status, headers, body = client.upload(
            f"/admin/books/{book_id}/chapters/new",
            {
                "title": "端到端章节",
                "slug": "e2e-md",
                "format": "markdown",
                "status": "published",
                "content": "",
                "encoding": "",
                "csrf_token": token,
            },
            "端到端章节.md",
            MARKDOWN_V1.encode("utf-8"),
            "text/markdown",
        )
        if status != 303:
            raise Failure(f"上传 Markdown 返回 {status}: {body[:300]!r}")
        return location_id(headers, r"/chapters/(\d+)")

    md_id = step(client, "上传 Markdown 章节", upload_markdown)

    def create_html_book() -> int:
        status, headers, body = client.form(
            "/admin/books/new",
            {
                "title": f"E2E HTML 书 {stamp}",
                "slug": f"e2e-html-{stamp.lower()}",
                "summary": "端到端演练数据（HTML 类型）",
                "icon": "",
                "format": "html",
                "visibility": "public",
                "sort_order": "",
                "csrf_token": csrf,
            },
        )
        if status != 303:
            raise Failure(f"创建 HTML Book 返回 {status}: {body[:300]!r}")
        return location_id(headers, r"/admin/books/(\d+)")

    html_book_id = step(client, "新建 HTML 类型 Book", create_html_book)
    html_book_slug = step(
        client, "读取 HTML Book slug", lambda: _book_slug(client, html_book_id)
    )

    def upload_html() -> int:
        token = client.csrf(f"/admin/books/{html_book_id}/chapters/new")
        status, headers, body = client.upload(
            f"/admin/books/{html_book_id}/chapters/new",
            {
                "title": "HTML 章节",
                "slug": "e2e-html",
                "format": "html",
                "status": "published",
                "content": "",
                "encoding": "",
                "csrf_token": token,
            },
            "html.html",
            HTML_XSS.encode("utf-8"),
            "text/html",
        )
        if status != 303:
            raise Failure(f"上传 HTML 返回 {status}: {body[:300]!r}")
        return location_id(headers, r"/chapters/(\d+)")

    step(client, "上传 HTML 章节（含 XSS payload）", upload_html)

    step(
        client,
        "API：Markdown Book 出现在列表且含一章",
        lambda: _expect_book_listed(client, api, book_slug),
    )
    step(
        client,
        "API：Markdown 原文与渲染结果正确",
        lambda: _expect_markdown(client, api, book_slug),
    )
    step(
        client,
        "API：HTML 原文已被净化",
        lambda: _expect_html_sanitized(client, api, html_book_slug),
    )
    step(
        client,
        "站内检索能命中章节",
        lambda: _expect_search(client, book_slug),
    )

    def replace() -> str:
        token = client.csrf(f"/admin/books/{book_id}/chapters/{md_id}")
        status, _, body = client.form(
            f"/admin/books/{book_id}/chapters/{md_id}/replace",
            {
                "title": "端到端章节",
                "slug": "e2e-md",
                "format": "markdown",
                "content": MARKDOWN_V2,
                "encoding": "",
                "base_version": "1",
                "note": "e2e 替换",
                "csrf_token": token,
            },
        )
        if status != 303:
            raise Failure(f"替换返回 {status}: {body[:300]!r}")
        payload = client.get_json(f"/api/v1/books/{book_slug}/chapters/e2e-md")
        if payload["version"] != 2:
            raise Failure(f"替换后版本号应为 2，实际 {payload['version']}")
        if "替换条款" not in payload["content_raw"]:
            raise Failure("替换后原文未更新")
        return payload["etag"] if "etag" in payload else payload["checksum"]

    step(client, "替换章节（版本 +1、内容更新）", replace)

    def rollback() -> None:
        token = client.csrf(f"/admin/books/{book_id}/chapters/{md_id}/versions")
        status, _, body = client.form(
            f"/admin/books/{book_id}/chapters/{md_id}/rollback/1", {"csrf_token": token}
        )
        if status != 303:
            raise Failure(f"回滚返回 {status}: {body[:300]!r}")
        payload = client.get_json(f"/api/v1/books/{book_slug}/chapters/e2e-md")
        if payload["version"] != 3:
            raise Failure(f"回滚应产生版本 3，实际 {payload['version']}")
        if "初始化条款" not in payload["content_raw"]:
            raise Failure("回滚后内容不是版本 1")

    step(client, "回滚到版本 1（生成新版本）", rollback)

    def delete_chapter() -> None:
        token = client.csrf(f"/admin/books/{book_id}")
        status, _, body = client.form(
            f"/admin/books/{book_id}/chapters/{md_id}/delete", {"csrf_token": token}
        )
        if status != 303:
            raise Failure(f"删除返回 {status}: {body[:300]!r}")
        code, _ = api(f"/api/v1/books/{book_slug}/chapters/e2e-md")
        if code != 404:
            raise Failure(f"删除后 API 应 404，实际 {code}")
        since = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = json.loads(api(f"/api/v1/changes?since={since}")[1])
        tomb = [
            item
            for item in payload["chapters"]
            if item["slug"] == "e2e-md" and item["book_slug"] == book_slug
        ]
        if not tomb or not tomb[0]["deleted"]:
            raise Failure("changes 未返回删除墓碑")

    step(client, "删除章节（API 404 + 墓碑）", delete_chapter)

    def restore_chapter() -> None:
        token = client.csrf("/admin/trash")
        status, _, body = client.form(
            f"/admin/books/{book_id}/chapters/{md_id}/restore", {"csrf_token": token}
        )
        if status != 303:
            raise Failure(f"恢复返回 {status}: {body[:300]!r}")
        code, body = api(f"/api/v1/books/{book_slug}/chapters/e2e-md")
        if code != 200:
            raise Failure(f"恢复后 API 应 200，实际 {code}: {body[:200]!r}")

    step(client, "从回收站恢复章节", restore_chapter)

    def audit() -> None:
        status, _, body = client.get("/admin/audit")
        if status != 200:
            raise Failure(f"审计页返回 {status}")
        text = body.decode("utf-8")
        for action in ("book.create", "chapter.create", "chapter.replace", "chapter.delete", "chapter.restore"):
            if action not in text:
                raise Failure(f"审计页缺少 {action}")

    step(client, "审计日志记录了全部动作", audit)

    print(f"\n全部 {client.steps} 步通过。测试 Book：{book_title}（/b/{book_slug}）与 {html_book_slug}")
    return 0


def _login(client: Client, username: str, password: str) -> None:
    status, headers, body = client.form(
        "/admin/login", {"username": username, "password": password, "next": ""}
    )
    if status != 303:
        raise Failure(f"登录返回 {status}: {body[:200]!r}")
    location = next((value for key, value in headers.items() if key.lower() == "location"), "")
    if "/admin" not in location:
        raise Failure(f"登录后跳转异常：{location!r}")
    time.sleep(0.05)


def _book_slug(client: Client, book_id: int) -> str:
    status, _, body = client.get(f"/admin/books/{book_id}")
    if status != 200:
        raise Failure(f"Book 管理页返回 {status}")
    text = body.decode("utf-8")
    match = re.search(r"/b/([a-z0-9-]+)", text)
    if not match:
        raise Failure("管理页里找不到 Book slug")
    return match.group(1)


def _expect_book_listed(client: Client, api, book_slug: str) -> None:
    payload = json.loads(api("/api/v1/books?page_size=100")[1])
    if not any(item["slug"] == book_slug for item in payload["items"]):
        raise Failure("新建的 Book 未出现在 /api/v1/books")
    detail = json.loads(api(f"/api/v1/books/{book_slug}")[1])
    slugs = [chapter["slug"] for chapter in detail["chapters"]]
    if slugs != ["e2e-md"]:
        raise Failure(f"目录顺序异常：{slugs}")


def _expect_markdown(client: Client, api, book_slug: str) -> None:
    code, body = api(f"/api/v1/books/{book_slug}/chapters/e2e-md?format=raw", "text/markdown")
    if code != 200 or "初始化条款" not in body.decode("utf-8"):
        raise Failure("原文通道内容不正确")
    payload = json.loads(api(f"/api/v1/books/{book_slug}/chapters/e2e-md")[1])
    if "<table>" not in payload["content_rendered"]:
        raise Failure("渲染结果缺少表格")
    if not payload["toc"]:
        raise Failure("渲染结果缺少目录")


def _expect_html_sanitized(client: Client, api, book_slug: str) -> None:
    code, body = api(f"/api/v1/books/{book_slug}/chapters/e2e-html?format=raw", "text/html")
    if code != 200:
        raise Failure(f"HTML 原文通道返回 {code}")
    text = body.decode("utf-8")
    for needle in ("<script", "onerror", "javascript:", "<iframe", "<form"):
        if needle in text.lower():
            raise Failure(f"净化后仍包含 {needle}")
    if "正常段落" not in text:
        raise Failure("净化把正常内容也删了")


def _expect_search(client: Client, book_slug: str) -> None:
    payload = client.get_json("/api/v1/search?q=" + urllib.parse.quote("初始化"))
    if not any(item["book"]["slug"] == book_slug for item in payload["items"]):
        raise Failure("检索未命中新章节")


if __name__ == "__main__":
    sys.exit(main())
