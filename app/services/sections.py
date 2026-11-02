"""节的生命周期服务：一节 = 一份文件，正文、格式与版本都挂在节上。

章（`chapters` 表）只是目录行与发布开关；这里负责节的内容写入、版本、diff 与回滚。
节没有独立状态：章发布 → 所有节可见，章草稿 → 所有节 404（避免"半章可见"）。
"""

from __future__ import annotations

import difflib
import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, ContentTooLong, NotFound, ValidationFailed
from app.models import (
    FORMAT_HTML,
    FORMAT_MARKDOWN,
    FORMATS,
    STATUS_PUBLISHED,
    Book,
    Chapter,
    ChapterSection,
    SectionVersion,
    User,
    utcnow,
)
from app.services import audit, builtin
from app.services import webhooks as events
from app.services.render import count_words, public_source, render_content, to_plain_text
from app.services.search import index_section, remove_from_index
from app.services.slug import slugify, unique_slug

DEFAULT_MAX_CONTENT_CHARS = 500_000
DIFF_MAX_LINES = 5000
FORMAT_LABELS = {FORMAT_MARKDOWN: "Markdown", FORMAT_HTML: "HTML"}


def normalize_newlines(raw: str) -> str:
    """浏览器提交 textarea 时会把换行统一成 CRLF，比较内容前先归一化。"""
    return (raw or "").replace("\r\n", "\n").replace("\r", "\n")


