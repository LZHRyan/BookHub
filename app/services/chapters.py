"""章的生命周期服务：章只是「目录行 + 发布开关」，正文与版本都在节上。

目录是两级：Book → 章 → 节。章负责排序、发布/撤回与标题，节由 `sections.py` 管理。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFound, ValidationFailed
from app.models import (
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    STATUSES,
    VISIBILITY_PUBLIC,
    Book,
    Chapter,
    ChapterSection,
    User,
    utcnow,
)
from app.services import audit, builtin
from app.services import sections as sections_service
from app.services import webhooks as events
from app.services.books import _chapter_slug_exists
from app.services.render import to_plain_text
from app.services.search import index_section, remove_from_index
from app.services.slug import slugify, unique_slug


def next_sort_order(session: Session, book_id: int) -> int:
    """章的排序作用域是 Book：同一本书一串序号，步长 10。"""
    current = session.execute(
        select(func.max(Chapter.sort_order)).where(
            Chapter.book_id == book_id, Chapter.deleted_at.is_(None)
        )
    ).scalar()
    return int(current or 0) + 10


def resolve_chapter_slug(session: Session, book_id: int, raw_slug: str, title: str) -> str:
    base = slugify(raw_slug) if (raw_slug or "").strip() else slugify(title)
    return unique_slug(
        base,
        lambda candidate: _chapter_slug_exists(session, book_id, candidate),
        prefix="chapter",
    )


def create_chapter(
    session: Session,
    book: Book,
    *,
    title: str,
    slug_raw: str = "",
    status: str = STATUS_DRAFT,
    actor: User | None = None,
    ip: str = "",
    note: str = "新建章",
    files: list[dict[str, Any]] | None = None,
    max_chars: int = sections_service.DEFAULT_MAX_CONTENT_CHARS,
) -> Chapter:
    """建一章；`files` 里的每一项都会生成一节（多文件上传 = 多节）。

    每项形如 `{"title": str, "raw": str, "format": str | None, "slug": str}`。
    """
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValidationFailed("章标题必填")
    if status not in STATUSES:
        raise ValidationFailed("章状态取值非法")
    if book.deleted_at is not None:
        raise NotFound("Book 不存在")

    chapter = Chapter(
        book_id=book.id,
        slug=resolve_chapter_slug(session, book.id, slug_raw, clean_title),
        title=clean_title,
        sort_order=next_sort_order(session, book.id),
        status=status,
        published_at=utcnow() if status == STATUS_PUBLISHED else None,
        created_by=actor.id if actor else None,
        updated_by=actor.id if actor else None,
    )
    session.add(chapter)
    session.flush()

    payloads = list(files or [])
    for item in payloads:
        sections_service.create_section(
            session,
            chapter,
            title=str(item.get("title") or clean_title),
            raw=str(item.get("raw") or ""),
            fmt=item.get("format"),  # type: ignore[arg-type]
            slug_raw=str(item.get("slug") or ""),
            actor=actor,
            ip=ip,
            note=note,
            max_chars=max_chars,
        )
    audit.record(
        session,
        actor=actor,
        action="chapter.create",
        target_type="chapter",
        target_id=chapter.id,
        target_label=chapter.title,
        book_id=book.id,
        detail={"slug": chapter.slug, "status": status, "sections": len(payloads)},
        ip=ip,
    )
    return chapter


def create_chapter_with_section(
    session: Session,
    book: Book,
    *,
    title: str,
    raw: str,
    fmt: str | None = None,
    slug_raw: str = "",
    status: str = STATUS_DRAFT,
    section_slug: str = "",
    actor: User | None = None,
    ip: str = "",
    note: str = "新建章",
    max_chars: int = sections_service.DEFAULT_MAX_CONTENT_CHARS,
) -> tuple[Chapter, ChapterSection]:
    """一次建「章 + 它唯一的一节」，返回两者（脚本、演示数据与测试的常用入口）。"""
    chapter = create_chapter(
        session,
        book,
        title=title,
        slug_raw=slug_raw,
        status=status,
        actor=actor,
        ip=ip,
        note=note,
        files=[{"title": title, "raw": raw, "format": fmt, "slug": section_slug}],
        max_chars=max_chars,
    )
    section = sections_service.ordered_sections(session, chapter.id)[0]
    return chapter, section


def update_chapter(
    session: Session,
    chapter: Chapter,
    *,
    title: str | None = None,
    slug_raw: str | None = None,
    actor: User | None = None,
    ip: str = "",
) -> Chapter:
    """只改章级字段（标题 / 访问标识）；正文走 `sections.replace_content`。"""
    changed: dict[str, object] = {}
    if title is not None and title.strip() and title.strip() != chapter.title:
        changed["title"] = chapter.title
        chapter.title = title.strip()
    if slug_raw is not None and slug_raw.strip() and slug_raw.strip() != chapter.slug:
        new_slug = resolve_chapter_slug(session, chapter.book_id, slug_raw, chapter.title)
        changed["slug"] = chapter.slug
        chapter.slug = new_slug
    if not changed:
        return chapter
    chapter.updated_at = utcnow()
    chapter.updated_by = actor.id if actor else None
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="chapter.update",
        target_type="chapter",
        target_id=chapter.id,
        target_label=chapter.title,
        book_id=chapter.book_id,
        detail=changed,
        ip=ip,
    )
    # 只有标题 / 序号 / 发布状态这类章级字段变化才发 chapter.* 事件；
    # 改正文发的是 section.updated，避免一次保存触发两条。
    events.dispatch(session, "chapter.updated", _event_payload(chapter))
    return chapter


def set_status(
    session: Session,
    chapter: Chapter,
    status: str,
    *,
    actor: User | None = None,
    ip: str = "",
) -> Chapter:
    """发布状态在章级：发布 → 其下所有节对外可见；撤回 → 全部 404。"""
    if status not in STATUSES:
        raise ValidationFailed("章节状态取值非法")
    if chapter.status == status:
        return chapter
    chapter.status = status
    if status == STATUS_PUBLISHED and chapter.published_at is None:
        chapter.published_at = utcnow()
    chapter.updated_at = utcnow()
    chapter.updated_by = actor.id if actor else chapter.updated_by
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="chapter.publish" if status == STATUS_PUBLISHED else "chapter.unpublish",
        target_type="chapter",
        target_id=chapter.id,
        target_label=chapter.title,
        book_id=chapter.book_id,
        detail={"status": status},
        ip=ip,
    )
    events.dispatch(
        session,
        "chapter.published" if status == STATUS_PUBLISHED else "chapter.unpublished",
        _event_payload(chapter),
    )
    if status == STATUS_PUBLISHED:
        for section in sections_service.ordered_sections(session, chapter.id):
            events.dispatch(session, "section.published", sections_service.event_payload(section))
    return chapter


def _event_payload(chapter: Chapter) -> dict[str, object]:
    """Webhook 事件的最小上下文：足够接收方定位内容，不夹带正文。"""
    book = chapter.book
    return {
        "book": {"id": chapter.book_id},
        "book_slug": book.slug if book is not None else "",
        "chapter": {
            "id": chapter.id,
            "slug": chapter.slug,
            "title": chapter.title,
            "status": chapter.status,
            "updated_at": chapter.updated_at.isoformat(),
        },
        "chapter_slug": chapter.slug,
    }


def ordered_chapters(
    session: Session, book_id: int, *, include_deleted: bool = False
) -> list[Chapter]:
    conditions = [Chapter.book_id == book_id]
    if not include_deleted:
        conditions.append(Chapter.deleted_at.is_(None))
    return list(
        session.execute(
            select(Chapter)
            .where(*conditions)
            .order_by(Chapter.sort_order.asc(), Chapter.created_at.asc(), Chapter.id.asc())
        )
        .scalars()
        .all()
    )


def published_chapters(session: Session, book_id: int) -> list[Chapter]:
    return [
        chapter for chapter in ordered_chapters(session, book_id) if chapter.status == STATUS_PUBLISHED
    ]


def tree(session: Session, book_id: int, *, published_only: bool = False) -> list[dict[str, Any]]:
    """两级目录：`[{chapter, no, sections: [(section, "1.1")]}]`。

    - `no` 是章号（`1`、`2`），节号由章号与节序拼成（`1.1`、`1.2`）；
    - `published_only=True` 时过滤掉草稿章（节没有独立状态，跟着章走）。
    """
    chapters = ordered_chapters(session, book_id)
    if published_only:
        chapters = [chapter for chapter in chapters if chapter.status == STATUS_PUBLISHED]
    rows: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters, start=1):
        no = str(index)
        sections = sections_service.ordered_sections(session, chapter.id)
        rows.append(
            {
                "chapter": chapter,
                "no": no,
                "sections": sections_service.section_numbers(sections, no),
            }
        )
    return rows


def flat_published_sections(session: Session, book_id: int) -> list[tuple[Chapter, ChapterSection]]:
    """按目录顺序拍平「已发布章 → 其节」，用于上一篇/下一篇。"""
    flat: list[tuple[Chapter, ChapterSection]] = []
    for row in tree(session, book_id, published_only=True):
        flat.extend((row["chapter"], section) for section, _no in row["sections"])
    return flat


def neighbours(
    session: Session, section: ChapterSection
) -> tuple[tuple[Chapter, ChapterSection] | None, tuple[Chapter, ChapterSection] | None]:
    """按节序列取上一篇/下一篇；跨章自动跳转。"""
    chapter = section.chapter
    if chapter is None:
        return None, None
    flat = flat_published_sections(session, chapter.book_id)
    for index, (_chapter, item) in enumerate(flat):
        if item.id != section.id:
            continue
        previous = flat[index - 1] if index > 0 else None
        following = flat[index + 1] if index + 1 < len(flat) else None
        return previous, following
    return None, None


def _rewrite_order(session: Session, chapters: list[Chapter]) -> None:
    for index, item in enumerate(chapters, start=1):
        item.sort_order = index * 10
    session.flush()


def move_chapter(
    session: Session,
    chapter: Chapter,
    direction: int,
    *,
    actor: User | None = None,
    ip: str = "",
) -> None:
    siblings = ordered_chapters(session, chapter.book_id)
    ids = [item.id for item in siblings]
    if chapter.id not in ids:
        raise NotFound("章节不存在")
    position = ids.index(chapter.id)
    target = position + direction
    if target < 0 or target >= len(siblings):
        return
    siblings[position], siblings[target] = siblings[target], siblings[position]
    _rewrite_order(session, siblings)
    audit.record(
        session,
        actor=actor,
        action="chapter.reorder",
        target_type="chapter",
        target_id=chapter.id,
        target_label=chapter.title,
        book_id=chapter.book_id,
        detail={"from": position + 1, "to": target + 1},
        ip=ip,
    )


def reorder_chapters(
    session: Session,
    book_id: int,
    ordered_ids: list[int],
    *,
    actor: User | None = None,
    ip: str = "",
) -> list[Chapter]:
    siblings = ordered_chapters(session, book_id)
    by_id = {item.id: item for item in siblings}
    if set(ordered_ids) != set(by_id):
        raise ValidationFailed("排序列表与该 Book 下的章节不一致（可能有人同时修改，请刷新后重试）")
    ordered = [by_id[chapter_id] for chapter_id in ordered_ids]
    _rewrite_order(session, ordered)
    audit.record(
        session,
        actor=actor,
        action="chapter.reorder",
        target_type="book",
        target_id=book_id,
        book_id=book_id,
        detail={"order": ordered_ids},
        ip=ip,
    )
    return ordered


def soft_delete_chapter(
    session: Session, chapter: Chapter, *, actor: User | None = None, ip: str = ""
) -> None:
    """删章连带把它的节一起下架；节本身不软删，恢复章即恢复全部节。"""
    builtin.reject_content_delete(chapter.book, "章")
    if chapter.deleted_at is not None:
        return
    chapter.deleted_at = utcnow()
    chapter.updated_at = chapter.deleted_at
    for section in sections_service.ordered_sections(session, chapter.id):
        remove_from_index(session, section.id)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="chapter.delete",
        target_type="chapter",
        target_id=chapter.id,
        target_label=chapter.title,
        book_id=chapter.book_id,
        detail={"sections": len(sections_service.ordered_sections(session, chapter.id))},
        ip=ip,
    )


def restore_chapter(
    session: Session, chapter: Chapter, *, actor: User | None = None, ip: str = ""
) -> None:
    if chapter.deleted_at is None:
        return
    chapter.deleted_at = None
    chapter.updated_at = utcnow()
    if _chapter_slug_exists(session, chapter.book_id, chapter.slug, exclude_id=chapter.id):
        chapter.slug = unique_slug(
            chapter.slug,
            lambda candidate: _chapter_slug_exists(
                session, chapter.book_id, candidate, exclude_id=chapter.id
            ),
            prefix="chapter",
        )
    session.flush()
    for section in sections_service.ordered_sections(session, chapter.id):
        index_section(
            session,
            section_id=section.id,
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            title=section.title,
            body=to_plain_text(section.content_rendered),
        )
    audit.record(
        session,
        actor=actor,
        action="chapter.restore",
        target_type="chapter",
        target_id=chapter.id,
        target_label=chapter.title,
        book_id=chapter.book_id,
        ip=ip,
    )


def get_chapter(session: Session, ref: str | int, *, include_deleted: bool = False) -> Chapter:
    query = select(Chapter)
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        query = query.where(Chapter.id == int(ref))
    else:
        raise NotFound("章节不存在")
    if not include_deleted:
        query = query.where(Chapter.deleted_at.is_(None))
    chapter = session.execute(query).scalar_one_or_none()
    if chapter is None:
        raise NotFound("章节不存在")
    return chapter


def find_chapter(
    session: Session,
    book_slug: str,
    chapter_slug: str,
    *,
    allow_unpublished: bool = False,
) -> tuple[Book, Chapter]:
    """按 slug 定位章；默认只认已发布章，登录用户可以看草稿预览。"""
    conditions = [
        Book.slug == book_slug,
        Book.deleted_at.is_(None),
        Chapter.slug == chapter_slug,
        Chapter.deleted_at.is_(None),
    ]
    if not allow_unpublished:
        conditions.append(Chapter.status == STATUS_PUBLISHED)
    row = session.execute(
        select(Book, Chapter).join(Chapter, Chapter.book_id == Book.id).where(*conditions)
    ).first()
    if row is None:
        raise NotFound("章节不存在")
    return row[0], row[1]


def find_published_chapter(
    session: Session, book_slug: str, chapter_slug: str
) -> tuple[Book, Chapter]:
    """访客/API 视角的定位：草稿、已删除、Book 已删除一律 404。"""
    return find_chapter(session, book_slug, chapter_slug)


def chapters_updated_since(session: Session, since: datetime) -> list[dict[str, Any]]:
    """对外增量同步流：以**节**为条目，章的信息作为上下文带上。

    墓碑（`deleted: true`）= 从可见集合里消失的条目（章或节被删、章撤回发布），
    调用方据此清理本地副本；从未发布过的草稿不进入对外同步流。
    """
    rows = session.execute(
        select(ChapterSection, Chapter, Book)
        .join(Chapter, Chapter.id == ChapterSection.chapter_id)
        .join(Book, Book.id == Chapter.book_id)
        .where(
            ChapterSection.updated_at > since,
            Book.visibility == VISIBILITY_PUBLIC,
            Book.deleted_at.is_(None),
        )
        .order_by(ChapterSection.updated_at.asc())
    ).all()
    items: list[dict[str, Any]] = []
    for section, chapter, book in rows:
        visible = (
            section.deleted_at is None
            and chapter.deleted_at is None
            and chapter.status == STATUS_PUBLISHED
        )
        if not visible and chapter.published_at is None:
            continue
        item = {
            "id": section.id,
            "book_id": book.id,
            "book_slug": book.slug,
            "chapter_id": chapter.id,
            "chapter_slug": chapter.slug,
            "slug": section.slug,
            "format": section.format,
            "version": section.current_version_no,
            "updated_at": section.updated_at,
            "deleted": not visible,
            "published": visible,
        }
        if visible:
            item["chapter_title"] = chapter.title
            item["title"] = section.title
        # 墓碑只回 id/slug：已删除或已撤回的内容连标题也不再对外暴露
        items.append(item)
    return items


__all__ = [
    "chapters_updated_since",
    "create_chapter",
    "create_chapter_with_section",
    "find_chapter",
    "find_published_chapter",
    "flat_published_sections",
    "get_chapter",
    "move_chapter",
    "neighbours",
    "next_sort_order",
    "ordered_chapters",
    "published_chapters",
    "reorder_chapters",
    "resolve_chapter_slug",
    "restore_chapter",
    "set_status",
    "soft_delete_chapter",
    "tree",
    "update_chapter",
]
