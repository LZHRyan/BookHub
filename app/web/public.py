"""访客侧路由：首页、Book 目录、章/节阅读、搜索。"""

from __future__ import annotations

from xml.etree import ElementTree

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import NotFound, ValidationFailed
from app.models import (
    FORMAT_HTML,
    STATUS_PUBLISHED,
    ApiToken,
    AuditLog,
    Book,
    Chapter,
    ChapterSection,
    MediaAsset,
)
from app.services import book_groups, visits
from app.services import books as books_service
from app.services import chapters as chapters_service
from app.services import media as media_service
from app.services import sections as sections_service
from app.services.search import MAX_QUERY_LENGTH
from app.services.search import search as run_search
from app.web.common import (
    DEFAULT_PAGE_SIZE,
    absolute_url,
    base_context,
    current_user,
    get_settings,
    paginate,
)

router = APIRouter(include_in_schema=False)
PAGE_SIZE = 12

# 原始文档通道：把上传的 HTML 原样交给浏览器，因此必须用 CSP `sandbox` 把它降级成
# 唯一源（不给 allow-same-origin）——文档自己的脚本可以跑，但读不到本站 Cookie、
# localStorage，也拿不到同源接口的响应。资源加载放开到任意来源，方便文档引用 CDN。
RAW_DOCUMENT_CSP = (
    "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals; "
    "default-src 'none'; "
    "style-src * 'unsafe-inline' data:; "
    "script-src * 'unsafe-inline' data: blob:; "
    "img-src * data: blob:; "
    "font-src * data:; "
    "media-src * data: blob:; "
    "connect-src *; "
    "frame-src *; "
    "form-action 'none'"
)


def _article_title(*parts: str) -> str:
    """把「节 - 章 - Book」拼成标题，相邻同名（常见于单节章）只留一个。"""
    kept: list[str] = []
    for part in parts:
        if part and (not kept or kept[-1] != part):
            kept.append(part)
    return " - ".join(kept)