def checksum(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def parse_toc(section: ChapterSection) -> list[dict[str, Any]]:
    try:
        value = json.loads(section.content_toc or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _validate_content(raw: str, fmt: str, max_chars: int) -> None:
    if fmt not in FORMATS:
        raise ValidationFailed("内容格式取值非法，应为 markdown 或 html")
    if len(raw) > max_chars:
        raise ContentTooLong(f"正文超过上限（{max_chars} 字符）")


def resolve_section_format(book_format: str, requested: str | None) -> str:
    """整本单一格式：节的内容格式 MUST 与 Book 的文档类型一致。

    不传 `requested` 表示沿用 Book 的格式；传了但和 Book 不一致时直接拒绝，
    避免同一本 Book 里出现 Markdown 与 HTML 混排。
    """
    if book_format not in FORMATS:
        raise ValidationFailed("Book 的文档类型非法，请先修正 Book")
    if requested is not None and requested.strip():
        if requested not in FORMATS:
            raise ValidationFailed("内容格式取值非法，应为 markdown 或 html")
        if requested != book_format:
            raise ValidationFailed(
                f"这本 Book 是 {FORMAT_LABELS[book_format]} 类型，"
                f"不能写入 {FORMAT_LABELS[requested]} 格式的节"
            )
    return book_format


def next_sort_order(session: Session, chapter_id: int) -> int:
    """排序作用域是章：同一章内每节一串序号，步长 10。"""
    current = session.execute(
        select(func.max(ChapterSection.sort_order)).where(
            ChapterSection.chapter_id == chapter_id,
            ChapterSection.deleted_at.is_(None),
        )
    ).scalar()
    return int(current or 0) + 10


def _section_slug_exists(
    session: Session, chapter_id: int, slug: str, *, exclude_id: int | None = None
) -> bool:
    query = select(ChapterSection.id).where(
        ChapterSection.chapter_id == chapter_id,
        ChapterSection.slug == slug,
        ChapterSection.deleted_at.is_(None),
    )
    if exclude_id is not None:
        query = query.where(ChapterSection.id != exclude_id)
    return session.execute(query).first() is not None


def resolve_section_slug(session: Session, chapter_id: int, raw_slug: str, title: str) -> str:
    """节在章内唯一；留空时按标题生成，中文标题会得到 `section-xxxxxx` 这类回退值。"""
    base = slugify(raw_slug) if (raw_slug or "").strip() else slugify(title)
    return unique_slug(
        base,
        lambda candidate: _section_slug_exists(session, chapter_id, candidate),
        prefix="section",
    )


def _apply_content(
    session: Session,
    section: ChapterSection,
    *,
    title: str,
    fmt: str,
    raw: str,
    actor_id: int | None,
) -> None:
    section.title = title
    section.format = fmt
    section.content_raw = raw
    section.content_safe = public_source(raw, fmt)
    section.content_checksum = checksum(raw)
    rendered, toc = render_content(raw, fmt)
    section.content_rendered = rendered
    section.content_toc = json.dumps(toc, ensure_ascii=False)
    plain = to_plain_text(rendered)
    section.word_count = count_words(plain)
    section.updated_at = utcnow()
    section.updated_by = actor_id
    chapter = section.chapter
    if chapter is not None:
        chapter.updated_at = section.updated_at
    if section.id is not None and chapter is not None:
        index_section(
            session,
            section_id=section.id,
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            title=section.title,
            body=plain,
        )


def ordered_sections(
    session: Session, chapter_id: int, *, include_deleted: bool = False
) -> list[ChapterSection]:
    conditions = [ChapterSection.chapter_id == chapter_id]
    if not include_deleted:
        conditions.append(ChapterSection.deleted_at.is_(None))
    return list(
        session.execute(
            select(ChapterSection)
            .where(*conditions)
            .order_by(
                ChapterSection.sort_order.asc(),
                ChapterSection.created_at.asc(),
                ChapterSection.id.asc(),
            )
        )
        .scalars()
        .all()
    )


def list_sections(
    session: Session, chapter: Chapter, *, include_deleted: bool = False
) -> list[ChapterSection]:
    return ordered_sections(session, chapter.id, include_deleted=include_deleted)


def section_counts(
    session: Session, chapter_ids: list[int], *, include_deleted: bool = False
) -> dict[int, int]:
    """批量取「每章有多少节」，供后台表格与 API 列表避免 N+1。"""
    if not chapter_ids:
        return {}
    conditions = [ChapterSection.chapter_id.in_(chapter_ids)]
    if not include_deleted:
        conditions.append(ChapterSection.deleted_at.is_(None))
    rows = session.execute(
        select(ChapterSection.chapter_id, func.count())
        .where(*conditions)
        .group_by(ChapterSection.chapter_id)
    ).all()
    counts = dict.fromkeys(chapter_ids, 0)
    for chapter_id, count in rows:
        counts[int(chapter_id)] = int(count)
    return counts


def get_section(
    session: Session, chapter: Chapter, ref: str | int, *, include_deleted: bool = False
) -> ChapterSection:
    """按 id 或 slug 在**这一章内**定位节；跨章引用一律当作不存在。"""
    query = select(ChapterSection)
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        query = query.where(ChapterSection.id == int(ref))
    else:
        query = query.where(ChapterSection.slug == str(ref))
    query = query.where(ChapterSection.chapter_id == chapter.id)
    if not include_deleted:
        query = query.where(ChapterSection.deleted_at.is_(None))
    section = session.execute(query).scalar_one_or_none()
    if section is None:
        raise NotFound("节不存在")
    return section


def find_section(
    session: Session,
    book_slug: str,
    chapter_slug: str,
    section_slug: str,
    *,
    allow_unpublished: bool = False,
) -> tuple[Book, Chapter, ChapterSection]:
    """按 slug 三元组定位节；默认只认已发布章节下的未删除节。"""
    conditions = [
        Book.slug == book_slug,
        Book.deleted_at.is_(None),
        Chapter.slug == chapter_slug,
        Chapter.deleted_at.is_(None),
        ChapterSection.slug == section_slug,
        ChapterSection.deleted_at.is_(None),
    ]
    if not allow_unpublished:
        conditions.append(Chapter.status == STATUS_PUBLISHED)
    row = session.execute(
        select(Book, Chapter, ChapterSection)
        .join(Chapter, Chapter.book_id == Book.id)
        .join(ChapterSection, ChapterSection.chapter_id == Chapter.id)
        .where(*conditions)
    ).first()
    if row is None:
        raise NotFound("节不存在")
    return row[0], row[1], row[2]


def create_section(
    session: Session,
    chapter: Chapter,
    *,
    title: str,
    raw: str,
    fmt: str | None = None,
    slug_raw: str = "",
    actor: User | None = None,
    ip: str = "",
    note: str = "新建节",
    max_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> ChapterSection:
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValidationFailed("节标题必填")
    if chapter.deleted_at is not None:
        raise NotFound("章不存在")
    book = chapter.book
    if book is None or book.deleted_at is not None:
        raise NotFound("Book 不存在")
    resolved = resolve_section_format(book.format, fmt)
    _validate_content(raw, resolved, max_chars)

    section = ChapterSection(
        chapter_id=chapter.id,
        chapter=chapter,
        slug=resolve_section_slug(session, chapter.id, slug_raw, clean_title),
        title=clean_title,
        format=resolved,
        content_raw=raw,
        content_checksum=checksum(raw),
        content_rendered="",
        content_toc="[]",
        sort_order=next_sort_order(session, chapter.id),
        current_version_no=1,
        created_by=actor.id if actor else None,
        updated_by=actor.id if actor else None,
    )
    session.add(section)
    session.flush()
    _apply_content(
        session,
        section,
        title=clean_title,
        fmt=resolved,
        raw=raw,
        actor_id=actor.id if actor else None,
    )
    session.add(
        SectionVersion(
            section_id=section.id,
            version_no=1,
            title=section.title,
            format=section.format,
            content_raw=section.content_raw,
            note=note,
            created_by=actor.id if actor else None,
        )
    )
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="section.create",
        target_type="section",
        target_id=section.id,
        target_label=section.title,
        book_id=chapter.book_id,
        detail={
            "chapter_id": chapter.id,
            "slug": section.slug,
            "format": resolved,
            "to_version": 1,
        },
        ip=ip,
    )
    return section


def replace_content(
    session: Session,
    section: ChapterSection,
    *,
    title: str | None = None,
    raw: str | None = None,
    fmt: str | None = None,
    slug_raw: str | None = None,
    base_version: int | None = None,
    actor: User | None = None,
    ip: str = "",
    note: str = "替换内容",
    max_chars: int = DEFAULT_MAX_CONTENT_CHARS,
    retention: int = 50,
) -> ChapterSection:
    """替换节内容。

    幂等语义：标题、格式、正文、slug 都没变时**不产生新版本**（版本号、版本记录、
    审计与 Webhook 全部不动），这是"连点两次保存只多一个版本"的根因修复。
    """
    if base_version is not None and int(base_version) != section.current_version_no:
        raise Conflict("内容已被他人更新，请重新加载后再保存")
    chapter = section.chapter
    book = chapter.book if chapter is not None else None
    if chapter is None or book is None:
        raise NotFound("Book 不存在")
    new_title = (title if title is not None else section.title).strip()
    if not new_title:
        raise ValidationFailed("节标题必填")
    new_fmt = resolve_section_format(book.format, fmt if fmt is not None else section.format)
    new_raw = section.content_raw if raw is None else raw
    _validate_content(new_raw, new_fmt, max_chars)

    # 先算 slug 会变成什么，但不立刻写回，便于下面判断是否真的无改动
    slug_target: str | None = None
    if slug_raw is not None and slug_raw.strip():
        base = slugify(slug_raw)
        if base and base != section.slug:
            slug_target = unique_slug(
                base,
                lambda candidate: _section_slug_exists(
                    session, section.chapter_id, candidate, exclude_id=section.id
                ),
                prefix="section",
            )

    if (
        new_title == section.title
        and new_fmt == section.format
        and normalize_newlines(new_raw) == normalize_newlines(section.content_raw)
        and slug_target is None
    ):
        return section
    if slug_target is not None:
        section.slug = slug_target

    from_version = section.current_version_no
    _apply_content(
        session,
        section,
        title=new_title,
        fmt=new_fmt,
        raw=new_raw,
        actor_id=actor.id if actor else None,
    )
    section.current_version_no = from_version + 1
    session.add(
        SectionVersion(
            section_id=section.id,
            version_no=section.current_version_no,
            title=section.title,
            format=section.format,
            content_raw=section.content_raw,
            note=note,
            created_by=actor.id if actor else None,
        )
    )
    session.flush()
    prune_versions(session, section, retention)
    audit.record(
        session,
        actor=actor,
        action="section.replace",
        target_type="section",
        target_id=section.id,
        target_label=section.title,
        book_id=chapter.book_id,
        detail={
            "chapter_id": section.chapter_id,
            "from_version": from_version,
            "to_version": section.current_version_no,
            "note": note,
        },
        ip=ip,
    )
    events.dispatch(session, "section.updated", event_payload(section))
    return section


def event_payload(section: ChapterSection) -> dict[str, object]:
    """Webhook 事件的最小上下文：足够接收方定位内容，不夹带正文。"""
    chapter = section.chapter
    book = chapter.book if chapter is not None else None
    return {
        "book": {"id": chapter.book_id if chapter else None},
        "book_slug": book.slug if book is not None else "",
        "chapter": {
            "id": chapter.id if chapter else None,
            "slug": chapter.slug if chapter else "",
            "title": chapter.title if chapter else "",
            "status": chapter.status if chapter else "",
        },
        "chapter_slug": chapter.slug if chapter else "",
        "section": {
            "id": section.id,
            "slug": section.slug,
            "title": section.title,
            "format": section.format,
            "version": section.current_version_no,
            "word_count": section.word_count,
            "updated_at": section.updated_at.isoformat(),
        },
        "section_slug": section.slug,
    }


def delete_section(
    session: Session, section: ChapterSection, *, actor: User | None = None, ip: str = ""
) -> None:
    builtin.reject_content_delete(section.chapter.book, "节")
    if section.deleted_at is not None:
        return
    section.deleted_at = utcnow()
    section.updated_at = section.deleted_at
    remove_from_index(session, section.id)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="section.delete",
        target_type="section",
        target_id=section.id,
        target_label=section.title,
        book_id=section.chapter.book_id,
        detail={"chapter_id": section.chapter_id, "version": section.current_version_no},
        ip=ip,
    )


def restore_section(
    session: Session, section: ChapterSection, *, actor: User | None = None, ip: str = ""
) -> None:
    if section.deleted_at is None:
        return
    section.deleted_at = None
    section.updated_at = utcnow()
    if _section_slug_exists(session, section.chapter_id, section.slug, exclude_id=section.id):
        section.slug = unique_slug(
            section.slug,
            lambda candidate: _section_slug_exists(
                session, section.chapter_id, candidate, exclude_id=section.id
            ),
            prefix="section",
        )
    session.flush()
    chapter = section.chapter
    if chapter is not None:
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
        action="section.restore",
        target_type="section",
        target_id=section.id,
        target_label=section.title,
        book_id=section.chapter.book_id,
        detail={"chapter_id": section.chapter_id},
        ip=ip,
    )


