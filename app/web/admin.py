"""管理端路由：Book、章、节、版本、账号、站点设置与审计。"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import AppError, NotFound, ValidationFailed, error_body
from app.middleware import client_ip
from app.models import (
    FORMATS,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    STATUSES,
    AuditLog,
    Book,
    Chapter,
    ChapterSection,
    User,
)
from app.services import audit as audit_service
from app.services import book_groups, ranking
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import media as media_service
from app.services import sections as sections_service
from app.services.encoding import (
    EmptyContent,
    EncodingError,
    UnsupportedFormat,
    decode_with_hint,
    detect_format,
    title_from_filename,
)
from app.services.icons import ICON_GROUPS, total_icons
from app.services.settings import load_settings, save_settings
from app.services.users import create_user, set_active, set_password
from app.uploads import read_limited
from app.web.common import (
    absolute_url,
    base_context,
    get_settings,
    paginate,
    require_csrf,
    require_user,
)

router = APIRouter(prefix="/admin", include_in_schema=False)
AUDIT_PAGE_SIZE = 30


def _ctx(request: Request, session: Session, user: User, page_title: str, **extra: object) -> dict[str, object]:
    # 图标面板与媒体上传上限是纯数据，挂在所有管理页上下文里，避免每个渲染分支都传一遍
    context: dict[str, object] = {
        "icon_groups": ICON_GROUPS,
        "icon_total": total_icons(),
        "media_max_label": human_bytes(get_settings(request).media_max_bytes),
    }
    context.update(extra)
    return base_context(request, session, user=user, page_title=page_title, **context)


def _book_or_404(session: Session, book_id: int) -> Book:
    return books_service.get_book(session, int(book_id), include_deleted=True)


def _chapter_or_404(session: Session, book: Book, chapter_id: int) -> Chapter:
    chapter = session.get(Chapter, int(chapter_id))
    if chapter is None or chapter.book_id != book.id:
        raise NotFound("章节不存在")
    return chapter


def _section_or_404(session: Session, chapter: Chapter, section_id: int) -> ChapterSection:
    section = session.get(ChapterSection, int(section_id))
    if section is None or section.chapter_id != chapter.id:
        raise NotFound("节不存在")
    return section


def _render(request: Request, template: str, context: dict[str, object], status_code: int = 200) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, template, context, status_code=status_code)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    page: int = Query(default=1, ge=1),
    group: str = Query(default=""),
    error: str = Query(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    groups = book_groups.list_groups(session)
    group_ref = (group or "").strip()
    # 过滤值可能是 id 也可能是 slug；先解析成组再交给服务层，脏参数就当作没过滤
    selected_group = next(
        (item for item in groups if str(item.id) == group_ref or item.slug == group_ref), None
    )
    book_rows, total = books_service.list_books(
        session,
        visibility=None,
        group=selected_group.id if selected_group is not None else None,
        page=page,
        page_size=20,
        include_deleted=False,
    )
    counts = book_groups.book_counts(session)
    group_map = {item.id: item for item in groups}
    published = books_service.chapter_counts(session, [book.id for book in book_rows])
    all_counts = books_service.chapter_counts(
        session, [book.id for book in book_rows], published_only=False
    )
    stats = ranking.stats_for(session, book_rows)
    items = [
        {
            "book": book,
            "book_group": group_map.get(book.group_id),
            "published": published.get(book.id, 0),
            "total": all_counts.get(book.id, 0),
            "stats": stats.get(book.id, ranking.BookStats()),
            "cover": media_service.cover_url(session, book, get_settings(request)),
        }
        for book in book_rows
    ]
    trash_books = session.execute(
        select(func.count()).select_from(Book).where(Book.deleted_at.is_not(None))
    ).scalar_one()
    trash_chapters = session.execute(
        select(func.count()).select_from(Chapter).where(Chapter.deleted_at.is_not(None))
    ).scalar_one()
    chapter_total = session.execute(
        select(func.count()).select_from(Chapter).where(Chapter.deleted_at.is_(None))
    ).scalar_one()
    section_total = session.execute(
        select(func.count()).select_from(ChapterSection).where(ChapterSection.deleted_at.is_(None))
    ).scalar_one()
    context = _ctx(
        request,
        session,
        user,
        "内容管理",
        items=items,
        pager=paginate(total, page, 20),
        trash_books=trash_books,
        trash_chapters=trash_chapters,
        chapter_total=chapter_total,
        section_total=section_total,
        groups=groups,
        group_counts=counts,
        selected_group=selected_group,
        book_total=sum(counts.values()),
        error=error,
    )
    return _render(request, "admin/dashboard.html", context)


# ---------------------------------------------------------------- Book


def _book_form_context(
    request: Request,
    session: Session,
    user: User,
    *,
    form: dict[str, str],
    error: str,
    mode: str,
    book: Book | None,
) -> dict[str, object]:
    """Book 表单的渲染上下文：新建与编辑、首次打开与校验失败都走这里。"""
    extra: dict[str, object] = {"groups": book_groups.list_groups(session)}
    if book is not None:
        extra["cover"] = media_service.cover_url(session, book, get_settings(request))
        extra["chapter_total"] = books_service.active_chapter_count(session, book.id)
    return _ctx(
        request,
        session,
        user,
        f"编辑 {book.title}" if book is not None else "新建 Book",
        form=form,
        error=error,
        mode=mode,
        book=book,
        **extra,
    )


@router.get("/books/new", response_class=HTMLResponse)
def book_new_form(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    user = require_user(request, session)
    context = _book_form_context(
        request,
        session,
        user,
        form={"title": "", "slug": "", "group": "", "summary": "", "icon": "", "format": "markdown", "html_view": "document", "visibility": "public"},
        error="",
        mode="create",
        book=None,
    )
    return _render(request, "admin/book_form.html", context)


@router.post("/books/new", response_class=HTMLResponse)
def book_new_submit(
    request: Request,
    title: str = Form(default=""),
    slug: str = Form(default=""),
    group: str = Form(default=""),
    summary: str = Form(default=""),
    icon: str = Form(default=""),
    format: str = Form(default=""),
    html_view: str = Form(default=""),
    visibility: str = Form(default="public"),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    form = {"title": title, "slug": slug, "group": group, "summary": summary, "icon": icon, "format": format, "html_view": html_view or "document", "visibility": visibility}
    if not group.strip():
        # 浏览器侧的 required 可以被绕过，所以分组必选在这里也拦一次，且不落库
        context = _book_form_context(
            request, session, user, form=form, error="必须选择分组", mode="create", book=None
        )
        return _render(request, "admin/book_form.html", context, status_code=400)
    try:
        book = books_service.create_book(
            session,
            title=title,
            slug_raw=slug,
            summary=summary,
            icon=icon,
            fmt=format,
            html_view=html_view or None,
            visibility=visibility,
            group=group,
            actor=user,
            ip=client_ip(request),
        )
        session.commit()
    except (AppError, ValueError) as exc:
        session.rollback()
        message = exc.message if isinstance(exc, AppError) else str(exc)
        context = _book_form_context(
            request, session, user, form=form, error=message, mode="create", book=None
        )
        return _render(request, "admin/book_form.html", context, status_code=400)
    return RedirectResponse(
        f"{get_settings(request).root_path}/admin/books/{book.id}?notice=book-created",
        status_code=303,
    )


@router.get("/books/{book_id}", response_class=HTMLResponse)
def book_detail(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    chapters = chapters_service.ordered_chapters(session, book.id)
    counts = sections_service.section_counts(session, [chapter.id for chapter in chapters])
    context = _ctx(
        request,
        session,
        user,
        book.title,
        book=book,
        chapters=chapters,
        section_counts=counts,
        section_total=sum(counts.values()),
        notice=request.query_params.get("notice", ""),
        error=request.query_params.get("error", ""),
        batch=request.query_params.get("batch", ""),
        share_url=absolute_url(request, f"/b/{book.slug}"),
        stats=ranking.stats_of(session, book),
        statuses=(STATUS_DRAFT, STATUS_PUBLISHED),
    )
    return _render(request, "admin/book_detail.html", context)


@router.get("/books/{book_id}/edit", response_class=HTMLResponse)
def book_edit_form(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    form = {
        "title": book.title,
        "slug": book.slug,
        "group": str(book.group_id),
        "summary": book.summary,
        "icon": book.icon,
        "format": book.format,
        "html_view": book.html_view,
        "visibility": book.visibility,
    }
    context = _book_form_context(
        request, session, user, form=form, error="", mode="edit", book=book
    )
    return _render(request, "admin/book_form.html", context)


@router.post("/books/{book_id}/edit", response_class=HTMLResponse)
def book_edit_submit(
    request: Request,
    book_id: int,
    title: str = Form(default=""),
    slug: str = Form(default=""),
    group: str = Form(default=""),
    summary: str = Form(default=""),
    icon: str = Form(default=""),
    format: str = Form(default=""),
    html_view: str = Form(default="inline"),
    visibility: str = Form(default="public"),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    form = {"title": title, "slug": slug, "group": group or str(book.group_id), "summary": summary, "icon": icon, "format": format or book.format, "html_view": html_view, "visibility": visibility}
    if not group.strip():
        # 改归属同样要显式给组：空值可能是表单坏了，不该悄悄沿用旧组
        context = _book_form_context(
            request, session, user, form=form, error="必须选择分组", mode="edit", book=book
        )
        return _render(request, "admin/book_form.html", context, status_code=400)
    try:
        books_service.update_book(
            session,
            book,
            title=title,
            slug_raw=slug,
            summary=summary,
            icon=icon,
            fmt=format or None,
            html_view=html_view or None,
            visibility=visibility,
            group=group,
            actor=user,
            ip=client_ip(request),
        )
        session.commit()
    except (AppError, ValueError) as exc:
        session.rollback()
        message = exc.message if isinstance(exc, AppError) else str(exc)
        context = _book_form_context(
            request, session, user, form=form, error=message, mode="edit", book=book
        )
        return _render(request, "admin/book_form.html", context, status_code=400)
    return RedirectResponse(
        f"{get_settings(request).root_path}/admin/books/{book.id}?notice=book-saved",
        status_code=303,
    )


@router.post("/books/{book_id}/delete")
def book_delete(
    request: Request,
    book_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    try:
        books_service.soft_delete_book(session, book, actor=user, ip=client_ip(request))
        session.commit()
    except AppError as exc:
        # 拒绝原因（例如内置指南不可删）回列表页用提示条呈现，而不是丢一张 400 错误页
        session.rollback()
        target = f"{get_settings(request).root_path}/admin?error={quote(exc.message)}"
        return RedirectResponse(target, status_code=303)
    return RedirectResponse(f"{get_settings(request).root_path}/admin", status_code=303)


@router.post("/books/{book_id}/restore")
def book_restore(
    request: Request,
    book_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    books_service.restore_book(session, book, actor=user, ip=client_ip(request))
    session.commit()
    return RedirectResponse(f"{get_settings(request).root_path}/admin/books/{book.id}", status_code=303)


# ---------------------------------------------------------------- 分组（Book 组）
#
# 分组是 Book 的上级分类（决定首页分区），与 Book 内部的「章 → 节」是两回事。


def _groups_redirect(request: Request, error: str = "") -> RedirectResponse:
    """组管理操作统一回列表页，失败信息用查询参数带回。"""
    target = f"{get_settings(request).root_path}/admin/groups"
    if error:
        return RedirectResponse(f"{target}?error={quote(error)}", status_code=303)
    return RedirectResponse(target, status_code=303)


@router.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    user = require_user(request, session)
    rows = book_groups.list_groups(session)
    counts = book_groups.book_counts(session)
    total_counts = book_groups.book_counts(session, include_deleted=True)
    entries = [
        {
            "group": row,
            "book_count": counts.get(row.id, 0),
            # 回收站里的 Book 仍占外键，删组时也会被算进去，这里显式暴露差额
            "deleted_count": total_counts.get(row.id, 0) - counts.get(row.id, 0),
            "is_default": book_groups.is_default(row),
        }
        for row in rows
    ]
    context = _ctx(
        request,
        session,
        user,
        "分组管理",
        groups=entries,
        book_total=sum(counts.values()),
        error=request.query_params.get("error", ""),
    )
    return _render(request, "admin/groups.html", context)


@router.get("/groups/new", response_class=HTMLResponse)
def book_group_new_form(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    user = require_user(request, session)
    context = _ctx(
        request,
        session,
        user,
        "新建分组",
        group=None,
        form={"title": "", "slug": "", "description": "", "icon": ""},
        error="",
        book_count=0,
    )
    return _render(request, "admin/book_group_form.html", context)


@router.post("/groups/new", response_class=HTMLResponse)
def book_group_new_submit(
    request: Request,
    title: str = Form(default=""),
    slug: str = Form(default=""),
    description: str = Form(default=""),
    icon: str = Form(default=""),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    try:
        book_groups.create(
            session,
            title=title,
            slug_raw=slug,
            description=description,
            icon=icon,
            actor=user,
            ip=client_ip(request),
        )
        session.commit()
    except AppError as exc:
        session.rollback()
        return _groups_redirect(request, exc.message)
    return _groups_redirect(request)


@router.get("/groups/{group_id}/edit", response_class=HTMLResponse)
def book_group_edit_form(
    request: Request,
    group_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    group = book_groups.get_group(session, group_id)
    context = _ctx(
        request,
        session,
        user,
        f"编辑分组 {group.title}",
        group=group,
        form={
            "title": group.title,
            "slug": group.slug,
            "description": group.description,
            "icon": group.icon,
        },
        error="",
        book_count=book_groups.count_books(session, group.id),
        is_default=book_groups.is_default(group),
    )
    return _render(request, "admin/book_group_form.html", context)


@router.post("/groups/{group_id}/edit", response_class=HTMLResponse)
def book_group_edit_submit(
    request: Request,
    group_id: int,
    title: str = Form(default=""),
    slug: str = Form(default=""),
    description: str = Form(default=""),
    icon: str = Form(default=""),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    group = book_groups.get_group(session, group_id)
    try:
        book_groups.update(
            session,
            group,
            title=title,
            slug_raw=slug,
            description=description,
            icon=icon,
            actor=user,
            ip=client_ip(request),
        )
        session.commit()
    except AppError as exc:
        session.rollback()
        return _groups_redirect(request, exc.message)
    return _groups_redirect(request)


@router.post("/groups/{group_id}/delete")
def book_group_delete(
    request: Request,
    group_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    group = book_groups.get_group(session, group_id)
    try:
        book_groups.delete(session, group, actor=user, ip=client_ip(request))
        session.commit()
    except AppError as exc:
        session.rollback()
        return _groups_redirect(request, exc.message)
    return _groups_redirect(request)


@router.post("/groups/{group_id}/move")
def book_group_move(
    request: Request,
    group_id: int,
    direction: int = Form(default=1),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    group = book_groups.get_group(session, group_id)
    book_groups.move(
        session, group, 1 if direction >= 0 else -1, actor=user, ip=client_ip(request)
    )
    session.commit()
    return _groups_redirect(request)


# ---------------------------------------------------------------- 章节 / 节


@router.get("/books/{book_id}/chapters/new", response_class=HTMLResponse)
def chapter_new_form(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    context = _ctx(
        request,
        session,
        user,
        f"新增章 - {book.title}",
        book=book,
        chapter=None,
        form={"title": "", "slug": "", "status": "draft", "content": "", "encoding": ""},
        error="",
        statuses=STATUSES,
        default_format=book.format,
        max_upload_bytes=get_settings(request).max_upload_bytes,
    )
    return _render(request, "admin/chapter_form.html", context)


@router.post("/books/{book_id}/chapters/new", response_class=HTMLResponse)
async def chapter_new_submit(
    request: Request,
    book_id: int,
    title: str = Form(default=""),
    slug: str = Form(default=""),
    status: str = Form(default="draft"),
    content: str = Form(default=""),
    encoding: str = Form(default=""),
    csrf_token: str = Form(default=""),
    upload: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """建章 + 首批节：一次选多个 .md/.html 文件，一个文件生成一节。"""
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    settings = get_settings(request)
    form = {"title": title, "slug": slug, "status": status, "content": content, "encoding": encoding}
    try:
        files = await _read_uploads(
            upload, encoding, settings.max_upload_bytes, expected_format=book.format, max_files=settings.max_upload_files
        )
        if not files and content.strip():
            files = [{"title": title.strip() or "正文", "raw": content, "format": book.format}]
        if not files:
            raise ValidationFailed("请粘贴正文内容或选择要上传的文件")
        chapter = chapters_service.create_chapter(
            session,
            book,
            title=title or str(files[0]["title"]),
            slug_raw=slug,
            status=status,
            actor=user,
            ip=client_ip(request),
            files=files,
            max_chars=settings.max_content_chars,
        )
        session.commit()
    except (AppError, ValidationFailed, EncodingError, UnsupportedFormat, EmptyContent, ValueError) as exc:
        session.rollback()
        message = exc.message if isinstance(exc, AppError) else str(exc)
        code = exc.status_code if isinstance(exc, AppError) else 400
        context = _ctx(
            request,
            session,
            user,
            f"新增章 - {book.title}",
            book=book,
            chapter=None,
            form=form,
            error=message,
            statuses=STATUSES,
            default_format=book.format,
            max_upload_bytes=settings.max_upload_bytes,
        )
        return _render(request, "admin/chapter_form.html", context, status_code=code)
    return RedirectResponse(
        f"{settings.root_path}/admin/books/{book.id}/chapters/{chapter.id}?notice=chapter-created",
        status_code=303,
    )


_UPLOAD_HINTS = {
    "markdown": ("Markdown", ".md / .markdown / .txt"),
    "html": ("HTML", ".html / .htm"),
}


async def _read_uploads(
    uploads: list[UploadFile] | None,
    encoding: str,
    max_bytes: int,
    expected_format: str | None = None,
    max_files: int = 50,
) -> list[dict[str, object]]:
    """把上传的文件读成节的初稿列表（标题取文件名、格式按扩展名）。

    整本 Book 只有一种格式：`expected_format` 给了就拒绝扩展名不匹配的文件，
    免得把 .html 传进 Markdown 书本、到渲染阶段才发现。
    """
    files: list[dict[str, object]] = []
    candidates = [item for item in (uploads or []) if item is not None and item.filename]
    if len(candidates) > max_files:
        raise ValidationFailed(f"一次最多上传 {max_files} 个文件")
    for upload in candidates:
        # 分块读：超大文件在读的过程中就 413，不会先占满内存
        data = await read_limited(upload, max_bytes)
        detected = detect_format(upload.filename)
        if expected_format in _UPLOAD_HINTS and detected != expected_format:
            label, suffixes = _UPLOAD_HINTS[expected_format]
            raise ValidationFailed(
                f"这本 Book 是 {label} 类型，只能上传 {suffixes} 文件（收到 {upload.filename}）"
            )
        text = decode_with_hint(data, encoding or None)
        files.append(
            {
                "title": title_from_filename(upload.filename),
                "format": detected,
                "raw": text,
            }
        )
    return files


@router.get("/books/{book_id}/chapters/{chapter_id}", response_class=HTMLResponse)
def chapter_edit_form(
    request: Request,
    book_id: int,
    chapter_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """章编辑器：章信息（标题/slug/序号/状态）+ 它下面的节列表。"""
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    context = _ctx(
        request,
        session,
        user,
        f"编辑章 - {chapter.title}",
        book=book,
        chapter=chapter,
        form={
            "title": chapter.title,
            "slug": chapter.slug,
            "status": chapter.status,
        },
        error="",
        notice=request.query_params.get("notice", ""),
        statuses=STATUSES,
        sections=sections_service.ordered_sections(session, chapter.id),
        max_upload_bytes=get_settings(request).max_upload_bytes,
    )
    return _render(request, "admin/chapter_form.html", context)


@router.post("/books/{book_id}/chapters/{chapter_id}/info", response_class=HTMLResponse)
def chapter_update_submit(
    request: Request,
    book_id: int,
    chapter_id: int,
    title: str = Form(default=""),
    slug: str = Form(default=""),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """保存章级字段；正文请到节编辑页。"""
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    settings = get_settings(request)
    form = {"title": title, "slug": slug, "status": chapter.status}
    try:
        chapters_service.update_chapter(
            session, chapter, title=title, slug_raw=slug, actor=user, ip=client_ip(request)
        )
        session.commit()
    except (AppError, ValueError) as exc:
        session.rollback()
        message = exc.message if isinstance(exc, AppError) else str(exc)
        code = exc.status_code if isinstance(exc, AppError) else 400
        context = _ctx(
            request,
            session,
            user,
            f"编辑章 - {chapter.title}",
            book=book,
            chapter=chapter,
            form=form,
            error=message,
            statuses=STATUSES,
            sections=sections_service.ordered_sections(session, chapter.id),
            max_upload_bytes=settings.max_upload_bytes,
        )
        return _render(request, "admin/chapter_form.html", context, status_code=code)
    return RedirectResponse(
        f"{settings.root_path}/admin/books/{book.id}/chapters/{chapter.id}?notice=chapter-info-saved",
        status_code=303,
    )


# ---------------------------------------------------------------- 节


@router.get("/books/{book_id}/chapters/{chapter_id}/preview", response_class=HTMLResponse)
def chapter_preview(
    request: Request,
    book_id: int,
    chapter_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """管理员按访客视角预览（草稿也能看），不改变章状态。"""
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    sections = sections_service.ordered_sections(session, chapter.id)
    base = {
        "request": request,
        "page_title": f"预览 - {chapter.title}",
        "book": book,
        "chapter": chapter,
        "preview": True,
    }
    if len(sections) > 1:
        context = _ctx(
            request,
            session,
            user,
            f"预览 - {chapter.title}",
            book=book,
            chapter=chapter,
            preview=True,
            numbered=[(section, str(index)) for index, section in enumerate(sections, start=1)],
            share_url=absolute_url(request, f"/b/{book.slug}/{chapter.slug}"),
        )
        return _render(request, "chapter_index.html", context)
    section = sections[0] if sections else None
    context = _ctx(
        request,
        session,
        user,
        f"预览 - {chapter.title}",
        book=book,
        chapter=chapter,
        section=section,
        preview=True,
        section_position=1,
        section_total=len(sections),
        toc=sections_service.parse_toc(section) if section is not None else [],
        prev_section=None,
        next_section=None,
        share_url=absolute_url(request, f"/b/{book.slug}/{chapter.slug}"),
    )
    context.update(base)
    return _render(request, "chapter.html", context)


@router.get("/books/{book_id}/chapters/{chapter_id}/sections/new", response_class=HTMLResponse)
def section_new_form(
    request: Request,
    book_id: int,
    chapter_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    context = _ctx(
        request,
        session,
        user,
        f"新增节 - {chapter.title}",
        book=book,
        chapter=chapter,
        section=None,
        form={"title": "", "slug": "", "format": book.format, "content": "", "encoding": ""},
        error="",
        formats=FORMATS,
        max_upload_bytes=get_settings(request).max_upload_bytes,
    )
    return _render(request, "admin/section_form.html", context)


@router.post("/books/{book_id}/chapters/{chapter_id}/sections/new", response_class=HTMLResponse)
async def section_new_submit(
    request: Request,
    book_id: int,
    chapter_id: int,
    title: str = Form(default=""),
    slug: str = Form(default=""),
    fmt: str = Form(default="", alias="format"),
    content: str = Form(default=""),
    encoding: str = Form(default=""),
    note: str = Form(default=""),
    csrf_token: str = Form(default=""),
    upload: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """追加节：可以选多个文件，一个文件生成一节。"""
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    settings = get_settings(request)
    form = {"title": title, "slug": slug, "format": fmt, "content": content, "encoding": encoding}
    try:
        files = await _read_uploads(
            upload, encoding, settings.max_upload_bytes, expected_format=book.format, max_files=settings.max_upload_files
        )
        if not files and content.strip():
            files = [
                {"title": title.strip() or "正文", "raw": content, "format": fmt or book.format}
            ]
        if not files:
            raise ValidationFailed("请粘贴正文内容或选择要上传的文件")
        first = None
        for item in files:
            first = sections_service.create_section(
                session,
                chapter,
                title=str(item["title"]),
                raw=str(item["raw"]),
                fmt=str(item["format"]) if item.get("format") else None,
                slug_raw=slug if len(files) == 1 else "",
                actor=user,
                ip=client_ip(request),
                note=note.strip() or "新增节",
                max_chars=settings.max_content_chars,
            )
            slug = ""
        session.commit()
    except (AppError, ValidationFailed, EncodingError, UnsupportedFormat, EmptyContent, ValueError) as exc:
        session.rollback()
        message = exc.message if isinstance(exc, AppError) else str(exc)
        code = exc.status_code if isinstance(exc, AppError) else 400
        context = _ctx(
            request,
            session,
            user,
            f"新增节 - {chapter.title}",
            book=book,
            chapter=chapter,
            section=None,
            form=form,
            error=message,
            formats=FORMATS,
            max_upload_bytes=settings.max_upload_bytes,
        )
        return _render(request, "admin/section_form.html", context, status_code=code)
    if len(files) > 1 or first is None:
        return RedirectResponse(
            f"{settings.root_path}/admin/books/{book.id}/chapters/{chapter.id}?notice=sections-created",
            status_code=303,
        )
    return RedirectResponse(
        f"{settings.root_path}/admin/books/{book.id}/chapters/{chapter.id}/sections/{first.id}?notice=section-created",
        status_code=303,
    )


@router.get(
    "/books/{book_id}/chapters/{chapter_id}/sections/{section_id}",
    response_class=HTMLResponse,
)
def section_edit_form(
    request: Request,
    book_id: int,
    chapter_id: int,
    section_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    section = _section_or_404(session, chapter, section_id)
    context = _ctx(
        request,
        session,
        user,
        f"编辑节 - {section.title}",
        book=book,
        chapter=chapter,
        section=section,
        form={
            "title": section.title,
            "slug": section.slug,
            "format": section.format,
            "content": section.content_raw,
            "encoding": "",
        },
        error="",
        notice=request.query_params.get("notice", ""),
        formats=FORMATS,
        max_upload_bytes=get_settings(request).max_upload_bytes,
    )
    return _render(request, "admin/section_form.html", context)


@router.post(
    "/books/{book_id}/chapters/{chapter_id}/sections/{section_id}/replace",
    response_class=HTMLResponse,
)
async def section_replace_submit(
    request: Request,
    book_id: int,
    chapter_id: int,
    section_id: int,
    title: str = Form(default=""),
    slug: str = Form(default=""),
    fmt: str = Form(default="", alias="format"),
    content: str = Form(default=""),
    encoding: str = Form(default=""),
    base_version: str = Form(default=""),
    note: str = Form(default=""),
    csrf_token: str = Form(default=""),
    upload: UploadFile | None = File(default=None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    section = _section_or_404(session, chapter, section_id)
    settings = get_settings(request)
    form = {
        "title": title,
        "slug": slug,
        "format": fmt,
        "content": content,
        "encoding": encoding,
    }
    try:
        files = await _read_uploads(
            [upload] if upload is not None else [],
            encoding,
            settings.max_upload_bytes,
            expected_format=book.format,
            max_files=settings.max_upload_files,
        )
        if files:
            new_raw = str(files[0]["raw"])
            new_fmt = str(files[0]["format"])
            new_title = title or str(files[0]["title"])
        else:
            new_raw = content if content.strip() else section.content_raw
            new_fmt = fmt or section.format
            new_title = title or section.title
        before_version = section.current_version_no
        sections_service.replace_content(
            session,
            section,
            title=new_title,
            raw=new_raw,
            fmt=new_fmt,
            slug_raw=slug,
            base_version=int(base_version) if base_version.strip() else None,
            actor=user,
            ip=client_ip(request),
            note=note.strip() or "替换内容",
            max_chars=settings.max_content_chars,
            retention=settings.version_retention,
        )
        # 服务层在内容无改动时不递增版本，据此区分「已保存」与「没变化」
        notice = "section-saved" if section.current_version_no != before_version else "section-unchanged"
        session.commit()
    except (AppError, EncodingError, UnsupportedFormat, EmptyContent, ValueError) as exc:
        session.rollback()
        message = exc.message if isinstance(exc, AppError) else str(exc)
        code = exc.status_code if isinstance(exc, AppError) else 400
        context = _ctx(
            request,
            session,
            user,
            f"编辑节 - {section.title}",
            book=book,
            chapter=chapter,
            section=section,
            form=form,
            error=message,
            formats=FORMATS,
            max_upload_bytes=settings.max_upload_bytes,
        )
        return _render(request, "admin/section_form.html", context, status_code=code)
    return RedirectResponse(
        f"{settings.root_path}/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}?notice={notice}",
        status_code=303,
    )


@router.post("/books/{book_id}/chapters/{chapter_id}/sections/{section_id}/move")
def section_move(
    request: Request,
    book_id: int,
    chapter_id: int,
    section_id: int,
    direction: int = Form(default=1),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    section = _section_or_404(session, chapter, section_id)
    sections_service.move_section(
        session, section, 1 if direction >= 0 else -1, actor=user, ip=client_ip(request)
    )
    session.commit()
    return RedirectResponse(
        f"{get_settings(request).root_path}/admin/books/{book.id}/chapters/{chapter.id}",
        status_code=303,
    )


@router.post("/books/{book_id}/chapters/{chapter_id}/sections/{section_id}/delete")
def section_delete(
    request: Request,
    book_id: int,
    chapter_id: int,
    section_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    section = _section_or_404(session, chapter, section_id)
    sections_service.delete_section(session, section, actor=user, ip=client_ip(request))
    session.commit()
    return RedirectResponse(
        f"{get_settings(request).root_path}/admin/books/{book.id}/chapters/{chapter.id}?notice=section-deleted",
        status_code=303,
    )


@router.post("/books/{book_id}/chapters/{chapter_id}/sections/{section_id}/restore")
def section_restore(
    request: Request,
    book_id: int,
    chapter_id: int,
    section_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    section = _section_or_404(session, chapter, section_id)
    sections_service.restore_section(session, section, actor=user, ip=client_ip(request))
    session.commit()
    return RedirectResponse(
        f"{get_settings(request).root_path}/admin/books/{book.id}/chapters/{chapter.id}",
        status_code=303,
    )


@router.post("/books/{book_id}/chapters/{chapter_id}/status")
def chapter_status(
    request: Request,
    book_id: int,
    chapter_id: int,
    status: str = Form(default="draft"),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    chapters_service.set_status(session, chapter, status, actor=user, ip=client_ip(request))
    session.commit()
    return RedirectResponse(f"{get_settings(request).root_path}/admin/books/{book.id}", status_code=303)


@router.post("/books/{book_id}/chapters/{chapter_id}/move")
def chapter_move(
    request: Request,
    book_id: int,
    chapter_id: int,
    direction: int = Form(default=1),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    chapters_service.move_chapter(session, chapter, 1 if direction >= 0 else -1, actor=user, ip=client_ip(request))
    session.commit()
    return RedirectResponse(f"{get_settings(request).root_path}/admin/books/{book.id}", status_code=303)


@router.post("/books/{book_id}/chapters/{chapter_id}/delete")
def chapter_delete(
    request: Request,
    book_id: int,
    chapter_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    chapters_service.soft_delete_chapter(session, chapter, actor=user, ip=client_ip(request))
    session.commit()
    return RedirectResponse(f"{get_settings(request).root_path}/admin/books/{book.id}", status_code=303)


@router.post("/books/{book_id}/chapters/{chapter_id}/restore")
def chapter_restore(
    request: Request,
    book_id: int,
    chapter_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    chapters_service.restore_chapter(session, chapter, actor=user, ip=client_ip(request))
    session.commit()
    return RedirectResponse(f"{get_settings(request).root_path}/admin/books/{book.id}", status_code=303)


# ---------------------------------------------------------------- 版本（节级）


@router.get("/books/{book_id}/chapters/{chapter_id}/versions", response_class=HTMLResponse)
def chapter_versions(
    request: Request,
    book_id: int,
    chapter_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """章的「历史版本」= 该章各节的版本（每节各自 v1/v2，互不影响）。"""
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    section_rows = [
        {"section": section, "versions": sections_service.list_versions(session, section)}
        for section in sections_service.ordered_sections(session, chapter.id)
    ]
    context = _ctx(
        request,
        session,
        user,
        f"历史版本 - {chapter.title}",
        book=book,
        chapter=chapter,
        section=None,
        section_rows=section_rows,
        versions=[],
    )
    return _render(request, "admin/versions.html", context)


@router.get(
    "/books/{book_id}/chapters/{chapter_id}/sections/{section_id}/versions",
    response_class=HTMLResponse,
)
def section_versions(
    request: Request,
    book_id: int,
    chapter_id: int,
    section_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    section = _section_or_404(session, chapter, section_id)
    versions = sections_service.list_versions(session, section)
    context = _ctx(
        request,
        session,
        user,
        f"历史版本 - {section.title}",
        book=book,
        chapter=chapter,
        section=section,
        section_rows=[],
        versions=versions,
    )
    return _render(request, "admin/versions.html", context)


@router.get(
    "/books/{book_id}/chapters/{chapter_id}/sections/{section_id}/versions/{version_no}",
    response_class=HTMLResponse,
)
def section_version_detail(
    request: Request,
    book_id: int,
    chapter_id: int,
    section_id: int,
    version_no: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    section = _section_or_404(session, chapter, section_id)
    version = sections_service.get_version(session, section, version_no)
    context = _ctx(
        request,
        session,
        user,
        f"版本 {version_no} - {section.title}",
        book=book,
        chapter=chapter,
        section=section,
        version=version,
    )
    return _render(request, "admin/version_detail.html", context)


@router.get(
    "/books/{book_id}/chapters/{chapter_id}/sections/{section_id}/diff",
    response_class=HTMLResponse,
)
def section_diff(
    request: Request,
    book_id: int,
    chapter_id: int,
    section_id: int,
    a: int | None = Query(default=None),
    b: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    section = _section_or_404(session, chapter, section_id)
    # 不带参数时默认对比「最早版本 → 最新版本」，而不是 1 对 1（那样永远显示一致）
    versions = sections_service.list_versions(session, section)
    if not versions:
        raise NotFound("该节还没有历史版本")
    earliest = versions[-1].version_no
    latest = versions[0].version_no
    left = earliest if a is None else a
    right = latest if b is None else b
    diff = sections_service.diff_versions(session, section, left, right)
    context = _ctx(
        request,
        session,
        user,
        f"版本对比 - {section.title}",
        book=book,
        chapter=chapter,
        section=section,
        diff=diff,
    )
    return _render(request, "admin/diff.html", context)


@router.post(
    "/books/{book_id}/chapters/{chapter_id}/sections/{section_id}/rollback/{version_no}"
)
def section_rollback(
    request: Request,
    book_id: int,
    chapter_id: int,
    section_id: int,
    version_no: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    chapter = _chapter_or_404(session, book, chapter_id)
    section = _section_or_404(session, chapter, section_id)
    settings = get_settings(request)
    sections_service.rollback(
        session,
        section,
        version_no,
        actor=user,
        ip=client_ip(request),
        retention=settings.version_retention,
        max_chars=settings.max_content_chars,
    )
    session.commit()
    return RedirectResponse(
        f"{settings.root_path}/admin/books/{book.id}/chapters/{chapter.id}/sections/{section.id}",
        status_code=303,
    )


# ---------------------------------------------------------------- 回收站 / 账号 / 设置 / 审计


@router.get("/trash", response_class=HTMLResponse)
def trash(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    deleted_books = list(
        session.execute(
            select(Book).where(Book.deleted_at.is_not(None)).order_by(Book.deleted_at.desc())
        )
        .scalars()
        .all()
    )
    deleted_chapters = list(
        session.execute(
            select(Chapter, Book)
            .join(Book, Book.id == Chapter.book_id)
            .where(Chapter.deleted_at.is_not(None))
            .order_by(Chapter.deleted_at.desc())
        ).all()
    )
    context = _ctx(
        request,
        session,
        user,
        "回收站",
        deleted_books=deleted_books,
        deleted_chapters=deleted_chapters,
    )
    return _render(request, "admin/trash.html", context)


@router.get("/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session, admin_only=True)
    rows = list(session.execute(select(User).order_by(User.created_at.asc())).scalars().all())
    context = _ctx(request, session, user, "账号管理", users=rows, error="")
    return _render(request, "admin/users.html", context)


@router.post("/users/new", response_class=HTMLResponse)
def users_create(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
    display_name: str = Form(default=""),
    role: str = Form(default="admin"),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session, admin_only=True)
    require_csrf(request, csrf_token)
    try:
        create_user(session, username=username, password=password, display_name=display_name, role=role)
        audit_service.record(
            session,
            actor=user,
            action="user.create",
            target_type="user",
            target_label=username,
            detail={"role": role},
            ip=client_ip(request),
        )
        session.commit()
        return RedirectResponse(f"{get_settings(request).root_path}/admin/users", status_code=303)
    except AppError as exc:
        session.rollback()
        rows = list(session.execute(select(User).order_by(User.created_at.asc())).scalars().all())
        context = _ctx(request, session, user, "账号管理", users=rows, error=exc.message)
        return _render(request, "admin/users.html", context, status_code=400)


@router.post("/users/{user_id}/toggle")
def users_toggle(
    request: Request,
    user_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    actor = require_user(request, session, admin_only=True)
    require_csrf(request, csrf_token)
    target = session.get(User, user_id)
    if target is None:
        raise NotFound("账号不存在")
    if target.id == actor.id:
        raise ValidationFailed("不能停用自己")
    set_active(target, not target.is_active)
    audit_service.record(
        session,
        actor=actor,
        action="user.toggle",
        target_type="user",
        target_id=target.id,
        target_label=target.username,
        detail={"is_active": target.is_active},
        ip=client_ip(request),
    )
    session.commit()
    return RedirectResponse(f"{get_settings(request).root_path}/admin/users", status_code=303)


@router.post("/users/{user_id}/password", response_class=HTMLResponse)
def users_reset_password(
    request: Request,
    user_id: int,
    password: str = Form(default=""),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    actor = require_user(request, session, admin_only=True)
    require_csrf(request, csrf_token)
    target = session.get(User, user_id)
    if target is None:
        raise NotFound("账号不存在")
    try:
        set_password(target, password)
        audit_service.record(
            session,
            actor=actor,
            action="user.password_reset",
            target_type="user",
            target_id=target.id,
            target_label=target.username,
            ip=client_ip(request),
        )
        session.commit()
    except AppError as exc:
        session.rollback()
        rows = list(session.execute(select(User).order_by(User.created_at.asc())).scalars().all())
        context = _ctx(request, session, actor, "账号管理", users=rows, error=exc.message)
        return _render(request, "admin/users.html", context, status_code=400)
    return RedirectResponse(f"{get_settings(request).root_path}/admin/users", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session, admin_only=True)
    values = load_settings(session, get_settings(request))
    context = _ctx(request, session, user, "站点设置", values=values, error="", saved=False)
    return _render(request, "admin/settings.html", context)


@router.post("/settings", response_class=HTMLResponse)
def settings_save(
    request: Request,
    site_name: str = Form(default=""),
    site_footer: str = Form(default=""),
    home_intro: str = Form(default=""),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session, admin_only=True)
    require_csrf(request, csrf_token)
    if not site_name.strip():
        values = load_settings(session, get_settings(request))
        context = _ctx(request, session, user, "站点设置", values=values, error="站点名不能为空", saved=False)
        return _render(request, "admin/settings.html", context, status_code=400)
    saved = save_settings(
        session, {"site_name": site_name, "site_footer": site_footer, "home_intro": home_intro}
    )
    audit_service.record(
        session,
        actor=user,
        action="settings.update",
        target_type="settings",
        target_label="site",
        detail=saved,
        ip=client_ip(request),
    )
    session.commit()
    values = load_settings(session, get_settings(request))
    context = _ctx(request, session, user, "站点设置", values=values, error="", saved=True)
    return _render(request, "admin/settings.html", context)


@router.get("/audit", response_class=HTMLResponse)
def audit_page(
    request: Request,
    book_id: str = Query(default=""),
    chapter_id: str = Query(default=""),
    actor: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session, admin_only=True)
    conditions = []
    if book_id.strip().isdigit():
        conditions.append(AuditLog.book_id == int(book_id))
    if chapter_id.strip().isdigit():
        conditions.append(
            (AuditLog.target_type == "chapter") & (AuditLog.target_id == int(chapter_id))
        )
    if actor.strip():
        conditions.append(AuditLog.actor_name.ilike(f"%{actor.strip()}%"))
    total = session.execute(select(func.count()).select_from(AuditLog).where(*conditions)).scalar_one()
    rows = list(
        session.execute(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(AUDIT_PAGE_SIZE)
            .offset((page - 1) * AUDIT_PAGE_SIZE)
        )
        .scalars()
        .all()
    )
    entries = [{"log": row, "detail": audit_service.detail_of(row)} for row in rows]
    context = _ctx(
        request,
        session,
        user,
        "审计日志",
        entries=entries,
        pager=paginate(total, page, AUDIT_PAGE_SIZE),
        filters={"book_id": book_id, "chapter_id": chapter_id, "actor": actor},
    )
    return _render(request, "admin/audit.html", context)


@router.get("/audit.csv")
def audit_export(
    request: Request,
    book_id: str = Query(default=""),
    actor: str = Query(default=""),
    session: Session = Depends(get_session),
) -> Response:
    """网页端审计导出：复用查询层的过滤语义，UTF-8 BOM 便于 Excel 打开。"""
    require_user(request, session, admin_only=True)
    rows = audit_service.query_rows(
        session,
        book_id=int(book_id) if book_id.strip().isdigit() else None,
        actor=actor,
        limit=10000,
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Response(
        content=audit_service.export_csv(rows).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bookhub-audit-{stamp}.csv"'},
    )


# ---------------------------------------------------------------- 媒体库


def human_bytes(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def _media_view(request: Request, session: Session, book: Book) -> dict[str, object]:
    settings = get_settings(request)
    referenced = media_service.referenced_names(session, book.id)
    assets = media_service.list_media(session, book.id, include_deleted=True)
    items = [
        {
            "asset": asset,
            "url": media_service.media_url(book.slug, asset.stored_name, settings.root_path),
            "referenced": asset.stored_name in referenced,
            "size_label": human_bytes(asset.byte_size),
        }
        for asset in assets
    ]
    return {
        "book": book,
        "items": items,
        "cover_id": book.cover_media_id,
        "usage": media_service.usage(session, book.id, settings),
        "usage_label": human_bytes(media_service.usage(session, book.id, settings)["used"]),
        "quota_label": human_bytes(settings.media_quota_bytes),
        "stale": media_service.stale_references(session, book),
        "preview": media_service.cleanup_plan(session, book, settings),
        "max_bytes": settings.media_max_bytes,
        "max_label": human_bytes(settings.media_max_bytes),
        "allowed_types": settings.media_allowed_types,
    }


@router.get("/books/{book_id}/media", response_class=HTMLResponse)
def media_page(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = require_user(request, session)
    book = _book_or_404(session, book_id)
    context = _ctx(
        request,
        session,
        user,
        f"媒体库 - {book.title}",
        error=request.query_params.get("error", ""),
        **_media_view(request, session, book),
    )
    return _render(request, "admin/media.html", context)


@router.post("/books/{book_id}/media")
async def media_upload_submit(
    request: Request,
    book_id: int,
    csrf_token: str = Form(default=""),
    upload: UploadFile | None = File(default=None),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """编辑器内联上传：返回 JSON，失败也返回 JSON 以便前端就地提示。"""
    request_id = getattr(request.state, "request_id", "-")
    settings = get_settings(request)
    try:
        user = require_user(request, session)
        require_csrf(request, csrf_token)
        book = _book_or_404(session, book_id)
        if upload is None or not upload.filename:
            raise ValidationFailed("请选择要上传的文件")
        data = await read_limited(upload, settings.media_max_bytes)
        asset = media_service.save_media(
            session,
            book=book,
            filename=upload.filename,
            data=data,
            settings=get_settings(request),
            actor=user,
            ip=client_ip(request),
        )
        session.commit()
    except AppError as exc:
        session.rollback()
        return JSONResponse(
            error_body(exc.code, exc.message, request_id), status_code=exc.status_code
        )
    settings = get_settings(request)
    return JSONResponse(
        {
            "id": asset.id,
            "url": media_service.media_url(book.slug, asset.stored_name, settings.root_path),
            "filename": asset.filename,
            "byte_size": asset.byte_size,
            "kind": asset.kind,
            "mime": asset.mime,
        },
        status_code=201,
    )


@router.post("/books/{book_id}/media/{media_id}/delete")
def media_delete_submit(
    request: Request,
    book_id: int,
    media_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    asset = media_service.find_media_by_id(session, book, media_id)
    media_service.delete_media(session, book=book, asset=asset, actor=user, ip=client_ip(request))
    session.commit()
    return RedirectResponse(f"{get_settings(request).root_path}/admin/books/{book.id}/media", status_code=303)


@router.post("/books/{book_id}/media/cleanup")
def media_cleanup_submit(
    request: Request,
    book_id: int,
    confirm: int = Form(default=0),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    media_service.cleanup(
        session,
        book=book,
        settings=get_settings(request),
        actor=user,
        confirm=bool(confirm),
        ip=client_ip(request),
    )
    session.commit()
    return RedirectResponse(f"{get_settings(request).root_path}/admin/books/{book.id}/media", status_code=303)


# ---------------------------------------------------------------- 排序与批量

@router.post("/books/{book_id}/cover")
def book_cover_set(
    request: Request,
    book_id: int,
    media_id: str = Form(default=""),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """设置 / 清除封面：media_id 为空表示清除。"""
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    settings = get_settings(request)
    target = f"{settings.root_path}/admin/books/{book.id}/media"
    try:
        books_service.set_cover(
            session,
            book,
            int(media_id) if media_id.strip().isdigit() else None,
            actor=user,
            ip=client_ip(request),
        )
        session.commit()
    except AppError as exc:
        session.rollback()
        return RedirectResponse(f"{target}?error={quote(exc.message)}", status_code=303)
    return RedirectResponse(target, status_code=303)

@router.post("/books/{book_id}/chapters/reorder")
async def chapters_reorder(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session),
) -> JSONResponse:
    """拖拽排序：按整本 Book 提交完整有序 id 列表，集合不一致直接拒绝。"""
    request_id = getattr(request.state, "request_id", "-")
    try:
        user = require_user(request, session)
        require_csrf(request, request.headers.get("x-csrf-token", ""))
        book = _book_or_404(session, book_id)
        body = await request.json()
        raw_ids = body.get("chapter_ids") if isinstance(body, dict) else None
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValidationFailed("chapter_ids 不能为空")
        ids = [int(item) for item in raw_ids]
        ordered = chapters_service.reorder_chapters(
            session,
            book.id,
            ids,
            actor=user,
            ip=client_ip(request),
        )
        session.commit()
    except AppError as exc:
        session.rollback()
        return JSONResponse(error_body(exc.code, exc.message, request_id), status_code=exc.status_code)
    except (TypeError, ValueError):
        session.rollback()
        return JSONResponse(
            error_body("validation_error", "chapter_ids 必须是整数列表", request_id), status_code=400
        )
    return JSONResponse({"ok": True, "order": [item.id for item in ordered]})


@router.post("/books/{book_id}/chapters/batch")
def chapters_batch(
    request: Request,
    book_id: int,
    action: str = Form(default=""),
    confirm: int = Form(default=0),
    csrf_token: str = Form(default=""),
    chapter_id: list[int] = Form(default=[]),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """批量发布 / 撤回 / 删除：逐条执行，结果用查询参数回显。"""
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    settings = get_settings(request)
    target = f"{settings.root_path}/admin/books/{book.id}"

    if action not in {"publish", "unpublish", "delete"}:
        return RedirectResponse(f"{target}?error={quote('未知的批量操作')}", status_code=303)
    if not chapter_id:
        return RedirectResponse(f"{target}?error={quote('请先勾选要操作的章')}", status_code=303)
    if action == "delete" and not confirm:
        return RedirectResponse(f"{target}?error={quote('批量删除需要显式确认')}", status_code=303)

    ok = 0
    failed = 0
    for cid in chapter_id:
        try:
            chapter = _chapter_or_404(session, book, cid)
            if action == "delete":
                chapters_service.soft_delete_chapter(
                    session, chapter, actor=user, ip=client_ip(request)
                )
            else:
                chapters_service.set_status(
                    session,
                    chapter,
                    STATUS_PUBLISHED if action == "publish" else STATUS_DRAFT,
                    actor=user,
                    ip=client_ip(request),
                )
            session.commit()
            ok += 1
        except (AppError, ValueError):
            session.rollback()
            failed += 1
    return RedirectResponse(f"{target}?batch={action}:{ok},{failed}", status_code=303)


@router.post("/books/{book_id}/pin")
def book_pin_toggle(
    request: Request,
    book_id: int,
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = require_user(request, session)
    require_csrf(request, csrf_token)
    book = _book_or_404(session, book_id)
    books_service.update_book(
        session,
        book,
        pinned=not book.pinned,
        actor=user,
        ip=client_ip(request),
    )
    session.commit()
    return RedirectResponse(f"{get_settings(request).root_path}/admin/books/{book.id}", status_code=303)
