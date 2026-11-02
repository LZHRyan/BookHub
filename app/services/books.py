"""Book 服务：创建、更新、软删除、排序与查询。"""

from __future__ import annotations

from sqlalchemy import false, func, select
from sqlalchemy.orm import Session

from app.errors import NotFound, ValidationFailed
from app.models import (
    FORMAT_HTML,
    FORMAT_MARKDOWN,
    FORMATS,
    HTML_VIEW_DOCUMENT,
    HTML_VIEW_INLINE,
    HTML_VIEWS,
    STATUS_PUBLISHED,
    VISIBILITIES,
    VISIBILITY_PUBLIC,
    Book,
    Chapter,
    User,
    utcnow,
)
from app.services import audit, builtin, ranking
from app.services.slug import slugify, unique_slug

MAX_TITLE = 200

# HTML Book 的默认阅读方式：上传的是什么，就读什么（原始文档，新标签页打开）。
# 想回到站内净化渲染需要在 Book 设置里显式选 inline。
DEFAULT_HTML_VIEW = HTML_VIEW_DOCUMENT


def resolve_html_view(fmt: str, html_view: str | None, *, current: str | None = None) -> str:
    """Markdown Book 永远是站内渲染；HTML Book 默认原样输出。"""
    if fmt != FORMAT_HTML:
        return HTML_VIEW_INLINE
    value = (html_view or current or DEFAULT_HTML_VIEW).strip()
    if value not in HTML_VIEWS:
        raise ValidationFailed("阅读方式取值非法，只能是 inline 或 document")
    return value


def _slug_exists(session: Session, slug: str, *, exclude_id: int | None = None) -> bool:
    query = select(Book.id).where(Book.slug == slug, Book.deleted_at.is_(None))
    if exclude_id is not None:
        query = query.where(Book.id != exclude_id)
    return session.execute(query).first() is not None


def _chapter_slug_exists(session: Session, book_id: int, slug: str, *, exclude_id: int | None = None) -> bool:
    query = select(Chapter.id).where(
        Chapter.book_id == book_id, Chapter.slug == slug, Chapter.deleted_at.is_(None)
    )
    if exclude_id is not None:
        query = query.where(Chapter.id != exclude_id)
    return session.execute(query).first() is not None


def resolve_slug(session: Session, raw_slug: str, title: str) -> str:
    base = slugify(raw_slug) if (raw_slug or "").strip() else slugify(title)
    return unique_slug(base, lambda candidate: _slug_exists(session, candidate), prefix="book")


def _resolve_group(session: Session, group: object):
    """解析 Book 的所属组（slug 或 id）。

    管理端表单与 API 都强制要求显式指定；这里对程序内部调用（脚本、测试、演示数据）
    回退到「默认分组」，保证任何 Book 都不会没有组。
    """
    from app.services import book_groups

    if group is None or (isinstance(group, str) and not group.strip()):
        return book_groups.ensure_default(session)
    return book_groups.get_group(session, group)  # type: ignore[arg-type]


def get_book(session: Session, ref: str | int, *, include_deleted: bool = False) -> Book:
    query = select(Book)
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        query = query.where(Book.id == int(ref))
    else:
        query = query.where(Book.slug == str(ref))
    if not include_deleted:
        query = query.where(Book.deleted_at.is_(None))
    book = session.execute(query).scalar_one_or_none()
    if book is None:
        raise NotFound("Book 不存在")
    return book


def list_books(
    session: Session,
    *,
    visibility: str | None = VISIBILITY_PUBLIC,
    group: object = None,
    page: int = 1,
    page_size: int = 20,
    include_deleted: bool = False,
    scope_ids: list[int] | None = None,
) -> tuple[list[Book], int]:
    """按自动权重分页返回 Book：权重越高越靠前，权重由热度与创建时间算出。

    权重依赖访问统计，无法在 SQL 里用索引直接排序，所以先取符合条件的全部 Book
    再在内存里排序切片。Book 量级是「几十到几百」，这个成本可以接受；
    分页本身的 total 也来自同一份集合，保证各页不重不漏。

    `scope_ids` 非 None 时只返回这些 Book：受限 Token 的列表不能泄露范围外的书。
    """
    conditions = []
    if not include_deleted:
        conditions.append(Book.deleted_at.is_(None))
    if visibility:
        conditions.append(Book.visibility == visibility)
    if scope_ids is not None:
        conditions.append(Book.id.in_(scope_ids) if scope_ids else false())
    if group is not None:
        from app.services import book_groups

        target = book_groups.get_group(session, group)  # type: ignore[arg-type]
        conditions.append(Book.group_id == target.id)
    rows = session.execute(select(Book).where(*conditions)).scalars().all()
    ranked = ranking.rank_books(session, list(rows))
    total = len(ranked)
    start = max(0, (page - 1) * page_size)
    return ranked[start : start + page_size], total