def _rewrite_order(session: Session, sections: list[ChapterSection]) -> None:
    for index, item in enumerate(sections, start=1):
        item.sort_order = index * 10
    session.flush()


def move_section(
    session: Session,
    section: ChapterSection,
    direction: int,
    *,
    actor: User | None = None,
    ip: str = "",
) -> None:
    """章内上移/下移（不做拖拽、不做跨章移动）。"""
    siblings = ordered_sections(session, section.chapter_id)
    ids = [item.id for item in siblings]
    if section.id not in ids:
        raise NotFound("节不存在")
    position = ids.index(section.id)
    target = position + direction
    if target < 0 or target >= len(siblings):
        return
    siblings[position], siblings[target] = siblings[target], siblings[position]
    _rewrite_order(session, siblings)
    audit.record(
        session,
        actor=actor,
        action="section.reorder",
        target_type="section",
        target_id=section.id,
        target_label=section.title,
        book_id=section.chapter.book_id,
        detail={"chapter_id": section.chapter_id, "from": position + 1, "to": target + 1},
        ip=ip,
    )


def reorder_sections(
    session: Session,
    chapter: Chapter,
    ordered_ids: list[int],
    *,
    actor: User | None = None,
    ip: str = "",
) -> list[ChapterSection]:
    """按有序 id 列表整体重排一章内的节；集合不一致直接拒绝。"""
    siblings = ordered_sections(session, chapter.id)
    by_id = {item.id: item for item in siblings}
    if set(ordered_ids) != set(by_id):
        raise ValidationFailed("排序列表与该章下的节不一致（可能有人同时修改，请刷新后重试）")
    ordered = [by_id[section_id] for section_id in ordered_ids]
    _rewrite_order(session, ordered)
    audit.record(
        session,
        actor=actor,
        action="section.reorder",
        target_type="chapter",
        target_id=chapter.id,
        target_label=chapter.title,
        book_id=chapter.book_id,
        detail={"order": ordered_ids},
        ip=ip,
    )
    return ordered


