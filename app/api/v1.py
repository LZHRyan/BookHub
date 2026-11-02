"""对外只读 API `/api/v1`。"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app import __version__
from app.db import get_session
from app.errors import NotFound, ValidationFailed
from app.models import (
    STATUS_PUBLISHED,
    VISIBILITY_PUBLIC,
    Book,
    BookGroup,
    Chapter,
    ChapterSection,
    MediaAsset,
)
from app.services import book_groups, ranking
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import guide as guide_service
from app.services import sections as sections_service
from app.services.search import MAX_QUERY_LENGTH
from app.services.search import search as run_search

router = APIRouter(prefix="/api/v1", tags=["content"])
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


# ------------------------------------------------------------------ 工具


def _paging(page_raw: str, size_raw: str) -> tuple[int, int]:
    try:
        page = int(page_raw or "1")
    except (TypeError, ValueError) as exc:
        raise ValidationFailed("page 必须是大于等于 1 的整数") from exc
    if page < 1:
        raise ValidationFailed("page 必须是大于等于 1 的整数")
    size = DEFAULT_PAGE_SIZE
    if size_raw:
        try:
            size = int(size_raw)
        except (TypeError, ValueError) as exc:
            raise ValidationFailed("page_size 必须是整数") from exc
        size = max(1, min(size, MAX_PAGE_SIZE))
    return page, size


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _http_date(value: datetime) -> str:
    return format_datetime(value.replace(tzinfo=UTC), usegmt=True)


def _base_url(request: Request) -> str:
    return request.app.state.settings.root_path


def _book_payload(
    request: Request,
    book: Book,
    chapter_count: int,
    stats: ranking.BookStats | None = None,
    *,
    groups: dict[int, BookGroup] | None = None,
) -> dict[str, object]:
    base = _base_url(request)
    stats = stats or ranking.BookStats()
    return {
        "id": book.id,
        "slug": book.slug,
        "title": book.title,
        "group": _group_ref(book, groups),
        "summary": book.summary,
        "icon": book.icon,
        "format": book.format,
        "html_view": book.html_view,
        "visibility": book.visibility,
        "pinned": book.pinned,
        "is_builtin": bool(getattr(book, "is_builtin", False)),
        "cover": _cover_ref(request, book),
        "weight": round(stats.weight, 2),
        "view_count": stats.total_views,
        "recent_view_count": stats.recent_views,
        "chapter_count": chapter_count,
        "created_at": _iso(book.created_at),
        "updated_at": _iso(book.updated_at),
        "url": f"{base}/b/{book.slug}",
        "api_url": f"{base}/api/v1/books/{book.slug}",
    }


def _group_ref(book: Book, cache: dict[int, BookGroup] | None = None) -> dict[str, object] | None:
    """Book 所属分组的轻量表示；列表接口传 cache 批量取组，避免 N+1。"""
    if cache is not None and book.group_id in cache:
        group = cache[book.group_id]
    else:
        session = object_session(book)
        group = session.get(BookGroup, book.group_id) if session is not None else None
    if group is None:
        return None
    return {"id": group.id, "slug": group.slug, "title": group.title}


def _cover_ref(request: Request, book: Book) -> dict[str, object] | None:
    """封面表示：绝对地址，无封面或资源已删返回 None。"""
    if not book.cover_media_id:
        return None
    session = object_session(book)
    if session is None:
        return None
    asset = session.get(MediaAsset, book.cover_media_id)
    if asset is None or asset.deleted_at is not None or asset.book_id != book.id:
        return None
    base = _base_url(request)
    return {
        "id": asset.id,
        "url": f"{base}/media/{book.slug}/{asset.stored_name}",
        "filename": asset.filename,
    }


def _chapter_brief(request: Request, book: Book, chapter: Chapter) -> dict[str, object]:
    """章的表示：只有目录字段与它的节列表（正文 / 版本 / 字数都在节上）。"""
    base = _base_url(request)
    sections = sections_service.ordered_sections(session_of(chapter), chapter.id)
    return {
        "id": chapter.id,
        "slug": chapter.slug,
        "title": chapter.title,
        "status": chapter.status,
        "sections": [
            _section_brief(request, book, chapter, section) for section in sections
        ],
        "published_at": _iso(chapter.published_at),
        "updated_at": _iso(chapter.updated_at),
        "url": f"{base}/b/{book.slug}/{chapter.slug}",
        "api_url": f"{base}/api/v1/books/{book.slug}/chapters/{chapter.slug}",
    }


def session_of(chapter: Chapter) -> Session:
    session = object_session(chapter)
    if session is None:  # pragma: no cover - 正常情况下对象总是挂在会话上
        raise NotFound("章节不存在")
    return session


def _section_brief(
    request: Request, book: Book, chapter: Chapter, section: ChapterSection
) -> dict[str, object]:
    base = _base_url(request)
    return {
        "id": section.id,
        "slug": section.slug,
        "title": section.title,
        "format": section.format,
        "version": section.current_version_no,
        "word_count": section.word_count,
        "checksum": section.content_checksum,
        "updated_at": _iso(section.updated_at),
        "url": f"{base}/b/{book.slug}/{chapter.slug}/{section.slug}",
    }


def _section_payload(
    request: Request, book: Book, chapter: Chapter, section: ChapterSection
) -> dict[str, object]:
    payload = _section_brief(request, book, chapter, section)
    payload.update(
        {
            "book": {"id": book.id, "slug": book.slug, "title": book.title},
            "chapter": {"id": chapter.id, "slug": chapter.slug, "title": chapter.title},
            "content_raw": section.content_safe,
            "content_rendered": section.content_rendered,
            "toc": sections_service.parse_toc(section),
            "created_at": _iso(section.created_at),
        }
    )
    return payload


def _chapter_payload(request: Request, book: Book, chapter: Chapter) -> dict[str, object]:
    payload = _chapter_brief(request, book, chapter)
    payload.update(
        {
            "book": {"id": book.id, "slug": book.slug, "title": book.title},
            "created_at": _iso(chapter.created_at),
        }
    )
    sections = sections_service.ordered_sections(session_of(chapter), chapter.id)
    if len(sections) == 1:
        # 单节章保持 v1 老契约可用：正文/格式/版本直接平铺在章上，另附 section 结构
        first = sections[0]
        payload["section"] = _section_payload(request, book, chapter, first)
        payload.update(
            {
                "format": first.format,
                "version": first.current_version_no,
                "checksum": first.content_checksum,
                "word_count": first.word_count,
                "content_raw": first.content_safe,
                "content_rendered": first.content_rendered,
                "toc": sections_service.parse_toc(first),
            }
        )
    return payload


def _section_etag(section: ChapterSection) -> str:
    return f'"{section.id}-{section.current_version_no}-{(section.content_checksum or "")[:8]}"'


def _book_etag(book: Book, latest: datetime | None) -> str:
    stamp = latest or book.updated_at
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return f'"b{book.id}-{int(stamp.timestamp())}"'


def _conditional(request: Request, etag: str, last_modified: datetime) -> Response | None:
    inm = request.headers.get("if-none-match", "")
    if inm:
        candidates = {_strip_weak(part) for part in inm.split(",")}
        if etag in candidates or "*" in candidates:
            return Response(
                status_code=304, headers={"ETag": etag, "Last-Modified": _http_date(last_modified)}
            )
        return None
    ims = request.headers.get("if-modified-since", "")
    if ims:
        try:
            since = parsedate_to_datetime(ims)
        except (TypeError, ValueError):
            return None
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        # Last-Modified 只有秒级精度，比较前把微秒截掉，否则同一秒内永远不命中
        modified = last_modified.replace(microsecond=0, tzinfo=UTC)
        if modified <= since:
            return Response(
                status_code=304,
                headers={"ETag": etag, "Last-Modified": _http_date(last_modified)},
            )
    return None


def _strip_weak(tag: str) -> str:
    candidate = tag.strip()
    if candidate.startswith("W/"):
        candidate = candidate[2:].strip()
    return candidate


def _safe_filename(slug: str) -> str:
    """导出 ZIP 的文件名兜底：即使库里被写入异常 slug 也不会产生 zip slip。"""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", slug or "").strip("-")
    return cleaned or "chapter"


def _resolve_book(session: Session, ref: str) -> Book:
    return books_service.get_book(session, (ref or "").strip())


def _resolve_chapter(session: Session, book: Book, ref: str) -> Chapter:
    ref = (ref or "").strip()
    if ref.isdigit():
        chapter = session.get(Chapter, int(ref))
        if chapter is None or chapter.book_id != book.id:
            raise NotFound("章节不存在")
    else:
        chapter = session.execute(
            select(Chapter).where(
                Chapter.book_id == book.id,
                Chapter.slug == ref,
                Chapter.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if chapter is None:
            raise NotFound("章节不存在")
    if chapter.deleted_at is not None or chapter.status != STATUS_PUBLISHED:
        raise NotFound("章节不存在")
    return chapter


def _resolve_section(
    session: Session, chapter: Chapter, ref: str
) -> ChapterSection:
    """按 slug 或 id 在这一章里定位一节（对外只认已发布章下的未删除节）。"""
    try:
        section = sections_service.get_section(session, chapter, ref)
    except NotFound as exc:
        raise NotFound("节不存在") from exc
    return section


# ------------------------------------------------------------------ 端点


@router.get("/site")
def site_info(request: Request, session: Session = Depends(get_session)) -> JSONResponse:
    settings = request.app.state.settings
    guide = guide_service.find_guide(session)
    return JSONResponse(
        {
            "name": settings.site_name,
            "version": __version__,
            "capabilities": {
                "formats": ["markdown", "html"],
                "rendered": True,
                "export": ["json", "zip"],
                "incremental": True,
                "search": True,
                "api_key_required": bool(settings.api_key),
            },
            "api": {
                "version": "v1",
                "docs": f"{settings.root_path}/docs" if settings.api_docs_enabled else None,
            },
            # 内置《AI Agent 接入使用指南》：外部工具拿到 slug 就能直接读「怎么用这个库」
            "guide": (
                {
                    "slug": guide.slug,
                    "title": guide.title,
                    "url": f"{_base_url(request)}/b/{guide.slug}",
                    "api_url": f"{_base_url(request)}/api/v1/books/{guide.slug}",
                }
                if guide is not None
                else None
            ),
        }
    )


@router.get("/books")
def list_books(
    request: Request,
    page: str = Query(default="1"),
    page_size: str = Query(default=""),
    visibility: str = Query(default=""),
    group: str = Query(default=""),
    session: Session = Depends(get_session),
) -> JSONResponse:
    page_no, size = _paging(page, page_size)
    settings = request.app.state.settings
    requested = (visibility or VISIBILITY_PUBLIC).strip()
    if requested not in {VISIBILITY_PUBLIC, "unlisted", "all"}:
        raise ValidationFailed("visibility 取值应为 public、unlisted 或 all")
    if requested == "all":
        if not settings.api_key:
            raise ValidationFailed("visibility=all 仅在配置 API_KEY 后可用")
        condition: str | None = None
    elif requested == VISIBILITY_PUBLIC:
        condition = VISIBILITY_PUBLIC
    else:
        if not settings.api_key:
            raise ValidationFailed("visibility=unlisted 仅在配置 API_KEY 后可用")
        condition = "unlisted"

    # group 只当过滤条件：不存在的分组由服务层抛 NotFound（404）
    rows, total = books_service.list_books(
        session,
        visibility=condition,
        group=(group or "").strip() or None,
        page=page_no,
        page_size=size,
    )
    counts = books_service.chapter_counts(session, [book.id for book in rows])
    stats = ranking.stats_for(session, rows)
    groups = {item.id: item for item in book_groups.list_groups(session)}
    items = [
        _book_payload(request, book, counts.get(book.id, 0), stats.get(book.id), groups=groups)
        for book in rows
    ]
    return JSONResponse({"items": items, "total": total, "page": page_no, "page_size": size})


@router.get("/books/{book_ref}")
def book_detail(
    request: Request,
    book_ref: str,
    session: Session = Depends(get_session),
) -> Response:
    book = _resolve_book(session, book_ref)
    flat = chapters_service.flat_published_sections(session, book.id)
    chapters = chapters_service.published_chapters(session, book.id)
    latest = max(
        [chapter.updated_at for chapter in chapters]
        + [section.updated_at for _chapter, section in flat]
        + [book.updated_at]
    )
    etag = _book_etag(book, latest)
    cached = _conditional(request, etag, latest)
    if cached is not None:
        return cached
    payload = _book_payload(request, book, len(chapters), ranking.stats_of(session, book))
    # 目录是「章 → 节」两级：章给出自身信息与它的节，节带自己的 URL
    payload["chapters"] = [
        _chapter_brief(request, book, row["chapter"])
        for row in chapters_service.tree(session, book.id, published_only=True)
    ]
    payload["section_count"] = len(flat)
    return JSONResponse(payload, headers={"ETag": etag, "Last-Modified": _http_date(latest)})


@router.get("/books/{book_ref}/chapters/{chapter_ref}")
def chapter_detail(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    format: str = Query(default=""),
    section: str = Query(default="", description="节的 slug 或 id；给了就返回这一节的正文"),
    session: Session = Depends(get_session),
):
    """章详情：默认返回节列表；`?section=` 取单节正文（也是 raw / rendered 的出口）。

    单节章即使不传 `?section=` 也会在 `section` 字段里带上这一节的内容，兼容旧调用。
    """
    book = _resolve_book(session, book_ref)
    chapter = _resolve_chapter(session, book, chapter_ref)

    accept = request.headers.get("accept", "").lower()
    wanted = (format or "").strip().lower()
    if not wanted:
        if "text/markdown" in accept:
            wanted = "raw"
        elif "text/html" in accept:
            wanted = "rendered"
        else:
            wanted = "json"
    if wanted not in {"json", "raw", "rendered"}:
        raise ValidationFailed("format 取值应为 json、raw 或 rendered")

    sections = sections_service.ordered_sections(session, chapter.id)
    only_section = sections[0] if len(sections) == 1 else None
    wanted_section = section.strip()
    if wanted in {"raw", "rendered"}:
        # 正文通道：必须能唯一定位一节（单节章可以不传 ?section=）
        target = (
            _resolve_section(session, chapter, wanted_section) if wanted_section else only_section
        )
        if target is None:
            raise ValidationFailed("这个章有多节，请在 ?section= 里指定要取哪一节")
        etag = _section_etag(target)
        cached = _conditional(request, etag, target.updated_at)
        if cached is not None:
            return cached
        headers = {"ETag": etag, "Last-Modified": _http_date(target.updated_at)}
        if wanted == "raw":
            media = "text/markdown" if target.format == "markdown" else "text/html"
            return PlainTextResponse(
                target.content_safe, media_type=f"{media}; charset=utf-8", headers=headers
            )
        return HTMLResponse(target.content_rendered, headers=headers)

    if wanted_section:
        target = _resolve_section(session, chapter, wanted_section)
        etag = _section_etag(target)
        cached = _conditional(request, etag, target.updated_at)
        if cached is not None:
            return cached
        return JSONResponse(
            _section_payload(request, book, chapter, target),
            headers={"ETag": etag, "Last-Modified": _http_date(target.updated_at)},
        )

    latest = max([chapter.updated_at] + [item.updated_at for item in sections])
    # ETag 里带上各节版本号之和：同一秒内连续保存也能区分出变化
    etag = f'"c{chapter.id}-{len(sections)}-{sum(item.current_version_no for item in sections)}"'
    cached = _conditional(request, etag, latest)
    if cached is not None:
        return cached
    return JSONResponse(
        _chapter_payload(request, book, chapter),
        headers={"ETag": etag, "Last-Modified": _http_date(latest)},
    )


@router.get("/books/{book_ref}/export")
def export_book(
    request: Request,
    book_ref: str,
    format: str = Query(default="json"),
    session: Session = Depends(get_session),
) -> Response:
    book = _resolve_book(session, book_ref)
    tree = chapters_service.tree(session, book.id, published_only=True)
    files: list[tuple[str, str]] = []
    chapters_payload: list[dict[str, object]] = []
    for row in tree:
        chapter = row["chapter"]
        section_entries: list[dict[str, object]] = []
        for section, _no in row["sections"]:
            suffix = "md" if section.format == "markdown" else "html"
            path = f"{chapter.slug}/{section.slug}.{suffix}"
            files.append((f"{_safe_filename(chapter.slug)}/{_safe_filename(section.slug)}.{suffix}", section.content_safe))
            section_entries.append(
                {
                    "id": section.id,
                    "slug": section.slug,
                    "title": section.title,
                    "format": section.format,
                    "version": section.current_version_no,
                    "checksum": section.content_checksum,
                    "path": path,
                    "api_path": (
                        f"/api/v1/books/{book.slug}/chapters/{chapter.slug}"
                        f"?section={section.slug}"
                    ),
                    "updated_at": _iso(section.updated_at),
                }
            )
        chapters_payload.append(
            {
                "id": chapter.id,
                "slug": chapter.slug,
                "title": chapter.title,
                "sections": section_entries,
                "updated_at": _iso(chapter.updated_at),
            }
        )

    manifest = {
        "book": {
            "id": book.id,
            "slug": book.slug,
            "title": book.title,
            "summary": book.summary,
            "visibility": book.visibility,
            "pinned": book.pinned,
            "updated_at": _iso(book.updated_at),
        },
        "chapter_count": len(chapters_payload),
        "section_count": len(files),
        "chapters": chapters_payload,
        "exported_at": _iso(datetime.now(UTC)),
    }
    if (format or "json").strip().lower() == "json":
        return JSONResponse(manifest)
    if (format or "").strip().lower() != "zip":
        raise ValidationFailed("format 取值应为 json 或 zip")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("book.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for path, body in files:
            archive.writestr(path, body)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{book.slug}.zip"'},
    )


@router.get("/search")
def search_endpoint(
    request: Request,
    q: str = Query(default=""),
    page: str = Query(default="1"),
    page_size: str = Query(default=""),
    book: str = Query(default=""),
    session: Session = Depends(get_session),
) -> JSONResponse:
    query = (q or "").strip()
    if len(query) > MAX_QUERY_LENGTH:
        raise ValidationFailed(f"查询词不能超过 {MAX_QUERY_LENGTH} 个字符")
    page_no, size = _paging(page, page_size)
    book_id = None
    if book.strip():
        try:
            book_id = _resolve_book(session, book.strip()).id
        except NotFound:
            return JSONResponse(
                {"items": [], "total": 0, "page": page_no, "page_size": size, "query": query}
            )
    items, total = run_search(session, query=query, book_id=book_id, page=page_no, page_size=size)
    base = _base_url(request)
    payload_items = [
        {
            "book": {
                "id": item["book_id"],
                "slug": item["book_slug"],
                "title": item["book_title"],
            },
            "chapter": {
                "id": item["chapter_id"],
                "slug": item["chapter_slug"],
                "title": item["chapter_title"],
            },
            "section": {
                "id": item["section_id"],
                "slug": item["section_slug"],
                "title": item["section_title"],
            },
            "url": f"{base}/b/{item['book_slug']}/{item['chapter_slug']}/{item['section_slug']}",
            "snippet": item["snippet"],
            "updated_at": _iso(item["updated_at"]),
        }
        for item in items
    ]
    return JSONResponse(
        {"items": payload_items, "total": total, "page": page_no, "page_size": size, "query": query}
    )


@router.get("/changes")
def changes(
    request: Request,
    since: str = Query(default=""),
    session: Session = Depends(get_session),
) -> JSONResponse:
    raw = (since or "").strip()
    if not raw:
        raise ValidationFailed("缺少 since 参数（ISO-8601 时间）")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationFailed("since 不是合法的 ISO-8601 时间") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    # server_time 取在查询之前：客户端下一次用该值做 since，才不会漏掉中间更新的节
    server_time = datetime.now(UTC)
    items = chapters_service.chapters_updated_since(session, parsed)
    for item in items:
        item["updated_at"] = _iso(item["updated_at"])  # type: ignore[arg-type]
    return JSONResponse(
        {
            "since": _iso(parsed),
            "server_time": _iso(server_time),
            "sections": items,
            "count": len(items),
        }
    )