def chapter_counts(
    session: Session, book_ids: list[int], *, published_only: bool = True
) -> dict[int, int]:
    if not book_ids:
        return {}
    conditions = [Chapter.book_id.in_(book_ids), Chapter.deleted_at.is_(None)]
    if published_only:
        conditions.append(Chapter.status == STATUS_PUBLISHED)
    rows = session.execute(
        select(Chapter.book_id, func.count()).where(*conditions).group_by(Chapter.book_id)
    ).all()
    counts = dict.fromkeys(book_ids, 0)
    for book_id, count in rows:
        counts[int(book_id)] = int(count)
    return counts


def active_chapter_count(session: Session, book_id: int) -> int:
    """Book 下未删除的章数（列表页与 API 的「N 章」）。"""
    return int(
        session.execute(
            select(func.count())
            .select_from(Chapter)
            .where(Chapter.book_id == book_id, Chapter.deleted_at.is_(None))
        ).scalar_one()
    )


def create_book(
    session: Session,
    *,
    title: str,
    slug_raw: str = "",
    summary: str = "",
    icon: str = "",
    fmt: str = FORMAT_MARKDOWN,
    html_view: str | None = None,
    visibility: str = VISIBILITY_PUBLIC,
    group: object = None,
    actor: User | None = None,
    ip: str = "",
) -> Book:
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValidationFailed("标题必填")
    group_row = _resolve_group(session, group)
    if len(clean_title) > MAX_TITLE:
        raise ValidationFailed(f"标题不能超过 {MAX_TITLE} 个字符")
    if visibility not in VISIBILITIES:
        raise ValidationFailed("可见性取值非法")
    if fmt not in FORMATS:
        raise ValidationFailed("文档类型必填，只能是 markdown 或 html")
    view_mode = resolve_html_view(fmt, html_view)

    book = Book(
        group_id=group_row.id,
        slug=resolve_slug(session, slug_raw, clean_title),
        title=clean_title,
        summary=(summary or "").strip(),
        icon=(icon or "").strip(),
        format=fmt,
        html_view=view_mode,
        visibility=visibility,
        created_by=actor.id if actor else None,
    )
    session.add(book)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="book.create",
        target_type="book",
        target_id=book.id,
        target_label=book.title,
        book_id=book.id,
        detail={"slug": book.slug, "format": book.format, "html_view": book.html_view},
        ip=ip,
    )
    return book