def cover_urls(request: Request, session: Session, books: list[Book]) -> dict[int, str]:
    """Book → 封面地址。只返回属于该 Book 且未删除的图片。"""
    settings = get_settings(request)
    wanted = {book.cover_media_id: book for book in books if book.cover_media_id}
    if not wanted:
        return {}
    assets = session.execute(
        select(MediaAsset).where(MediaAsset.id.in_(list(wanted)))
    ).scalars()
    urls: dict[int, str] = {}
    for asset in assets:
        book = wanted.get(asset.id)
        if asset.deleted_at is not None or book is None or asset.book_id != book.id:
            continue
        urls[book.id] = media_service.media_url(book.slug, asset.stored_name, settings.root_path)
    return urls


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    group: str = Query(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """首页按「组」分区；带 ?group=<slug> 时只显示该组的完整列表。"""
    group_ref = group.strip() or None
    sections = book_groups.overview(
        session,
        visibility="public",
        group_ref=group_ref,
        limit_per_group=0 if group_ref else 24,
    )
    # 筛选态不截断：进来就是要看这一组的全部内容
    all_books = [book for section in sections for book in section["books"]]
    counts = books_service.chapter_counts(session, [book.id for book in all_books])
    covers = cover_urls(request, session, all_books)
    view = [
        {
            "group": section["group"],
            "total": section["total"],
            "truncated": section["truncated"],
            "cards": [
                {
                    "book": book,
                    "chapter_count": counts.get(book.id, 0),
                    "cover": covers.get(book.id),
                }
                for book in section["books"]
            ],
        }
        for section in sections
    ]
    context = base_context(
        request,
        session,
        user=current_user(request, session),
        page_title="",
        sections=view,
        total_books=sum(section["total"] for section in sections),
        active_group=group_ref or "",
        groups=book_groups.list_groups(session),
        query="",
    )
    return request.app.state.templates.TemplateResponse(request, "index.html", context)


@router.get("/b/{book_slug}", response_class=HTMLResponse)
def book_detail(
    request: Request,
    book_slug: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """目录：章 → 节两级。Book 页本身不计热度，读到某一节才算。"""
    book = books_service.get_book(session, book_slug)
    book_group = book_groups.get_group(session, book.group_id)
    directory = chapters_service.tree(session, book.id, published_only=True)
    flat = chapters_service.flat_published_sections(session, book.id)
    book_cover = cover_urls(request, session, [book]).get(book.id)
    context = base_context(
        request,
        session,
        user=current_user(request, session),
        page_title=book.title,
        book=book,
        book_group=book_group,
        directory=directory,
        cover=book_cover,
        og_image=absolute_url(request, book_cover) if book_cover else None,
        share_url=absolute_url(request, f"/b/{book.slug}"),
        chapter_total=len(directory),
        section_total=len(flat),
        total_words=sum(section.word_count for _chapter, section in flat),
    )
    return request.app.state.templates.TemplateResponse(request, "book.html", context)


@router.get("/b/{book_slug}/{chapter_slug}", response_class=HTMLResponse)
def chapter_detail(
    request: Request,
    book_slug: str,
    chapter_slug: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """章页双形态：只有一节时直出正文（兼容存量链接），多节时作为节索引。"""
    book, chapter = chapters_service.find_published_chapter(session, book_slug, chapter_slug)
    sections = sections_service.ordered_sections(session, chapter.id)
    user = current_user(request, session)
    if len(sections) == 1:
        # 单节章直出正文：规范地址仍是章地址，分享/og:url 不能指到重复的三段式地址
        return _render_section_page(
            request,
            session,
            user,
            book,
            chapter,
            sections[0],
            canonical_path=f"/b/{book.slug}/{chapter.slug}",
        )
    numbered = [
        (section, str(index)) for index, section in enumerate(sections, start=1)
    ]
    # 节号要带章号（2.1 / 2.2），和 Book 页目录保持一致
    for row in chapters_service.tree(session, book.id, published_only=True):
        if row["chapter"].id == chapter.id:
            numbered = row["sections"]
            break
    context = base_context(
        request,
        session,
        user=user,
        page_title=f"{chapter.title} - {book.title}",
        book=book,
        chapter=chapter,
        numbered=numbered,
        share_url=absolute_url(request, f"/b/{book.slug}/{chapter.slug}"),
    )
    return request.app.state.templates.TemplateResponse(request, "chapter_index.html", context)


@router.get("/b/{book_slug}/{chapter_slug}/{section_slug}", response_class=HTMLResponse)
def section_detail(
    request: Request,
    book_slug: str,
    chapter_slug: str,
    section_slug: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """节的唯一正文出口。"""
    book, chapter, section = sections_service.find_section(
        session, book_slug, chapter_slug, section_slug
    )
    return _render_section_page(
        request, session, current_user(request, session), book, chapter, section
    )


def _render_section_page(
    request: Request,
    session: Session,
    user,
    book: Book,
    chapter: Chapter,
    section: ChapterSection,
    canonical_path: str | None = None,
) -> HTMLResponse:
    siblings = sections_service.ordered_sections(session, chapter.id)
    ids = [item.id for item in siblings]
    position = ids.index(section.id) if section.id in ids else 0
    previous, following = chapters_service.neighbours(session, section)
    if user is None:
        # 读到某一节才算这本书的热度（Book 目录页不计）
        visits.record_section_view(request, session, book_id=book.id, section_id=section.id)
    context = base_context(
        request,
        session,
        user=user,
        page_title=_article_title(section.title, chapter.title, book.title),
        book=book,
        chapter=chapter,
        section=section,
        section_no=f"{chapter.title} {position + 1}/{len(siblings)}",
        section_position=position + 1,
        section_total=len(siblings),
        toc=sections_service.parse_toc(section),
        share_url=absolute_url(
            request,
            canonical_path or f"/b/{book.slug}/{chapter.slug}/{section.slug}",
        ),
        share_title=(
            section.title if section.title == chapter.title else f"{section.title} · {chapter.title}"
        ),
        prev_section=previous,
        next_section=following,
    )
    return request.app.state.templates.TemplateResponse(request, "chapter.html", context)


@router.get("/b/{book_slug}/{chapter_slug}/{section_slug}/raw", response_class=HTMLResponse)
def section_raw(
    request: Request,
    book_slug: str,
    chapter_slug: str,
    section_slug: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """原样输出上传的 HTML（保留其 CSS/JS/base64 图片与自带导航）。

    只能在新标签页里直接打开，不做任何净化；安全边界完全由 `RAW_DOCUMENT_CSP`
    的沙箱承担。Markdown 节没有独立 HTML 文档，直接 404。
    """
    user = current_user(request, session)
    book, _chapter, section = sections_service.find_section(
        session,
        book_slug,
        chapter_slug,
        section_slug,
        allow_unpublished=user is not None,
    )
    if section.format != FORMAT_HTML:
        raise NotFound("节不存在")
    if user is None:
        visits.record_section_view(request, session, book_id=book.id, section_id=section.id)
    return HTMLResponse(
        section.content_raw,
        headers={
            "Content-Security-Policy": RAW_DOCUMENT_CSP,
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
            "Cache-Control": "no-store",
        },
    )


def _absolute(request: Request, path: str) -> str:
    return absolute_url(request, path)


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request, session: Session = Depends(get_session)) -> Response:
    """公开内容的地图：首页 + public Book + 章页 + 节页；不含草稿与 unlisted。"""
    books, _total = books_service.list_books(session, visibility="public", page=1, page_size=500)
    root = ElementTree.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")

    def add(loc: str, lastmod) -> None:
        node = ElementTree.SubElement(root, "url")
        ElementTree.SubElement(node, "loc").text = loc
        if lastmod is not None:
            ElementTree.SubElement(node, "lastmod").text = lastmod.strftime("%Y-%m-%d")

    add(_absolute(request, "/"), None)
    for book in books:
        add(_absolute(request, f"/b/{book.slug}"), book.updated_at)
        for row in chapters_service.tree(session, book.id, published_only=True):
            chapter = row["chapter"]
            add(_absolute(request, f"/b/{book.slug}/{chapter.slug}"), chapter.updated_at)
            # 单节章的章地址就是正文的规范地址，再收一份三段式地址只会变成重复内容
            if len(row["sections"]) <= 1:
                continue
            for section, _no in row["sections"]:
                add(
                    _absolute(request, f"/b/{book.slug}/{chapter.slug}/{section.slug}"),
                    section.updated_at,
                )

    payload = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=payload, media_type="application/xml")


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request, session: Session = Depends(get_session)) -> Response:
    """Prometheus 文本格式的最小指标集。"""
    settings = get_settings(request)

    def scalar(stmt) -> int:
        return int(session.execute(stmt).scalar_one() or 0)

    books_total = scalar(
        select(func.count()).select_from(Book).where(Book.deleted_at.is_(None))
    )
    chapters_published = scalar(
        select(func.count())
        .select_from(Chapter)
        .where(Chapter.deleted_at.is_(None), Chapter.status == STATUS_PUBLISHED)
    )
    sections_published = scalar(
        select(func.count())
        .select_from(ChapterSection)
        .join(Chapter, Chapter.id == ChapterSection.chapter_id)
        .where(
            ChapterSection.deleted_at.is_(None),
            Chapter.deleted_at.is_(None),
            Chapter.status == STATUS_PUBLISHED,
        )
    )
    media_bytes = scalar(
        select(func.coalesce(func.sum(MediaAsset.byte_size), 0)).where(
            MediaAsset.deleted_at.is_(None)
        )
    )
    lines = [
        "# HELP bookhub_books_total 未删除的 Book 数量",
        "# TYPE bookhub_books_total gauge",
        f"bookhub_books_total {books_total}",
        "# HELP bookhub_chapters_published_total 已发布的章节数量",
        "# TYPE bookhub_chapters_published_total gauge",
        f"bookhub_chapters_published_total {chapters_published}",
        "# HELP bookhub_sections_published_total 已发布章下面的节数量",
        "# TYPE bookhub_sections_published_total gauge",
        f"bookhub_sections_published_total {sections_published}",
        "# HELP bookhub_media_bytes_total 媒体资源占用字节数",
        "# TYPE bookhub_media_bytes_total gauge",
        f"bookhub_media_bytes_total {media_bytes}",
    ]
    if settings.api_docs_enabled:
        audit_rows = scalar(select(func.count()).select_from(AuditLog))
        tokens_active = scalar(
            select(func.count()).select_from(ApiToken).where(ApiToken.revoked_at.is_(None))
        )
        lines += [
            "# HELP bookhub_audit_rows_total 审计记录条数",
            "# TYPE bookhub_audit_rows_total gauge",
            f"bookhub_audit_rows_total {audit_rows}",
            "# HELP bookhub_tokens_active 未吊销的 Token 数量",
            "# TYPE bookhub_tokens_active gauge",
            f"bookhub_tokens_active {tokens_active}",
        ]
    lines.append(f'bookhub_version_info{{version="{__import__("app").__version__}"}} 1')
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    book: str = Query(default=""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    query = (q or "").strip()
    if len(query) > MAX_QUERY_LENGTH:
        raise ValidationFailed(f"查询词不能超过 {MAX_QUERY_LENGTH} 个字符")
    book_id = None
    book_obj = None
    if book:
        try:
            book_obj = books_service.get_book(session, book)
            book_id = book_obj.id
        except NotFound:
            book_obj = None
            book_id = -1
    results, total = ([], 0)
    if query:
        results, total = run_search(
            session, query=query, book_id=book_id, page=page, page_size=DEFAULT_PAGE_SIZE
        )
    context = base_context(
        request,
        session,
        user=current_user(request, session),
        page_title=f"搜索：{query}" if query else "搜索",
        query=query,
        results=results,
        book=book_obj,
        pager=paginate(total, page, DEFAULT_PAGE_SIZE),
    )
    return request.app.state.templates.TemplateResponse(request, "search.html", context)
