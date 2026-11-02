"""管理端写接口 `/api/v1/admin/*`：供程序与 AI 工具驱动全部后台操作。

设计原则（见 openspec/changes/admin-management-api/design.md）：
- 路由只做协议转换，业务规则全部复用 app/services 里的服务层；
- 每个写操作走统一的幂等包装（Idempotency-Key）；
- 破坏性操作支持 dry_run 预览与 confirm 强制；
- 审计归属到 `api:<token 名>`。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from app.db import get_session
from app.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.middleware import client_ip
from app.models import (
    STATUS_PUBLISHED,
    AuditLog,
    Book,
    BookGroup,
    Chapter,
    ChapterSection,
    MediaAsset,
    User,
    utcnow,
)
from app.services import audit as audit_service
from app.services import book_groups, builtin, idempotency
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import media as media_service
from app.services import sections as sections_service
from app.services import settings as settings_service
from app.services import tokens as token_service
from app.services import users as users_service
from app.services import webhooks as webhooks_service
from app.services.encoding import (
    EncodingError,
    UnsupportedFormat,
    decode_with_hint,
    detect_format,
    title_from_filename,
)
from app.uploads import read_limited

from .deps import Principal, require_scope

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

Visibility = Literal["public", "unlisted"]
DocFormat = Literal["markdown", "html"]
ChapterStatus = Literal["draft", "published"]


# ------------------------------------------------------------------ 请求模型


class BookCreate(BaseModel):
    title: str = Field(description="Book 标题，必填，最长 200 字符")
    # 分组是必填契约；这里不交给 Pydantic 的 required 校验，是为了让缺失时走统一的
    # error 信封并返回「必须选择分组」，而不是 FastAPI 默认的 422 detail 结构。
    group: str | int | None = Field(
        default=None, description="所属分组的 slug 或 id，必填；缺失返回 400"
    )
    summary: str = Field(default="", description="简介，显示在首页卡片")
    icon: str = Field(default="", description="图标，一个 emoji")
    format: DocFormat = Field(default="markdown", description="整本文档类型：所有节都按它渲染，有章后不可改")
    visibility: Visibility = Field(default="public", description="public 或 unlisted")
    html_view: str | None = Field(default=None, description="HTML Book 的展示模式（由站点定义）")


class BookUpdate(BaseModel):
    title: str | None = None
    slug: str | None = None
    group: str | int | None = Field(
        default=None, description="改归属的分组（slug 或 id）；不传或 null 表示不改"
    )
    summary: str | None = None
    icon: str | None = None
    format: DocFormat | None = None
    visibility: Visibility | None = None
    pinned: bool | None = Field(default=None, description="置顶后排在首页最前，置顶内部仍按热度排序")
    cover_media_id: int | None = Field(default=None, description="封面媒体资源 id；null 表示清除封面")
    html_view: str | None = None


class ChapterCreate(BaseModel):
    title: str = Field(description="章标题，必填")
    content: str = Field(default="", description="首节正文（与 multipart 上传二选一）")
    slug: str = Field(default="", description="留空由标题生成")
    status: ChapterStatus = Field(default="draft", description="draft 或 published")
    note: str = Field(default="", description="版本备注")
    format: DocFormat | None = Field(default=None, description="首节格式；必须与 Book 的文档类型一致，留空即用它")


class ChapterUpdate(BaseModel):
    """章级字段：正文与版本都在节上，章只改标题与访问标识。"""

    title: str | None = None
    slug: str | None = None


class SectionCreate(BaseModel):
    title: str = Field(description="节标题，必填")
    content: str = Field(default="", description="Markdown 或 HTML 正文（与 multipart 上传二选一）")
    slug: str = Field(default="", description="留空由标题生成；同一章内唯一")
    format: DocFormat | None = Field(default=None, description="节格式；必须与 Book 的文档类型一致，留空即用它")
    note: str = Field(default="", description="版本备注")


class SectionReplace(BaseModel):
    title: str | None = None
    content: str | None = Field(default=None, description="新正文；不传则保持原正文")
    slug: str | None = None
    format: DocFormat | None = Field(default=None, description="必须与 Book 的文档类型一致")
    base_version: int | None = Field(default=None, description="乐观并发基准版本，不一致返回 409")
    note: str = ""


class BookGroupCreate(BaseModel):
    """Book 分组（首页分区），是 Book 的上一层分类。"""

    title: str = Field(description="分组标题，必填")
    slug: str = Field(default="", description="留空由标题生成；只用于 API 与 ?group= 筛选")
    description: str = Field(default="", description="分组简介")
    icon: str = Field(default="", description="分组图标，一个 emoji")


class BookGroupUpdate(BaseModel):
    title: str | None = None
    slug: str | None = None
    description: str | None = None
    icon: str | None = None


class BookGroupMoveRequest(BaseModel):
    direction: Literal[-1, 1] = Field(description="-1 上移，1 下移")


class StatusChange(BaseModel):
    status: ChapterStatus


class MoveRequest(BaseModel):
    direction: int | None = Field(default=None, description="-1 上移，1 下移")
    position: int | None = Field(default=None, ge=1, description="目标位置（从 1 开始），与 direction 二选一")


class BatchRequest(BaseModel):
    action: Literal["publish", "unpublish", "delete"]
    chapter_ids: list[int] = Field(min_length=1, description="要操作的章 ID 列表")
    confirm: bool = Field(default=False, description="delete 时必须为 true")


class ReorderRequest(BaseModel):
    chapter_ids: list[int] = Field(min_length=1, description="该 Book 下有序列条目的完整 id 列表")


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: Literal["admin", "editor"] = "editor"


class PasswordReset(BaseModel):
    password: str


class SettingsUpdate(BaseModel):
    site_name: str
    site_footer: str = ""
    home_intro: str = ""


class TokenCreate(BaseModel):
    name: str = Field(description="Token 名称，会作为审计里的操作者")
    scopes: list[Literal["read", "write", "admin"]] = Field(default=["read"])
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    books: list[str] = Field(
        default_factory=list, description="限定可操作的 Book（slug 或 id）；留空表示全部"
    )


# ------------------------------------------------------------------ 工具


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _cover_json(book: Book, root_path: str = "") -> dict[str, object] | None:
    """封面的轻量表示（根相对地址）；无封面或资源已删返回 None。"""
    if not book.cover_media_id:
        return None
    session = object_session(book)
    if session is None:
        return None
    asset = session.get(MediaAsset, book.cover_media_id)
    if asset is None or asset.deleted_at is not None or asset.book_id != book.id:
        return None
    return {
        "id": asset.id,
        "url": media_service.media_url(book.slug, asset.stored_name, root_path),
        "filename": asset.filename,
    }


def _book_group_ref(book: Book, cache: dict[int, BookGroup] | None = None) -> dict[str, object] | None:
    """Book 所属「分组」的轻量表示。

    列表接口传 cache（{group_id: BookGroup}）批量取一次组，避免逐本查库。
    """
    if cache is not None and book.group_id in cache:
        group = cache[book.group_id]
    else:
        session = object_session(book)
        group = session.get(BookGroup, book.group_id) if session is not None else None
    if group is None:
        return None
    return {"id": group.id, "slug": group.slug, "title": group.title}


def _book_json(
    book: Book,
    chapter_count: int = 0,
    *,
    root_path: str = "",
    groups: dict[int, BookGroup] | None = None,
) -> dict[str, object]:
    return {
        "id": book.id,
        "slug": book.slug,
        "title": book.title,
        "group": _book_group_ref(book, groups),
        "summary": book.summary,
        "icon": book.icon,
        "format": book.format,
        "visibility": book.visibility,
        "pinned": book.pinned,
        "is_builtin": builtin.is_builtin(book),
        "cover": _cover_json(book, root_path),
        "html_view": book.html_view,
        "chapter_count": chapter_count,
        "deleted": book.deleted_at is not None,
        "created_at": _iso(book.created_at),
        "updated_at": _iso(book.updated_at),
    }


def _token_json(token, *, session: Session | None = None) -> dict[str, object]:
    """Token 描述转 JSON（describe 里的时间字段是 datetime）。"""
    described = token_service.describe(token)
    for key in ("created_at", "expires_at", "revoked_at", "last_used_at"):
        described[key] = _iso(described.get(key))  # type: ignore[arg-type]
    book_ids = described.pop("book_ids", []) or []
    books: list[dict[str, object]] = []
    if session is not None:
        for book_id in book_ids:
            book = session.get(Book, int(book_id))
            if book is not None:
                books.append({"id": book.id, "slug": book.slug, "title": book.title})
    described["books"] = books
    return described


def _chapter_json(chapter: Chapter, *, with_content: bool = False) -> dict[str, object]:
    """章的表示：只有目录字段 + 它的节列表（正文、版本、字数都属于节）。"""
    sections = sections_service.ordered_sections(session_of(chapter), chapter.id)
    return {
        "id": chapter.id,
        "book_id": chapter.book_id,
        "slug": chapter.slug,
        "title": chapter.title,
        "status": chapter.status,
        "sort_order": chapter.sort_order,
        "sections": [
            _section_json(section, chapter=chapter, with_content=with_content)
            for section in sections
        ],
        "published_at": _iso(chapter.published_at),
        "deleted": chapter.deleted_at is not None,
        "created_at": _iso(chapter.created_at),
        "updated_at": _iso(chapter.updated_at),
    }


def session_of(chapter: Chapter) -> Session:
    session = object_session(chapter)
    if session is None:  # pragma: no cover - 正常情况下对象总是挂在会话上
        raise NotFound("章节不在会话中")
    return session


def _section_json(
    section: ChapterSection,
    *,
    chapter: Chapter | None = None,
    book: Book | None = None,
    with_content: bool = False,
    root_path: str = "",
) -> dict[str, object]:
    owner = chapter if chapter is not None else section.chapter
    parent_book = book if book is not None else (owner.book if owner is not None else None)
    base = root_path
    payload: dict[str, object] = {
        "id": section.id,
        "chapter_id": section.chapter_id,
        "slug": section.slug,
        "title": section.title,
        "format": section.format,
        "sort_order": section.sort_order,
        "version": section.current_version_no,
        "word_count": section.word_count,
        "checksum": section.content_checksum,
        "deleted": section.deleted_at is not None,
        "updated_at": _iso(section.updated_at),
    }
    if parent_book is not None and owner is not None:
        payload["url"] = f"{base}/b/{parent_book.slug}/{owner.slug}/{section.slug}"
        payload["api_url"] = (
            f"{base}/api/v1/books/{parent_book.slug}/chapters/{owner.slug}?section={section.slug}"
        )
    if with_content:
        payload["content_raw"] = section.content_safe
        payload["content_rendered"] = section.content_rendered
        payload["toc"] = sections_service.parse_toc(section)
    return payload


def _section(session: Session, chapter: Chapter, ref: str) -> ChapterSection:
    return sections_service.get_section(session, chapter, ref)


def _book(session: Session, ref: str) -> Book:
    return books_service.get_book(session, ref, include_deleted=True)


def _chapter(session: Session, book: Book, ref: str) -> Chapter:
    if ref.isdigit():
        chapter = session.get(Chapter, int(ref))
    else:
        chapter = session.execute(
            select(Chapter).where(Chapter.book_id == book.id, Chapter.slug == ref)
        ).scalar_one_or_none()
    if chapter is None or chapter.book_id != book.id:
        raise NotFound("章节不存在")
    return chapter


def _write(
    request: Request,
    session: Session,
    principal: Principal,
    *,
    op: str,
    payload: dict[str, object],
    action,
    status_code: int = 200,
) -> JSONResponse:
    """统一处理幂等键：同键同指纹回放首次结果，不同指纹 409。

    存储键带上签发 Token 的 id：不同 Token 用同一个 Idempotency-Key 时互不影响，
    既避免跨 Token 回放别人的响应，也避免互相抢占键造成 409。
    """
    raw_key = (request.headers.get("idempotency-key") or "").strip()
    key = f"{principal.token_id}:{raw_key}" if raw_key else ""
    fp = idempotency.fingerprint(op, payload)
    if key:
        replay = idempotency.lookup(session, key, token_id=principal.token_id, request_fingerprint=fp)
        if replay is not None:
            session.commit()
            return JSONResponse(replay.payload, status_code=replay.status_code, headers={"Idempotent-Replay": "true"})

    body = action()
    session.commit()
    if key:
        idempotency.remember(
            session,
            key,
            token_id=principal.token_id,
            request_fingerprint=fp,
            status_code=status_code,
            payload=body,
        )
        session.commit()
    return JSONResponse(body, status_code=status_code)


def _dry_run(request: Request) -> bool:
    return (request.query_params.get("dry_run") or "").lower() in {"1", "true", "yes"}


def _confirmed(request: Request) -> bool:
    return (request.query_params.get("confirm") or "").lower() in {"1", "true", "yes"}


def _require_confirm(request: Request, what: str) -> None:
    if not _confirmed(request):
        raise ValidationFailed(f"删除{what}需要显式确认：请带 confirm=true 参数（可先用 dry_run=true 预览影响面）")


# ------------------------------------------------------------------ 分组（Book 的上级分类）


def _book_group_json(group: BookGroup, book_count: int = 0) -> dict[str, object]:
    return {
        "id": group.id,
        "slug": group.slug,
        "title": group.title,
        "description": group.description,
        "icon": group.icon,
        "sort_order": group.sort_order,
        "book_count": book_count,
        # 默认分组随系统创建：不能删除，slug 固定为 default
        "is_default": book_groups.is_default(group),
    }


def _book_group_cache(session: Session) -> dict[int, BookGroup]:
    """一次取出全部组，供 Book 列表映射 group 对象（避免 N+1）。"""
    return {group.id: group for group in book_groups.list_groups(session)}


def _book_group_items(session: Session) -> list[dict[str, object]]:
    counts = book_groups.book_counts(session)
    return [_book_group_json(group, counts.get(group.id, 0)) for group in book_groups.list_groups(session)]


@router.get("/groups", summary="列出 Book 分组（含 Book 数）")
def list_book_groups(
    request: Request,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return JSONResponse({"items": _book_group_items(session)})


@router.post("/groups", status_code=201, summary="新建 Book 分组")
def create_book_group(
    request: Request,
    body: BookGroupCreate,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def action() -> dict[str, object]:
        group = book_groups.create(
            session,
            title=body.title,
            slug_raw=body.slug,
            description=body.description,
            icon=body.icon,
            actor=principal,  # type: ignore[arg-type]
            ip=client_ip(request),
        )
        return _book_group_json(group, 0)

    return _write(
        request,
        session,
        principal,
        op="book_group.create",
        payload=body.model_dump(),
        action=action,
        status_code=201,
    )


@router.patch("/groups/{group_ref}", summary="修改 Book 分组（标题 / slug / 简介 / 图标）")
def update_book_group(
    request: Request,
    group_ref: str,
    body: BookGroupUpdate,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    group = book_groups.get_group(session, group_ref)

    def action() -> dict[str, object]:
        book_groups.update(
            session,
            group,
            title=body.title,
            slug_raw=body.slug,
            description=body.description,
            icon=body.icon,
            actor=principal,  # type: ignore[arg-type]
            ip=client_ip(request),
        )
        return _book_group_json(group, book_groups.count_books(session, group.id))

    return _write(
        request,
        session,
        principal,
        op=f"book_group.update:{group.id}",
        payload=body.model_dump(exclude_unset=True),
        action=action,
    )


@router.delete("/groups/{group_ref}", summary="删除 Book 分组（默认分组、非空组与最后一个组会被拒绝）")
def delete_book_group(
    request: Request,
    group_ref: str,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    group = book_groups.get_group(session, group_ref)
    group_id, slug, title = group.id, group.slug, group.title

    def action() -> dict[str, object]:
        # 非空组 / 最后一个组的拒绝由服务层抛 ValidationFailed，信息原样透出
        book_groups.delete(session, group, actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
        return {"deleted": True, "id": group_id, "slug": slug, "title": title}

    return _write(
        request,
        session,
        principal,
        op=f"book_group.delete:{group_id}",
        payload={"group_id": group_id},
        action=action,
    )


@router.post("/groups/{group_ref}/move", summary="调整 Book 分组顺序（-1 上移 / 1 下移）")
def move_book_group(
    request: Request,
    group_ref: str,
    body: BookGroupMoveRequest,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    group = book_groups.get_group(session, group_ref)

    def action() -> dict[str, object]:
        book_groups.move(
            session, group, int(body.direction), actor=principal, ip=client_ip(request)  # type: ignore[arg-type]
        )
        return {"items": _book_group_items(session)}

    return _write(
        request,
        session,
        principal,
        op=f"book_group.move:{group.id}",
        payload={"direction": int(body.direction)},
        action=action,
    )


# ------------------------------------------------------------------ Book


@router.get("/books", summary="列出 Book（含未列出与已删除）")
def list_books(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    include_deleted: bool = Query(default=False),
    group: str = Query(default="", description="只列该分组（slug 或 id）"),
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    rows, total = books_service.list_books(
        session,
        visibility=None,
        group=group.strip() or None,
        page=page,
        page_size=page_size,
        include_deleted=include_deleted,
        # 受限 Token 只列自己范围内的 Book（含未列出/已删除）
        scope_ids=list(principal.book_ids) if principal.book_ids else None,
    )
    counts = books_service.chapter_counts(session, [book.id for book in rows], published_only=False)
    groups = _book_group_cache(session)
    root_path = request.app.state.settings.root_path
    items = [_book_json(book, counts.get(book.id, 0), root_path=root_path, groups=groups) for book in rows]
    return JSONResponse({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/books/{book_ref}", summary="读取单个 Book（含未列出 / 已删除）")
def get_book_detail(
    request: Request,
    book_ref: str,
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    counts = books_service.chapter_counts(session, [book.id], published_only=False)
    root_path = request.app.state.settings.root_path
    return JSONResponse(
        _book_json(
            book,
            counts.get(book.id, 0),
            root_path=root_path,
            groups=_book_group_cache(session),
        )
    )


@router.post("/books", status_code=201, summary="创建 Book")
def create_book(
    request: Request,
    body: BookCreate,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    if body.group is None or (isinstance(body.group, str) and not body.group.strip()):
        raise ValidationFailed("创建 Book 必须选择分组：请在 group 里给出分组的 slug 或 id")

    def action() -> dict[str, object]:
        book = books_service.create_book(
            session,
            title=body.title,
            summary=body.summary,
            icon=body.icon,
            fmt=body.format,
            html_view=body.html_view,
            visibility=body.visibility,
            group=body.group,
            actor=principal,  # type: ignore[arg-type]
            ip=client_ip(request),
        )
        return _book_json(book)

    return _write(request, session, principal, op="book.create", payload=body.model_dump(), action=action, status_code=201)


@router.patch("/books/{book_ref}", summary="修改 Book")
def update_book(
    request: Request,
    book_ref: str,
    body: BookUpdate,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    settings = request.app.state.settings
    cover_given = "cover_media_id" in body.model_fields_set
    group_given = "group" in body.model_fields_set and body.group is not None

    def action() -> dict[str, object]:
        books_service.update_book(
            session,
            book,
            title=body.title,
            slug_raw=body.slug,
            summary=body.summary,
            icon=body.icon,
            fmt=body.format,
            html_view=body.html_view,
            visibility=body.visibility,
            pinned=body.pinned,
            group=body.group if group_given else None,
            actor=principal,  # type: ignore[arg-type]
            ip=client_ip(request),
        )
        if cover_given:
            books_service.set_cover(
                session,
                book,
                body.cover_media_id,
                actor=principal,  # type: ignore[arg-type]
                ip=client_ip(request),
            )
        return _book_json(book, books_service.active_chapter_count(session, book.id), root_path=settings.root_path)

    return _write(request, session, principal, op=f"book.update:{book.id}", payload=body.model_dump(exclude_none=True), action=action)


@router.post("/books/{book_ref}/delete", summary="软删除 Book（建议先 dry_run）")
def delete_book(
    request: Request,
    book_ref: str,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    count = books_service.active_chapter_count(session, book.id)
    if _dry_run(request):
        return JSONResponse(
            {"dry_run": True, "would_delete": _book_json(book, count), "chapters": count}
        )
    _require_confirm(request, " Book")

    def action() -> dict[str, object]:
        books_service.soft_delete_book(session, book, actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
        return {"deleted": True, "book": _book_json(book, count)}

    return _write(request, session, principal, op=f"book.delete:{book.id}", payload={}, action=action)


@router.post("/books/{book_ref}/restore", summary="恢复 Book")
def restore_book(
    request: Request,
    book_ref: str,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)

    def action() -> dict[str, object]:
        books_service.restore_book(session, book, actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
        return {"restored": True, "book": _book_json(book)}

    return _write(request, session, principal, op=f"book.restore:{book.id}", payload={}, action=action)


# ------------------------------------------------------------------ 章节


@router.get("/books/{book_ref}/chapters", summary="列出 Book 下所有章节（含草稿与已删除）")
def list_chapters(
    request: Request,
    book_ref: str,
    include_deleted: bool = Query(default=False),
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    rows = chapters_service.ordered_chapters(session, book.id, include_deleted=include_deleted)
    return JSONResponse({"book": _book_json(book), "items": [_chapter_json(row) for row in rows]})


@router.post("/books/{book_ref}/chapters", status_code=201, summary="新建章节（可同时带上首节正文或上传文件）")
async def create_chapter(
    request: Request,
    book_ref: str,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """建一章；给了 content 或文件就同时建首节（多个文件 → 多节）。"""
    book = _book(session, book_ref)
    settings = request.app.state.settings
    content_type = (request.headers.get("content-type") or "").lower()

    fields: dict[str, object] = {}
    files: list[dict[str, object]] = []
    uploads: list[tuple[str, bytes]] = []
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        fields = {
            "title": str(form.get("title") or ""),
            "content": str(form.get("content") or ""),
            "slug": str(form.get("slug") or ""),
            "status": str(form.get("status") or "draft"),
            "note": str(form.get("note") or ""),
            "format": str(form.get("format") or ""),
        }
        encoding = str(form.get("encoding") or "")
        candidates = [
            upload
            for upload in list(form.getlist("file")) + list(form.getlist("upload"))
            if upload is not None and getattr(upload, "filename", "")
        ]
        if len(candidates) > settings.max_upload_files:
            raise ValidationFailed(f"一次最多上传 {settings.max_upload_files} 个文件")
        for upload in candidates:
            uploads.append(
                (
                    upload.filename or "",
                    await read_limited(upload, settings.max_upload_bytes),
                )
            )
    else:
        raw_body = await request.json()
        parsed = ChapterCreate.model_validate(raw_body)
        if not parsed.title.strip():
            # JSON 请求没有文件名可回落，空标题会让章变成「正文」并生成随机 slug
            raise ValidationFailed("章标题必填（JSON 请求没有文件名可回落；上传文件时标题可省略）")
        fields = {
            "title": parsed.title,
            "content": parsed.content,
            "slug": parsed.slug,
            "status": parsed.status,
            "note": parsed.note,
            "format": parsed.format or "",
        }
        encoding = ""

    for upload_name, upload_bytes in uploads:
        if len(upload_bytes) > settings.max_upload_bytes:
            raise ValidationFailed(f"文件超过上限（{settings.max_upload_bytes // 1024 // 1024} MiB）")
        try:
            detected = detect_format(upload_name)
            text = decode_with_hint(upload_bytes, encoding or None)
        except UnsupportedFormat as exc:
            raise ValidationFailed(str(exc)) from exc
        except EncodingError as exc:
            raise ValidationFailed(str(exc)) from exc
        files.append(
            {"title": title_from_filename(upload_name), "format": detected, "raw": text}
        )

    if not files and str(fields["content"]).strip():
        files.append(
            {
                "title": str(fields["title"]) or "正文",
                "format": fields["format"] or None,
                "raw": str(fields["content"]),
            }
        )
    if not files:
        raise ValidationFailed("请提供 content 字段或上传文件")

    def action() -> dict[str, object]:
        chapter = chapters_service.create_chapter(
            session,
            book,
            title=str(fields["title"]) or str(files[0]["title"]),
            slug_raw=str(fields["slug"]),
            status=str(fields["status"]),
            actor=principal,  # type: ignore[arg-type]
            ip=client_ip(request),
            note=str(fields["note"]) or "新建章（API）",
            files=files,
            max_chars=settings.max_content_chars,
        )
        return _chapter_json(chapter, with_content=True)

    payload = {
        "title": str(fields["title"]),
        "slug": str(fields["slug"]),
        "status": str(fields["status"]),
        "note": str(fields["note"]),
        "format": str(fields["format"]),
        "files": [
            {"title": item["title"], "format": item["format"], "raw": item["raw"]} for item in files
        ],
    }
    return _write(request, session, principal, op=f"chapter.create:{book.id}", payload=payload, action=action, status_code=201)


@router.patch("/books/{book_ref}/chapters/{chapter_ref}", summary="改章标题 / 访问标识（正文请用节级接口）")
def update_chapter(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    body: ChapterUpdate,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)

    def action() -> dict[str, object]:
        chapters_service.update_chapter(
            session,
            chapter,
            title=body.title,
            slug_raw=body.slug,
            actor=principal,  # type: ignore[arg-type]
            ip=client_ip(request),
        )
        return _chapter_json(chapter)

    payload = body.model_dump(exclude_unset=True)
    return _write(request, session, principal, op=f"chapter.update:{chapter.id}", payload=payload, action=action)


@router.post("/books/{book_ref}/chapters/{chapter_ref}/status", summary="发布或撤回章节")
def set_chapter_status(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    body: StatusChange,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)

    def action() -> dict[str, object]:
        chapters_service.set_status(session, chapter, body.status, actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
        return _chapter_json(chapter)

    return _write(
        request, session, principal, op=f"chapter.status:{chapter.id}", payload={"status": body.status}, action=action
    )


@router.post("/books/{book_ref}/chapters/{chapter_ref}/move", summary="调整章节顺序")
def move_chapter(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    body: MoveRequest,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    if body.direction is None and body.position is None:
        raise ValidationFailed("请提供 direction（-1/1）或 position（从 1 开始）")

    def action() -> dict[str, object]:
        if body.position is not None:
            siblings = chapters_service.ordered_chapters(session, book.id)
            ids = [item.id for item in siblings]
            if chapter.id not in ids:
                raise NotFound("章节不存在")
            ids.remove(chapter.id)
            target = max(0, min(len(ids), body.position - 1))
            ids.insert(target, chapter.id)
            chapters_service.reorder_chapters(session, book.id, ids, actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
        else:
            chapters_service.move_chapter(
                session, chapter, 1 if (body.direction or 0) >= 0 else -1, actor=principal, ip=client_ip(request)  # type: ignore[arg-type]
            )
        siblings = chapters_service.ordered_chapters(session, book.id)
        return {"items": [_chapter_json(item) for item in siblings]}

    return _write(request, session, principal, op=f"chapter.move:{chapter.id}", payload=body.model_dump(), action=action)


@router.post("/books/{book_ref}/chapters/{chapter_ref}/delete", summary="软删除章节（建议先 dry_run）")
def delete_chapter(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    if _dry_run(request):
        return JSONResponse({"dry_run": True, "would_delete": _chapter_json(chapter)})
    _require_confirm(request, "章节")

    def action() -> dict[str, object]:
        chapters_service.soft_delete_chapter(session, chapter, actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
        return {"deleted": True, "chapter": _chapter_json(chapter)}

    return _write(request, session, principal, op=f"chapter.delete:{chapter.id}", payload={}, action=action)


@router.post("/books/{book_ref}/chapters/{chapter_ref}/restore", summary="恢复章节")
def restore_chapter(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)

    def action() -> dict[str, object]:
        chapters_service.restore_chapter(session, chapter, actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
        return {"restored": True, "chapter": _chapter_json(chapter)}

    return _write(request, session, principal, op=f"chapter.restore:{chapter.id}", payload={}, action=action)


@router.post("/books/{book_ref}/chapters/batch", summary="批量发布 / 撤回 / 删除（逐条返回结果）")
def batch_chapters(
    request: Request,
    book_ref: str,
    body: BatchRequest,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    if body.action == "delete":
        _require_confirm(request, "章节")

    def action() -> dict[str, object]:
        results: list[dict[str, object]] = []
        for chapter_id in body.chapter_ids:
            try:
                with session.begin_nested():
                    chapter = session.get(Chapter, chapter_id)
                    if chapter is None or chapter.book_id != book.id:
                        raise NotFound(f"章节 {chapter_id} 不存在")
                    if body.action == "publish":
                        chapters_service.set_status(session, chapter, STATUS_PUBLISHED, actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
                    elif body.action == "unpublish":
                        chapters_service.set_status(session, chapter, "draft", actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
                    else:
                        chapters_service.soft_delete_chapter(session, chapter, actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
                results.append({"chapter_id": chapter_id, "ok": True})
            except Exception as exc:  # 单条失败不影响其余
                results.append({"chapter_id": chapter_id, "ok": False, "error": str(exc)})
        failed = sum(1 for item in results if not item["ok"])
        return {"action": body.action, "results": results, "ok_count": len(results) - failed, "failed_count": failed}

    return _write(
        request,
        session,
        principal,
        op=f"chapter.batch:{book.id}",
        payload=body.model_dump(),
        action=action,
    )


# ------------------------------------------------------------------ 重排


@router.post("/books/{book_ref}/chapters/reorder", summary="按有序 id 列表重排整本 Book 的章节")
def reorder_chapters(
    request: Request,
    book_ref: str,
    body: ReorderRequest,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)

    def action() -> dict[str, object]:
        ordered = chapters_service.reorder_chapters(
            session,
            book.id,
            body.chapter_ids,
            actor=principal,  # type: ignore[arg-type]
            ip=client_ip(request),
        )
        return {
            "order": [item.id for item in ordered],
            "chapters": [_chapter_json(item) for item in ordered],
        }

    return _write(
        request,
        session,
        principal,
        op=f"chapter.reorder:{book.id}",
        payload=body.model_dump(),
        action=action,
    )


# ------------------------------------------------------------------ 节


def _section_payload_files(raw_body: dict[str, object]) -> dict[str, object]:
    """JSON 建节：正文与格式都在 body 里。"""
    parsed = SectionCreate.model_validate(raw_body)
    return {
        "title": parsed.title,
        "content": parsed.content,
        "slug": parsed.slug,
        "format": parsed.format or "",
        "note": parsed.note,
    }


async def _read_form_sections(request: Request, settings) -> tuple[list[dict[str, object]], dict[str, object]]:
    """multipart 建节：每个 file 字段生成一节，字段里可覆盖标题 / 格式 / 备注。"""
    form = await request.form()
    fields: dict[str, object] = {
        "title": str(form.get("title") or ""),
        "content": str(form.get("content") or ""),
        "slug": str(form.get("slug") or ""),
        "format": str(form.get("format") or ""),
        "note": str(form.get("note") or ""),
    }
    encoding = str(form.get("encoding") or "")
    files: list[dict[str, object]] = []
    candidates = [
        upload
        for upload in list(form.getlist("file")) + list(form.getlist("upload"))
        if upload is not None and getattr(upload, "filename", "")
    ]
    if len(candidates) > settings.max_upload_files:
        raise ValidationFailed(f"一次最多上传 {settings.max_upload_files} 个文件")
    for upload in candidates:
        # 分块读：超大文件在读的过程中就 413，不会先占满内存
        data = await read_limited(upload, settings.max_upload_bytes)
        try:
            detected = detect_format(upload.filename)
            text = decode_with_hint(data, encoding or None)
        except UnsupportedFormat as exc:
            raise ValidationFailed(str(exc)) from exc
        except EncodingError as exc:
            raise ValidationFailed(str(exc)) from exc
        files.append(
            {"title": title_from_filename(upload.filename), "format": detected, "raw": text}
        )
    if not files and str(fields["content"]).strip():
        files.append(
            {
                "title": str(fields["title"]) or "正文",
                "format": fields["format"] or None,
                "raw": str(fields["content"]),
            }
        )
    if not files:
        raise ValidationFailed("请提供 content 字段或上传文件")
    return files, fields


@router.get("/books/{book_ref}/chapters/{chapter_ref}/sections", summary="列出该章的所有节")
def list_sections(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    include_deleted: bool = Query(default=False),
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    rows = sections_service.ordered_sections(
        session, chapter.id, include_deleted=include_deleted
    )
    return JSONResponse(
        {"chapter": _chapter_json(chapter), "items": [_section_json(row) for row in rows]}
    )


@router.get(
    "/books/{book_ref}/chapters/{chapter_ref}/sections/{section_ref}",
    summary="读取单个节（默认带正文）",
)
def get_section_detail(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    section_ref: str,
    with_content: bool = Query(default=True, description="是否返回正文（content_raw / content_rendered）"),
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    section = _section(session, chapter, section_ref)
    return JSONResponse(
        _section_json(
            section,
            chapter=chapter,
            book=book,
            with_content=with_content,
            root_path=request.app.state.settings.root_path,
        )
    )


@router.post(
    "/books/{book_ref}/chapters/{chapter_ref}/sections",
    status_code=201,
    summary="新建节（JSON 正文或 multipart 上传，多文件 = 多节）",
)
async def create_section(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    settings = request.app.state.settings
    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("multipart/form-data"):
        files, fields = await _read_form_sections(request, settings)
    else:
        fields = _section_payload_files(await request.json())
        files = [
            {
                "title": str(fields["title"]),
                "format": fields["format"] or None,
                "raw": str(fields["content"]),
            }
        ]

    def action() -> dict[str, object]:
        created = []
        slug = str(fields["slug"])
        for item in files:
            created.append(
                sections_service.create_section(
                    session,
                    chapter,
                    title=str(item.get("title") or fields["title"]),
                    raw=str(item["raw"]),
                    fmt=item.get("format"),  # type: ignore[arg-type]
                    slug_raw=slug if len(files) == 1 else "",
                    actor=principal,  # type: ignore[arg-type]
                    ip=client_ip(request),
                    note=str(fields["note"]) or "新建节（API）",
                    max_chars=settings.max_content_chars,
                )
            )
            slug = ""
        if len(created) == 1:
            return _section_json(created[0], chapter=chapter, book=book, with_content=True)
        return {
            "chapter": _chapter_json(chapter),
            "items": [
                _section_json(item, chapter=chapter, book=book, with_content=True)
                for item in created
            ],
        }

    payload = {
        "title": str(fields["title"]),
        "slug": str(fields["slug"]),
        "format": str(fields["format"]),
        "note": str(fields["note"]),
        "files": [{"title": item["title"], "format": item["format"], "raw": item["raw"]} for item in files],
    }
    return _write(
        request,
        session,
        principal,
        op=f"section.create:{chapter.id}",
        payload=payload,
        action=action,
        status_code=201,
    )


@router.patch(
    "/books/{book_ref}/chapters/{chapter_ref}/sections/{section_ref}",
    summary="替换节内容 / 改标题 / 改 slug / 改格式",
)
def replace_section(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    section_ref: str,
    body: SectionReplace,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    section = _section(session, chapter, section_ref)
    settings = request.app.state.settings
    base_version = body.base_version
    header_version = request.headers.get("if-match", "").strip().strip('"')
    if base_version is None and header_version.isdigit():
        base_version = int(header_version)

    def action() -> dict[str, object]:
        sections_service.replace_content(
            session,
            section,
            title=body.title,
            raw=body.content,
            fmt=body.format,
            slug_raw=body.slug,
            base_version=base_version,
            actor=principal,  # type: ignore[arg-type]
            ip=client_ip(request),
            note=body.note or "替换内容（API）",
            max_chars=settings.max_content_chars,
            retention=settings.version_retention,
        )
        return _section_json(section, chapter=chapter, book=book, with_content=True)

    payload = body.model_dump(exclude_unset=True)
    return _write(
        request,
        session,
        principal,
        op=f"section.replace:{section.id}",
        payload=payload,
        action=action,
    )


@router.post(
    "/books/{book_ref}/chapters/{chapter_ref}/sections/{section_ref}/move",
    summary="章内调整节顺序",
)
def move_section(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    section_ref: str,
    body: MoveRequest,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    section = _section(session, chapter, section_ref)
    if body.direction is None and body.position is None:
        raise ValidationFailed("请提供 direction（-1/1）或 position（从 1 开始）")

    def action() -> dict[str, object]:
        if body.position is not None:
            siblings = sections_service.ordered_sections(session, chapter.id)
            ids = [item.id for item in siblings]
            if section.id not in ids:
                raise NotFound("节不存在")
            ids.remove(section.id)
            target = max(0, min(len(ids), body.position - 1))
            ids.insert(target, section.id)
            sections_service.reorder_sections(
                session, chapter, ids, actor=principal, ip=client_ip(request)  # type: ignore[arg-type]
            )
        else:
            sections_service.move_section(
                session,
                section,
                1 if (body.direction or 0) >= 0 else -1,
                actor=principal,  # type: ignore[arg-type]
                ip=client_ip(request),
            )
        siblings = sections_service.ordered_sections(session, chapter.id)
        return {"items": [_section_json(item, chapter=chapter, book=book) for item in siblings]}

    return _write(
        request,
        session,
        principal,
        op=f"section.move:{section.id}",
        payload=body.model_dump(),
        action=action,
    )


@router.post(
    "/books/{book_ref}/chapters/{chapter_ref}/sections/{section_ref}/delete",
    summary="软删除节（建议先 dry_run）",
)
def delete_section(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    section_ref: str,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    section = _section(session, chapter, section_ref)
    if _dry_run(request):
        return JSONResponse({"dry_run": True, "would_delete": _section_json(section, chapter=chapter, book=book)})
    _require_confirm(request, "节")

    def action() -> dict[str, object]:
        sections_service.delete_section(
            session, section, actor=principal, ip=client_ip(request)  # type: ignore[arg-type]
        )
        return {"deleted": True, "section": _section_json(section, chapter=chapter, book=book)}

    return _write(
        request,
        session,
        principal,
        op=f"section.delete:{section.id}",
        payload={},
        action=action,
    )


@router.post(
    "/books/{book_ref}/chapters/{chapter_ref}/sections/{section_ref}/restore",
    summary="恢复节",
)
def restore_section(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    section_ref: str,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    section = sections_service.get_section(session, chapter, section_ref, include_deleted=True)

    def action() -> dict[str, object]:
        sections_service.restore_section(
            session, section, actor=principal, ip=client_ip(request)  # type: ignore[arg-type]
        )
        return {"restored": True, "section": _section_json(section, chapter=chapter, book=book)}

    return _write(
        request,
        session,
        principal,
        op=f"section.restore:{section.id}",
        payload={},
        action=action,
    )


# ------------------------------------------------------------------ 版本（节级）


@router.get(
    "/books/{book_ref}/chapters/{chapter_ref}/sections/{section_ref}/versions",
    summary="节的版本列表",
)
def list_versions(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    section_ref: str,
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    section = _section(session, chapter, section_ref)
    versions = sections_service.list_versions(session, section)
    return JSONResponse(
        {
            "section": _section_json(section, chapter=chapter, book=book),
            "items": [
                {
                    "version_no": version.version_no,
                    "title": version.title,
                    "format": version.format,
                    "note": version.note,
                    "created_at": _iso(version.created_at),
                }
                for version in versions
            ],
        }
    )


@router.get(
    "/books/{book_ref}/chapters/{chapter_ref}/sections/{section_ref}/versions/{version_no}",
    summary="读取节的单个版本",
)
def get_version(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    section_ref: str,
    version_no: int,
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    section = _section(session, chapter, section_ref)
    version = sections_service.get_version(session, section, version_no)
    return JSONResponse(
        {
            "version_no": version.version_no,
            "title": version.title,
            "format": version.format,
            "content_raw": version.content_raw,
            "note": version.note,
            "created_at": _iso(version.created_at),
        }
    )


@router.get(
    "/books/{book_ref}/chapters/{chapter_ref}/sections/{section_ref}/diff",
    summary="对比节的两个版本",
)
def diff_versions(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    section_ref: str,
    a: int | None = Query(default=None),
    b: int | None = Query(default=None),
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    section = _section(session, chapter, section_ref)
    versions = sections_service.list_versions(session, section)
    if not versions:
        raise NotFound("该节还没有历史版本")
    left = a if a is not None else versions[-1].version_no
    right = b if b is not None else versions[0].version_no
    diff = sections_service.diff_versions(session, section, left, right)
    return JSONResponse(
        {
            "left": left,
            "right": right,
            "identical": diff["identical"],
            "truncated": diff["truncated"],
            "rows": diff["rows"],
        }
    )


@router.post(
    "/books/{book_ref}/chapters/{chapter_ref}/sections/{section_ref}/rollback/{version_no}",
    summary="回滚到节的指定版本",
)
def rollback_section(
    request: Request,
    book_ref: str,
    chapter_ref: str,
    section_ref: str,
    version_no: int,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = _book(session, book_ref)
    chapter = _chapter(session, book, chapter_ref)
    section = _section(session, chapter, section_ref)
    settings = request.app.state.settings

    def action() -> dict[str, object]:
        sections_service.rollback(
            session,
            section,
            version_no,
            actor=principal,  # type: ignore[arg-type]
            ip=client_ip(request),
            retention=settings.version_retention,
            max_chars=settings.max_content_chars,
        )
        return _section_json(section, chapter=chapter, book=book, with_content=True)

    return _write(
        request,
        session,
        principal,
        op=f"section.rollback:{section.id}",
        payload={"version_no": version_no},
        action=action,
    )


# ------------------------------------------------------------------ 回收站 / 账号 / 设置 / 审计


@router.get("/trash", summary="回收站（已删除的 Book 与章节）")
def trash(
    request: Request,
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    scope = list(principal.book_ids)
    book_stmt = select(Book).where(Book.deleted_at.is_not(None))
    chapter_stmt = (
        select(Chapter, Book)
        .join(Book, Book.id == Chapter.book_id)
        .where(Chapter.deleted_at.is_not(None))
    )
    section_stmt = (
        select(ChapterSection, Chapter, Book)
        .join(Chapter, Chapter.id == ChapterSection.chapter_id)
        .join(Book, Book.id == Chapter.book_id)
        .where(ChapterSection.deleted_at.is_not(None))
    )
    if scope:
        book_stmt = book_stmt.where(Book.id.in_(scope))
        chapter_stmt = chapter_stmt.where(Book.id.in_(scope))
        section_stmt = section_stmt.where(Book.id.in_(scope))
    deleted_books = list(session.execute(book_stmt.order_by(Book.deleted_at.desc())).scalars())
    deleted_chapters = session.execute(chapter_stmt.order_by(Chapter.deleted_at.desc())).all()
    deleted_sections = session.execute(section_stmt.order_by(ChapterSection.deleted_at.desc())).all()
    return JSONResponse(
        {
            "books": [_book_json(book) for book in deleted_books],
            "chapters": [
                {**_chapter_json(chapter), "book": {"id": book.id, "slug": book.slug, "title": book.title}}
                for chapter, book in deleted_chapters
            ],
            # 单节软删不会进 Book/章回收站，这里单独列出，便于 restore
            "sections": [
                {
                    **_section_json(section, chapter=chapter, book=book),
                    "book": {"id": book.id, "slug": book.slug, "title": book.title},
                    "chapter": {"id": chapter.id, "slug": chapter.slug, "title": chapter.title},
                }
                for section, chapter, book in deleted_sections
            ],
        }
    )


@router.get("/users", summary="账号列表")
def list_users(
    request: Request,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    rows = list(session.execute(select(User).order_by(User.created_at.asc())).scalars())
    return JSONResponse(
        {
            "items": [
                {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "role": user.role,
                    "active": user.is_active,
                    "last_login_at": _iso(user.last_login_at),
                    "created_at": _iso(user.created_at),
                }
                for user in rows
            ]
        }
    )


@router.post("/users", status_code=201, summary="创建账号")
def create_user(
    request: Request,
    body: UserCreate,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def action() -> dict[str, object]:
        user = users_service.create_user(
            session,
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            role=body.role,
        )
        audit_service.record(
            session,
            actor=principal,  # type: ignore[arg-type]
            action="user.create",
            target_type="user",
            target_id=user.id,
            target_label=user.username,
            detail={"role": user.role, "via": "api"},
            ip=client_ip(request),
        )
        return {"id": user.id, "username": user.username, "role": user.role, "active": user.is_active}

    return _write(
        request,
        session,
        principal,
        op="user.create",
        payload={"username": body.username, "role": body.role, "display_name": body.display_name},
        action=action,
        status_code=201,
    )


@router.post("/users/{user_id}/toggle", summary="启用 / 停用账号")
def toggle_user(
    request: Request,
    user_id: int,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    target = session.get(User, user_id)
    if target is None:
        raise NotFound("账号不存在")

    def action() -> dict[str, object]:
        users_service.set_active(target, not target.is_active)
        audit_service.record(
            session,
            actor=principal,  # type: ignore[arg-type]
            action="user.toggle",
            target_type="user",
            target_id=target.id,
            target_label=target.username,
            detail={"is_active": target.is_active, "via": "api"},
            ip=client_ip(request),
        )
        return {"id": target.id, "username": target.username, "active": target.is_active}

    return _write(request, session, principal, op=f"user.toggle:{user_id}", payload={}, action=action)


@router.post("/users/{user_id}/password", summary="重置账号密码")
def reset_password(
    request: Request,
    user_id: int,
    body: PasswordReset,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    target = session.get(User, user_id)
    if target is None:
        raise NotFound("账号不存在")

    def action() -> dict[str, object]:
        users_service.set_password(target, body.password)
        audit_service.record(
            session,
            actor=principal,  # type: ignore[arg-type]
            action="user.password_reset",
            target_type="user",
            target_id=target.id,
            target_label=target.username,
            detail={"via": "api"},
            ip=client_ip(request),
        )
        return {"id": target.id, "username": target.username, "password_reset": True}

    return _write(
        request, session, principal, op=f"user.password:{user_id}", payload={"user_id": user_id}, action=action
    )


@router.get("/settings", summary="读取站点设置")
def read_settings(
    request: Request,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    values = settings_service.load_settings(session, request.app.state.settings)
    return JSONResponse({"values": values})


@router.put("/settings", summary="保存站点设置")
def save_settings(
    request: Request,
    body: SettingsUpdate,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    if not body.site_name.strip():
        raise ValidationFailed("站点名称不能为空")

    def action() -> dict[str, object]:
        saved = settings_service.save_settings(
            session,
            {"site_name": body.site_name, "site_footer": body.site_footer, "home_intro": body.home_intro},
        )
        audit_service.record(
            session,
            actor=principal,  # type: ignore[arg-type]
            action="settings.update",
            target_type="settings",
            target_label="site",
            detail={"saved": saved, "via": "api"},
            ip=client_ip(request),
        )
        return {"values": saved}

    return _write(request, session, principal, op="settings.update", payload=body.model_dump(), action=action)


@router.get("/audit", summary="查询审计日志")
def audit_log(
    request: Request,
    book_id: int | None = Query(default=None),
    actor: str = Query(default=""),
    action: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    action_filter = action.strip()
    if principal.book_ids:
        raise Forbidden("受限 Token 不能读取全站审计（含其它 Book 的操作记录）")
    total = audit_service.count_rows(
        session, book_id=book_id, actor=actor, action=action_filter
    )
    rows = audit_service.query_rows(
        session,
        book_id=book_id,
        actor=actor,
        action=action_filter,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return JSONResponse(
        {
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": row.id,
                    "actor": row.actor_name,
                    "action": row.action,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "target_label": row.target_label,
                    "book_id": row.book_id,
                    "detail": audit_service.detail_of(row),
                    "ip": row.ip,
                    "created_at": _iso(row.created_at),
                }
                for row in rows
            ],
        }
    )


@router.get("/audit.csv", summary="导出审计日志 CSV（与查询接口相同的过滤条件）")
def audit_export(
    request: Request,
    book_id: int | None = Query(default=None),
    actor: str = Query(default=""),
    action: str = Query(default=""),
    limit: int = Query(default=10000, ge=1, le=50000),
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> Response:
    if principal.book_ids:
        raise Forbidden("受限 Token 不能导出全站审计（含其它 Book 的操作记录）")
    rows = audit_service.query_rows(
        session, book_id=book_id, actor=actor, action=action.strip(), limit=limit
    )
    payload = audit_service.export_csv(rows)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=payload.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bookhub-audit-{stamp}.csv"'},
    )


@router.post("/audit/cleanup", summary="按保留期清理审计（默认预览）")
def audit_cleanup(
    request: Request,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    settings = request.app.state.settings
    days = settings.audit_retention_days
    if days <= 0:
        session.commit()
        return JSONResponse(
            {"applied": False, "reason": "AUDIT_RETENTION_DAYS=0（永久保留）", "retention_days": 0}
        )
    cutoff = utcnow() - timedelta(days=days)
    pending = audit_service.count_rows(session, until=cutoff)
    if not _confirmed(request):
        oldest = session.execute(
            select(func.min(AuditLog.created_at)).where(AuditLog.created_at < cutoff)
        ).scalar()
        session.commit()
        return JSONResponse(
            {
                "applied": False,
                "would_delete": pending,
                "oldest": _iso(oldest),
                "cutoff": _iso(cutoff),
                "retention_days": days,
            }
        )
    result = audit_service.cleanup(session, days)
    session.commit()
    return JSONResponse(
        {
            "applied": True,
            "deleted": result["deleted"],
            "cutoff": _iso(result["cutoff"]),
            "retention_days": days,
        }
    )


# ------------------------------------------------------------------ Token


@router.get("/tokens", summary="列出 API Token")
def list_tokens(
    request: Request,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    rows = token_service.list_tokens(session)
    return JSONResponse({"items": [_token_json(token, session=session) for token in rows]})


@router.post("/tokens", status_code=201, summary="签发 API Token（明文只返回一次）")
def create_token(
    request: Request,
    body: TokenCreate,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    book_ids: list[int] = []
    for ref in body.books:
        ref = (ref or "").strip()
        if not ref:
            continue
        book_ids.append(books_service.get_book(session, ref, include_deleted=True).id)
    # 防御性：Token 的权限不能超出签发者自身（作用域按 read < write < admin 包含关系比较）
    requested_scopes = token_service.normalize_scopes(body.scopes)
    if not all(principal.allows(scope) for scope in requested_scopes):
        raise Forbidden("不能签发超出自身作用域的 Token")
    if principal.book_ids and not set(book_ids) <= set(principal.book_ids):
        raise Forbidden("不能签发超出自身 Book 范围的 Token")
    token, raw = token_service.issue_token(
        session,
        name=body.name,
        scopes=body.scopes,
        expires_in_days=body.expires_in_days,
        book_ids=book_ids,
    )
    audit_service.record(
        session,
        actor=principal,  # type: ignore[arg-type]
        action="token.create",
        target_type="token",
        target_id=token.id,
        target_label=token.name,
        detail={"scopes": body.scopes, "book_ids": book_ids},
        ip=client_ip(request),
    )
    session.commit()
    payload = {**_token_json(token, session=session), "token": raw}
    return JSONResponse(payload, status_code=201)


@router.delete("/tokens/{token_id}", summary="吊销 API Token")
def revoke_token(
    request: Request,
    token_id: int,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    token = token_service.get_token(session, token_id)
    if token is None:
        raise NotFound("Token 不存在")
    if token.id == principal.token_id:
        raise Conflict("不能吊销当前正在使用的 Token")
    token_service.revoke_token(session, token)
    session.commit()
    return JSONResponse({"revoked": True, "id": token.id, "name": token.name})


# ------------------------------------------------------------------ 媒体库


def _media_json(asset, book: Book, settings, *, referenced: bool | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": asset.id,
        "filename": asset.filename,
        "stored_name": asset.stored_name,
        "mime": asset.mime,
        "kind": asset.kind,
        "byte_size": asset.byte_size,
        "checksum": asset.checksum,
        "url": media_service.media_url(book.slug, asset.stored_name, settings.root_path),
        "created_at": _iso(asset.created_at),
        "deleted_at": _iso(asset.deleted_at),
    }
    if referenced is not None:
        payload["referenced"] = referenced
    return payload


@router.get("/books/{book_ref}/media", summary="列出 Book 的媒体资源（含引用状态与配额）")
def list_media(
    request: Request,
    book_ref: str,
    include_deleted: bool = Query(default=True, description="是否包含已软删除资源"),
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    settings = request.app.state.settings
    book = _book(session, book_ref)
    referenced = media_service.referenced_names(session, book.id)
    assets = media_service.list_media(session, book.id, include_deleted=include_deleted)
    return JSONResponse(
        {
            "book": {"id": book.id, "slug": book.slug, "title": book.title},
            "usage": media_service.usage(session, book.id, settings),
            "items": [
                _media_json(asset, book, settings, referenced=asset.stored_name in referenced)
                for asset in assets
            ],
        }
    )


@router.post("/books/{book_ref}/media", status_code=201, summary="上传媒体（multipart，支持幂等）")
async def upload_media(
    request: Request,
    book_ref: str,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    settings = request.app.state.settings
    book = _book(session, book_ref)
    content_type = (request.headers.get("content-type") or "").lower()
    if not content_type.startswith("multipart/form-data"):
        raise ValidationFailed("请使用 multipart/form-data 上传文件（字段名 file 或 upload）")
    form = await request.form()
    upload = form.get("file") or form.get("upload")
    if upload is None or not getattr(upload, "filename", ""):
        raise ValidationFailed("请在 file 或 upload 字段里提供文件")
    filename = upload.filename or "upload.bin"
    data = await read_limited(upload, settings.media_max_bytes, label="文件")
    if not data:
        raise ValidationFailed("文件内容为空")

    def action() -> dict[str, object]:
        asset = media_service.save_media(
            session,
            book=book,
            filename=filename,
            data=data,
            settings=settings,
            actor=principal,  # type: ignore[arg-type]
            ip=client_ip(request),
        )
        return _media_json(asset, book, settings, referenced=False)

    payload = {
        "book_id": book.id,
        "filename": filename,
        "checksum": hashlib.sha256(data).hexdigest(),
        "byte_size": len(data),
    }
    return _write(
        request,
        session,
        principal,
        op=f"media.upload:{book.id}",
        payload=payload,
        action=action,
        status_code=201,
    )


@router.delete("/books/{book_ref}/media/{media_id}", summary="删除媒体资源（软删除，需 confirm）")
def delete_media(
    request: Request,
    book_ref: str,
    media_id: int,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    settings = request.app.state.settings
    book = _book(session, book_ref)
    asset = media_service.find_media_by_id(session, book, media_id)
    referenced = asset.stored_name in media_service.referenced_names(session, book.id)

    if _dry_run(request):
        session.commit()
        return JSONResponse(
            {
                "dry_run": True,
                "asset": _media_json(asset, book, settings, referenced=referenced),
                "warning": "删除是软删除：已发布章节里的图片仍会显示，但地址不再公开可读",
            }
        )
    _require_confirm(request, "媒体资源")

    def action() -> dict[str, object]:
        media_service.delete_media(
            session, book=book, asset=asset, actor=principal, ip=client_ip(request)  # type: ignore[arg-type]
        )
        return _media_json(asset, book, settings, referenced=referenced)

    payload = {"book_id": book.id, "media_id": asset.id}
    return _write(
        request,
        session,
        principal,
        op=f"media.delete:{book.id}",
        payload=payload,
        action=action,
    )


@router.post("/books/{book_ref}/media/cleanup", summary="清理未引用媒体（默认预览）")
def cleanup_media(
    request: Request,
    book_ref: str,
    principal: Principal = Depends(require_scope("write")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    settings = request.app.state.settings
    book = _book(session, book_ref)

    def action() -> dict[str, object]:
        result = media_service.cleanup(
            session,
            book=book,
            settings=settings,
            actor=principal,  # type: ignore[arg-type]
            confirm=_confirmed(request),
            ip=client_ip(request),
        )
        return {**result, "usage": media_service.usage(session, book.id, settings)}

    payload = {"book_id": book.id, "confirm": _confirmed(request)}
    return _write(
        request,
        session,
        principal,
        op=f"media.cleanup:{book.id}",
        payload=payload,
        action=action,
    )


# ------------------------------------------------------------------ Webhook


class WebhookCreate(BaseModel):
    url: str = Field(description="回调地址，必须 http(s) 绝对 URL")
    events: list[str] = Field(min_length=1, description="订阅的事件")
    description: str = ""


def _webhook_json(hook, *, with_secret: bool = False) -> dict[str, object]:
    payload = webhooks_service.detail_of(hook)
    payload["last_sent_at"] = _iso(payload.get("last_sent_at"))  # type: ignore[arg-type]
    payload["created_at"] = _iso(payload.get("created_at"))  # type: ignore[arg-type]
    if with_secret:
        payload["secret"] = hook.secret
    return payload


def _delivery_json(delivery) -> dict[str, object]:
    return {
        "id": delivery.id,
        "webhook_id": delivery.webhook_id,
        "event": delivery.event,
        "status_code": delivery.status_code,
        "error": delivery.error,
        "attempts": delivery.attempts,
        "created_at": _iso(delivery.created_at),
        "delivered_at": _iso(delivery.delivered_at),
    }


@router.get("/webhooks", summary="列出 Webhook（含最近状态）")
def list_webhooks(
    request: Request,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    hooks = webhooks_service.list_hooks(session)
    return JSONResponse(
        {
            "items": [_webhook_json(hook) for hook in hooks],
            "events": list(webhooks_service.EVENTS),
        }
    )


@router.post("/webhooks", status_code=201, summary="登记 Webhook（密钥只返回一次）")
def create_webhook(
    request: Request,
    body: WebhookCreate,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    hook, secret = webhooks_service.create(
        session,
        url=body.url,
        events=body.events,
        description=body.description,
        created_by=principal.id,
        actor=principal,  # type: ignore[arg-type]
        ip=client_ip(request),
    )
    session.commit()
    return JSONResponse({**_webhook_json(hook, with_secret=True), "secret": secret}, status_code=201)


@router.delete("/webhooks/{hook_id}", summary="停用 Webhook")
def delete_webhook(
    request: Request,
    hook_id: int,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    hook = webhooks_service.get_hook(session, hook_id)
    webhooks_service.deactivate(session, hook, actor=principal, ip=client_ip(request))  # type: ignore[arg-type]
    session.commit()
    return JSONResponse({"deactivated": True, "id": hook.id})


@router.get("/webhooks/{hook_id}/deliveries", summary="查看投递记录")
def list_deliveries(
    request: Request,
    hook_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    hook = webhooks_service.get_hook(session, hook_id)
    rows = webhooks_service.list_deliveries(session, hook.id, limit=limit)
    return JSONResponse({"items": [_delivery_json(row) for row in rows]})


@router.post("/webhooks/{hook_id}/test", summary="发送测试事件 webhook.test")
def test_webhook(
    request: Request,
    hook_id: int,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    hook = webhooks_service.get_hook(session, hook_id)
    if not hook.is_active:
        raise ValidationFailed("该 Webhook 已停用")
    deliveries = webhooks_service.dispatch(
        session, "webhook.test", {"message": "bookhub webhook test"}, hooks=[hook]
    )
    # 「测试」按钮要立刻给出结果，所以这一条同步发送（其余事件仍走后台投递）
    for delivery in deliveries:
        webhooks_service.send_now(session, delivery)
    audit_service.record(
        session,
        actor=principal,  # type: ignore[arg-type]
        action="webhook.test",
        target_type="webhook",
        target_id=hook.id,
        target_label=hook.url,
        detail={"deliveries": len(deliveries)},
        ip=client_ip(request),
    )
    session.commit()
    item = _delivery_json(deliveries[0]) if deliveries else None
    return JSONResponse({"ok": bool(item and item["status_code"] and 200 <= int(item["status_code"]) < 300), "delivery": item})


@router.post("/deliveries/{delivery_id}/retry", summary="重试一条失败投递")
def retry_delivery(
    request: Request,
    delivery_id: int,
    principal: Principal = Depends(require_scope("admin")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    delivery = webhooks_service.get_delivery(session, delivery_id)
    webhooks_service.deliver_now(session, delivery)
    audit_service.record(
        session,
        actor=principal,  # type: ignore[arg-type]
        action="webhook.retry",
        target_type="webhook",
        target_id=delivery.webhook_id,
        detail={"delivery_id": delivery.id, "attempts": delivery.attempts},
        ip=client_ip(request),
    )
    session.commit()
    return JSONResponse(_delivery_json(delivery))


# ------------------------------------------------------------------ 站点元信息（AI 工具探测用）


@router.get("/meta", summary="管理接口元信息（作用域、能力与限制）")
def meta(
    request: Request,
    principal: Principal = Depends(require_scope("read")),
    session: Session = Depends(get_session),
) -> JSONResponse:
    settings = request.app.state.settings
    return JSONResponse(
        {
            "token": {"name": principal.name, "scopes": list(principal.scopes)},
            "limits": {
                "max_upload_bytes": settings.max_upload_bytes,
                "max_upload_files": settings.max_upload_files,
                "max_content_chars": settings.max_content_chars,
                "media_max_bytes": settings.media_max_bytes,
                "media_quota_bytes": settings.media_quota_bytes,
                "media_allowed_types": settings.media_allowed_types,
                "version_retention": settings.version_retention,
                "rate_limit_per_minute": settings.admin_api_rate_limit,
            },
            "capabilities": [
                "books",
                "chapters",
                "sections",  # 章下面的节：/books/{ref}/chapters/{ref}/sections
                "book_groups",  # Book 分组：/groups（首页分区）
                "versions",  # 节级版本：/sections/{ref}/versions
                "media",
                "webhooks",
                "trash",
                "users",
                "settings",
                "audit",
                "tokens",
            ],
            "docs": {"openapi": f"{settings.root_path}/openapi.json"},
        }
    )


__all__ = ["router", "Principal"]