def update_book(
    session: Session,
    book: Book,
    *,
    title: str | None = None,
    slug_raw: str | None = None,
    summary: str | None = None,
    icon: str | None = None,
    fmt: str | None = None,
    html_view: str | None = None,
    visibility: str | None = None,
    pinned: bool | None = None,
    group: object = None,
    actor: User | None = None,
    ip: str = "",
) -> Book:
    before = {"title": book.title, "slug": book.slug, "visibility": book.visibility}
    # 内置指南的访问标识与文档类型是外部集成（链接、MCP 配置、导出后缀）的锚点，锁定
    builtin.reject_book_identity_change(book, slug_raw=slug_raw, fmt=fmt)
    if title is not None:
        clean_title = title.strip()
        if not clean_title:
            raise ValidationFailed("标题必填")
        if len(clean_title) > MAX_TITLE:
            raise ValidationFailed(f"标题不能超过 {MAX_TITLE} 个字符")
        book.title = clean_title
    if slug_raw is not None:
        if not slug_raw.strip():
            # 显式传了就当成"要改"：空值不算"没传"，否则用户以为改了其实没改
            raise ValidationFailed("访问标识不能为空；不改请省略该字段")
        base = slugify(slug_raw)
        if base and base != book.slug:
            book.slug = unique_slug(
                base,
                lambda candidate: _slug_exists(session, candidate, exclude_id=book.id),
                prefix="book",
            )
    if summary is not None:
        book.summary = summary.strip()
    if icon is not None:
        book.icon = icon.strip()
    if fmt is not None and fmt != book.format:
        if fmt not in FORMATS:
            raise ValidationFailed("文档类型取值非法，只能是 markdown 或 html")
        # 整本单一格式：已有章时改类型会让存量节与新类型冲突
        if active_chapter_count(session, book.id):
            raise ValidationFailed(
                "该 Book 下已有章，不能修改文档类型（整本只能是同一种格式：Markdown 或 HTML）"
            )
        book.format = fmt
    if html_view is not None or fmt is not None:
        book.html_view = resolve_html_view(book.format, html_view, current=book.html_view)
    if visibility is not None:
        if visibility not in VISIBILITIES:
            raise ValidationFailed("可见性取值非法")
        book.visibility = visibility
    if group is not None:
        target = _resolve_group(session, group)
        if target.id != book.group_id:
            before["group_id"] = book.group_id
            book.group_id = target.id
    if pinned is not None and bool(pinned) != bool(book.pinned):
        book.pinned = bool(pinned)
        audit.record(
            session,
            actor=actor,
            action="book.pin" if book.pinned else "book.unpin",
            target_type="book",
            target_id=book.id,
            target_label=book.title,
            book_id=book.id,
            detail={"pinned": book.pinned},
            ip=ip,
        )
    book.updated_at = utcnow()
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="book.update",
        target_type="book",
        target_id=book.id,
        target_label=book.title,
        book_id=book.id,
        detail={"before": before, "after": {"title": book.title, "slug": book.slug, "visibility": book.visibility}},
        ip=ip,
    )
    return book


def set_cover(
    session: Session,
    book: Book,
    media_id: int | None,
    *,
    actor: User | None = None,
    ip: str = "",
) -> Book:
    """设置/清除封面：只允许本 Book 名下、图片类型、未软删的资源。"""
    from app.models import MEDIA_IMAGE, MediaAsset

    previous = book.cover_media_id
    if media_id is None:
        book.cover_media_id = None
    else:
        asset = session.get(MediaAsset, int(media_id))
        if asset is None:
            raise ValidationFailed("封面资源不存在")
        if asset.book_id != book.id:
            raise ValidationFailed("封面只能使用这个 Book 自己的图片")
        if asset.kind != MEDIA_IMAGE:
            raise ValidationFailed("封面必须是图片，不能是附件")
        if asset.deleted_at is not None:
            raise ValidationFailed("该图片已删除，不能作为封面")
        book.cover_media_id = asset.id

    if book.cover_media_id == previous:
        return book
    book.updated_at = utcnow()
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="book.cover",
        target_type="book",
        target_id=book.id,
        target_label=book.title,
        book_id=book.id,
        detail={"from": previous, "to": book.cover_media_id},
        ip=ip,
    )
    return book


def soft_delete_book(session: Session, book: Book, *, actor: User | None = None, ip: str = "") -> None:
    builtin.reject_book_delete(book)
    if book.deleted_at is not None:
        return
    book.deleted_at = utcnow()
    book.updated_at = book.deleted_at
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="book.delete",
        target_type="book",
        target_id=book.id,
        target_label=book.title,
        book_id=book.id,
        ip=ip,
    )


def restore_book(session: Session, book: Book, *, actor: User | None = None, ip: str = "") -> None:
    if book.deleted_at is None:
        return
    book.deleted_at = None
    book.updated_at = utcnow()
    if _slug_exists(session, book.slug, exclude_id=book.id):
        book.slug = unique_slug(
            book.slug,
            lambda candidate: _slug_exists(session, candidate, exclude_id=book.id),
            prefix="book",
        )
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="book.restore",
        target_type="book",
        target_id=book.id,
        target_label=book.title,
        book_id=book.id,
        ip=ip,
    )