def move_to_chapter(
    session: Session, section: ChapterSection, chapter: Chapter, *, actor: User | None = None
) -> None:
    """跨章移动节不在本期范围内：保留显式拒绝，避免调用方默默做错事。"""
    raise ValidationFailed("不支持把节移动到别的章：请在新章里新建一节，再删除原节")


def list_versions(session: Session, section: ChapterSection) -> list[SectionVersion]:
    return list(
        session.execute(
            select(SectionVersion)
            .where(SectionVersion.section_id == section.id)
            .order_by(SectionVersion.version_no.desc())
        )
        .scalars()
        .all()
    )


def get_version(session: Session, section: ChapterSection, version_no: int) -> SectionVersion:
    version = session.execute(
        select(SectionVersion).where(
            SectionVersion.section_id == section.id, SectionVersion.version_no == version_no
        )
    ).scalar_one_or_none()
    if version is None:
        raise NotFound("版本不存在")
    return version


def prune_versions(session: Session, section: ChapterSection, retention: int) -> int:
    if retention <= 0:
        return 0
    versions = list_versions(session, section)
    removed = 0
    for version in versions[retention:]:
        if version.version_no == section.current_version_no:
            continue
        session.delete(version)
        removed += 1
    if removed:
        session.flush()
    return removed


def diff_versions(
    session: Session, section: ChapterSection, left_no: int, right_no: int
) -> dict[str, object]:
    left = get_version(session, section, left_no)
    right = get_version(session, section, right_no)
    left_lines = left.content_raw.splitlines()
    right_lines = right.content_raw.splitlines()
    truncated = False
    rows: list[dict[str, object]] = []
    matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if len(rows) >= DIFF_MAX_LINES:
            truncated = True
            break
        if tag == "equal":
            rows.append({"type": "equal", "left_no": i1 + 1, "right_no": j1 + 1, "text": "\n".join(left_lines[i1:i2])})
        elif tag == "delete":
            rows.append({"type": "delete", "left_no": i1 + 1, "right_no": None, "text": "\n".join(left_lines[i1:i2])})
        elif tag == "insert":
            rows.append({"type": "insert", "left_no": None, "right_no": j1 + 1, "text": "\n".join(right_lines[j1:j2])})
        else:  # replace
            rows.append({"type": "delete", "left_no": i1 + 1, "right_no": None, "text": "\n".join(left_lines[i1:i2])})
            rows.append({"type": "insert", "left_no": None, "right_no": j1 + 1, "text": "\n".join(right_lines[j1:j2])})
    return {
        "left": left,
        "right": right,
        "rows": rows,
        "identical": left.content_raw == right.content_raw,
        "truncated": truncated,
    }


