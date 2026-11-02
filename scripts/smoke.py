#!/usr/bin/env python3
"""BookHub 部署冒烟脚本（纯标准库，不需要装任何依赖）。

对运行中的实例按顺序验证：
    /healthz → /readyz → /api/v1/site → /api/v1/books → Book 详情
    → 首章（JSON + 原文）→ /api/v1/search → /api/v1/changes

每一步打印 OK/FAIL 与关键字段；任一步失败，退出码为 1，可直接放进部署流水线。

用法：
    python scripts/smoke.py
    python scripts/smoke.py --base-url http://wiki.internal:8000
    python scripts/smoke.py --base-url https://wiki.example.com/bookhub --api-key "$BOOKHUB_API_KEY"
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 15.0
USER_AGENT = "bookhub-smoke/1.0"


class SmokeError(RuntimeError):
    """单个步骤失败。由 step() 捕获并记成 FAIL。"""


# ---------------------------------------------------------------- HTTP 基础


def request(
    url: str,
    *,
    api_key: str = "",
    accept: str = "application/json",
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, str, bytes]:
    """发一次 GET，返回 (状态码, Content-Type, body)。非 2xx 抛 SmokeError。"""
    headers = {"Accept": accept, "User-Agent": USER_AGENT}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        raise SmokeError(f"HTTP {exc.code} {_short(exc.read())}") from None
    except urllib.error.URLError as exc:
        raise SmokeError(f"连接失败（{exc.reason}）——服务起了吗？端口对吗？") from None
    except TimeoutError:
        raise SmokeError(f"请求超时（>{timeout}s）") from None


def _short(body: bytes, limit: int = 300) -> str:
    text = body.decode("utf-8", "replace").strip().replace("\r", " ").replace("\n", " ")
    return text[:limit] + ("…" if len(text) > limit else "")


def get_json(url: str, *, api_key: str = "", timeout: float = DEFAULT_TIMEOUT) -> dict:
    status, ctype, body = request(url, api_key=api_key, timeout=timeout)
    if status != 200:
        raise SmokeError(f"期望 200，实际 {status}")
    if "json" not in ctype.lower():
        raise SmokeError(f"期望 JSON 响应，实际 Content-Type={ctype!r}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SmokeError(f"响应不是合法 JSON：{exc}") from None
    if not isinstance(payload, dict):
        raise SmokeError(f"期望 JSON 对象，实际 {type(payload).__name__}")
    return payload


# ---------------------------------------------------------------- 报告


class Reporter:
    """收集 OK/FAIL，最后统一出退出码。"""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def ok(self, title: str, detail: str = "") -> None:
        print(f"  OK   {title}" + (f"  ·  {detail}" if detail else ""))

    def fail(self, title: str, detail: str = "") -> None:
        print(f"  FAIL {title}  ·  {detail}")
        self.failures.append(f"{title}: {detail}")

    def skip(self, title: str, reason: str) -> None:
        print(f"  SKIP {title}  ·  {reason}")


FAILED = object()


def step(reporter: Reporter, title: str, func):
    """跑一个步骤。

    func 返回 (关键字段摘要, 后续步骤要用的值)。
    成功：打印 OK + 摘要，返回那个值；失败：打印 FAIL，返回 FAILED 哨兵。
    """
    try:
        detail, value = func()
    except SmokeError as exc:
        reporter.fail(title, str(exc))
        return FAILED
    reporter.ok(title, detail or "")
    return value


def _q(value: str) -> str:
    """拼查询串时统一 encode，中文标题也能安全进 URL。"""
    return urllib.parse.quote(value, safe="")


def _first_query(title: str) -> str:
    """用标题的第一个词当检索词；中文标题没有空格且可能只有一个字，
    退化为前两个字（二元组能命中），最后兜底用整串。"""
    parts = title.split()
    if parts and len(parts[0]) >= 2:
        return parts[0]
    if len(title) >= 2:
        return title[:2]
    return title

# ---------------------------------------------------------------- 各步骤
# 每个函数返回 (打印用的关键字段, 后续步骤要用的值)；失败抛 SmokeError。


def _health(base: str, timeout: float):
    payload = get_json(base + "/healthz", timeout=timeout)
    return f"status={payload.get('status')} version={payload.get('version')}", payload


def _ready(base: str, timeout: float):
    payload = get_json(base + "/readyz", timeout=timeout)
    return f"status={payload.get('status')} version={payload.get('version')}", payload


def _site(api: str, api_key: str, timeout: float):
    payload = get_json(api + "/site", api_key=api_key, timeout=timeout)
    caps = payload.get("capabilities") or {}
    return (
        f"name={payload.get('name')} version={payload.get('version')} "
        f"api_key_required={caps.get('api_key_required')}",
        payload,
    )


def _books(api: str, api_key: str, timeout: float):
    payload = get_json(api + "/books", api_key=api_key, timeout=timeout)
    items = payload.get("items") or []
    if not items:
        raise SmokeError("没有任何已发布 Book（先上传一本，或在 .env 设 SEED_DEMO=true 后重启）")
    slugs = [item["slug"] for item in items if item.get("slug")]
    if not slugs:
        raise SmokeError("Book 列表的条目缺少 slug 字段")
    return f"total={payload.get('total')} 首个={slugs[0]}", slugs


def _book(api: str, book_ref: str, api_key: str, timeout: float):
    payload = get_json(f"{api}/books/{_q(book_ref)}", api_key=api_key, timeout=timeout)
    chapters = payload.get("chapters") or []
    if not chapters:
        raise SmokeError(f"Book {book_ref} 下没有已发布章节（新章节默认是草稿，需要先发布）")
    first = chapters[0]
    if not first.get("slug"):
        raise SmokeError("章节目录条目缺少 slug 字段")
    return (
        f"title={payload.get('title')} chapter_count={len(chapters)} 首章={first['slug']}",
        (payload, first["slug"]),
    )


def _chapter(api: str, book_ref: str, chapter_ref: str, api_key: str, timeout: float):
    payload = get_json(
        f"{api}/books/{_q(book_ref)}/chapters/{_q(chapter_ref)}", api_key=api_key, timeout=timeout
    )
    raw = payload.get("content_raw")
    rendered = payload.get("content_rendered")
    if not isinstance(raw, str) or not raw.strip():
        raise SmokeError("JSON 响应里 content_raw 缺失或为空")
    if not isinstance(rendered, str) or not rendered.strip():
        raise SmokeError("JSON 响应里 content_rendered 缺失或为空（渲染缓存没写库？）")
    if "<script" in rendered.lower():
        raise SmokeError("渲染结果里出现 <script>，HTML 净化没生效——请立刻排查")
    return (
        f"title={payload.get('title')} version={payload.get('version')} "
        f"raw={len(raw)}字符 rendered={len(rendered)}字符",
        payload,
    )


def _chapter_raw(api: str, book_ref: str, chapter_ref: str, api_key: str, timeout: float):
    url = f"{api}/books/{_q(book_ref)}/chapters/{_q(chapter_ref)}?format=raw"
    status, ctype, body = request(url, api_key=api_key, accept="text/markdown", timeout=timeout)
    if status != 200:
        raise SmokeError(f"期望 200，实际 {status}")
    text = body.decode("utf-8", "replace")
    if not text.strip():
        raise SmokeError("原文响应为空")
    head = text.strip().splitlines()[0][:40]
    return f"content-type={ctype.split(';')[0]} 长度={len(text)} 首行={head!r}", text


def _search(api: str, query: str, api_key: str, timeout: float):
    payload = get_json(f"{api}/search?q={_q(query)}", api_key=api_key, timeout=timeout)
    items = payload.get("items") or []
    if not items:
        raise SmokeError(f"检索 {query!r} 命中 0 条（索引没建？章节未发布？）")
    first = items[0]
    hit = f"{(first.get('book') or {}).get('slug')}/{(first.get('chapter') or {}).get('slug')}"
    return f"query={payload.get('query')!r} total={payload.get('total')} 首个命中={hit}", items


def _changes(api: str, since: str, api_key: str, timeout: float):
    payload = get_json(f"{api}/changes?since={_q(since)}", api_key=api_key, timeout=timeout)
    chapters = payload.get("chapters") or []
    return (
        f"since={payload.get('since')} count={payload.get('count')} 返回条目={len(chapters)}",
        payload,
    )
# ---------------------------------------------------------------- 主流程


def run(base: str, api_key: str, timeout: float, reporter: Reporter) -> bool:
    """按依赖顺序跑一遍；返回是否全部通过。"""
    api = base + "/api/v1"

    if step(reporter, "GET /healthz（存活）", lambda: _health(base, timeout)) is FAILED:
        reporter.skip("后续步骤", "存活检查未通过，后面的检查没有意义")
        return False

    if step(reporter, "GET /readyz（就绪 / 数据库可写）", lambda: _ready(base, timeout)) is FAILED:
        reporter.skip("后续步骤", "就绪检查未通过（数据库不可写？）")
        return False

    site = step(reporter, "GET /api/v1/site（站点元信息）", lambda: _site(api, api_key, timeout))
    if site is not FAILED:
        caps = site.get("capabilities") or {}
        if caps.get("api_key_required") and not api_key:
            reporter.skip("提示", "该实例配置了 API_KEY，后续请求可能 401；请传 --api-key")

    books = step(reporter, "GET /api/v1/books（Book 列表）", lambda: _books(api, api_key, timeout))
    if books is FAILED:
        reporter.skip("后续步骤", "Book 列表不可用，无法继续验证章节 / 检索 / 增量")
        return False

    book_ref = books[0]
    book = step(
        reporter,
        f"GET /api/v1/books/{book_ref}（详情 + 目录）",
        lambda: _book(api, book_ref, api_key, timeout),
    )
    if book is FAILED:
        reporter.skip("后续步骤", "Book 详情不可用")
        return False

    book_payload, chapter_ref = book
    chapter = step(
        reporter,
        f"GET .../books/{book_ref}/chapters/{chapter_ref}（JSON）",
        lambda: _chapter(api, book_ref, chapter_ref, api_key, timeout),
    )
    chapter_title = "" if chapter is FAILED else str(chapter.get("title") or "")

    step(
        reporter,
        f"GET .../books/{book_ref}/chapters/{chapter_ref}?format=raw（原文）",
        lambda: _chapter_raw(api, book_ref, chapter_ref, api_key, timeout),
    )

    query = _first_query(chapter_title or str(book_payload.get("title") or "") or chapter_ref)
    step(reporter, f"GET /api/v1/search?q={query}", lambda: _search(api, query, api_key, timeout))

    since = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    step(reporter, f"GET /api/v1/changes?since={since}", lambda: _changes(api, since, api_key, timeout))

    return not reporter.failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BookHub 部署冒烟检查（只读请求，不改任何数据）",
        epilog=(
            "示例：\n"
            "  python scripts/smoke.py\n"
            "  python scripts/smoke.py --base-url http://wiki.internal:8000 --api-key $BOOKHUB_API_KEY\n"
            "退出码：0 = 全部通过，1 = 有步骤失败"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"站点根地址，默认 {DEFAULT_BASE_URL}")
    parser.add_argument("--api-key", default="", help="实例配置了 API_KEY 时传入，作为 X-API-Key 头发送")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"单次请求超时秒数，默认 {DEFAULT_TIMEOUT}"
    )
    args = parser.parse_args(argv)

    base = args.base_url.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        parser.error("--base-url 必须以 http:// 或 https:// 开头")

    print(f"BookHub 冒烟检查 → {base}")
    print(f"API Key：{'已提供（X-API-Key）' if args.api_key else '未提供（实例若启用 API_KEY 会 401）'}")
    print()

    reporter = Reporter()
    try:
        passed = run(base, args.api_key, args.timeout, reporter)
    except KeyboardInterrupt:
        print("\n已中断")
        return 130

    print()
    if passed and not reporter.failures:
        print("结果：全部通过 ✅")
        return 0
    print(f"结果：{len(reporter.failures)} 项失败")
    for item in reporter.failures:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