def rollback(
    session: Session,
    section: ChapterSection,
    version_no: int,
    *,
    actor: User | None = None,
    ip: str = "",
    retention: int = 50,
    max_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> ChapterSection:
    """回滚只作用于一个节：写回旧内容并追加一个新版本，章状态不变。"""
    version = get_version(session, section, version_no)
    return replace_content(
        session,
        section,
        title=version.title or section.title,
        raw=version.content_raw,
        fmt=version.format,
        base_version=None,
        actor=actor,
        ip=ip,
        note=f"回滚到版本 {version_no}",
        max_chars=max_chars,
        retention=retention,
    )


def section_numbers(
    sections: list[ChapterSection], chapter_no: str
) -> list[tuple[ChapterSection, str]]:
    """给每节配一个展示编号：`1.1`、`1.2`（章号.节序）。"""
    return [(section, f"{chapter_no}.{index}") for index, section in enumerate(sections, start=1)]


__all__ = [
    "DEFAULT_MAX_CONTENT_CHARS",
    "FORMAT_LABELS",
    "checksum",
    "create_section",
    "delete_section",
    "diff_versions",
    "event_payload",
    "find_section",
    "get_section",
    "get_version",
    "list_sections",
    "list_versions",
    "move_section",
    "move_to_chapter",
    "next_sort_order",
    "normalize_newlines",
    "ordered_sections",
    "parse_toc",
    "prune_versions",
    "reorder_sections",
    "replace_content",
    "resolve_section_format",
    "resolve_section_slug",
    "restore_section",
    "rollback",
    "section_counts",
    "section_numbers",
]
