"""Book 分组服务：组的增删改查、排序，以及首页按组的分区视图。

设计见 openspec/changes/archive/2026-10-22-add-book-groups/design.md 与
openspec/specs/book-groups/spec.md：
- Book 必属于一个组（`books.group_id` NOT NULL），存量归入默认分组；
- 组的位置决定首页分区顺序，组内顺序沿用「置顶 + 热度」；
- 默认分组随系统创建、不可删除且标识固定；非空组与最后一个组也不可删。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFound, ValidationFailed
from app.models import Book, BookGroup, User, utcnow
from app.services import audit
from app.services.slug import slugify, unique_slug

DEFAULT_SLUG = "default"
DEFAULT_TITLE = "默认分组"
MAX_TITLE = 120


def is_default(group: BookGroup) -> bool:
    """默认分组：系统创建并随系统生命周期存在，标识写死为 `DEFAULT_SLUG`。

    它是「没指定分组」时的兜底；删掉它或改掉标识，`ensure_default` 的查找与
    `books.group_id` 的非空契约都会失效，所以两者都必须拒绝。
    """
    return group.slug == DEFAULT_SLUG



def _slug_exists(session: Session, slug: str, *, exclude_id: int | None = None) -> bool:
    stmt = select(BookGroup.id).where(BookGroup.slug == slug)
    if exclude_id is not None:
        stmt = stmt.where(BookGroup.id != exclude_id)
    return session.execute(stmt).first() is not None


def _resolve_slug(session: Session, title: str, slug_raw: str, *, exclude_id: int | None = None) -> str:
    base = slugify(slug_raw) if (slug_raw or "").strip() else slugify(title)
    return unique_slug(
        base,
        lambda candidate: _slug_exists(session, candidate, exclude_id=exclude_id),
        prefix="group",
    )


def ensure_default(session: Session) -> BookGroup:
    """兜底：保证至少有一个组存在（迁移已建，运行时再防一次）。"""
    group = session.execute(
        select(BookGroup).where(BookGroup.slug == DEFAULT_SLUG)
    ).scalar_one_or_none()
    if group is not None:
        return group
    group = BookGroup(
        slug=DEFAULT_SLUG,
        title=DEFAULT_TITLE,
        description="",
        icon="",
        sort_order=10,
    )
    session.add(group)
    session.flush()
    return group


def list_groups(session: Session) -> list[BookGroup]:
    return list(
        session.execute(
            select(BookGroup).order_by(BookGroup.sort_order.asc(), BookGroup.id.asc())
        ).scalars()
    )


def get_group(session: Session, ref: str | int) -> BookGroup:
    if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
        group = session.get(BookGroup, int(ref))
    else:
        group = session.execute(
            select(BookGroup).where(BookGroup.slug == str(ref).strip())
        ).scalar_one_or_none()
    if group is None:
        raise NotFound("分组不存在")
    return group


def book_counts(session: Session, *, include_deleted: bool = False) -> dict[int, int]:
    conditions = []
    if not include_deleted:
        conditions.append(Book.deleted_at.is_(None))
    rows = session.execute(
        select(Book.group_id, func.count()).where(*conditions).group_by(Book.group_id)
    ).all()
    return {int(group_id): int(count) for group_id, count in rows}


def count_books(session: Session, group_id: int) -> int:
    return int(
        session.execute(
            select(func.count())
            .select_from(Book)
            .where(Book.group_id == group_id, Book.deleted_at.is_(None))
        ).scalar_one()
    )


def create(
    session: Session,
    *,
    title: str,
    slug_raw: str = "",
    description: str = "",
    icon: str = "",
    actor: User | None = None,
    ip: str = "",
) -> BookGroup:
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValidationFailed("分组标题必填")
    if len(clean_title) > MAX_TITLE:
        raise ValidationFailed(f"分组标题不能超过 {MAX_TITLE} 个字符")
    current_max = session.execute(select(func.max(BookGroup.sort_order))).scalar() or 0
    group = BookGroup(
        slug=_resolve_slug(session, clean_title, slug_raw),
        title=clean_title,
        description=(description or "").strip(),
        icon=(icon or "").strip(),
        sort_order=int(current_max) + 10,
    )
    session.add(group)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="group.book.create",
        target_type="book_group",
        target_id=group.id,
        target_label=group.title,
        detail={"slug": group.slug},
        ip=ip,
    )
    return group


def update(
    session: Session,
    group: BookGroup,
    *,
    title: str | None = None,
    slug_raw: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    actor: User | None = None,
    ip: str = "",
) -> BookGroup:
    changed: dict[str, object] = {}
    if title is not None and title.strip() and title.strip() != group.title:
        changed["title"] = title.strip()
        group.title = title.strip()
    if slug_raw is not None and slug_raw.strip():
        new_slug = _resolve_slug(session, group.title, slug_raw, exclude_id=group.id)
        if new_slug != group.slug:
            if is_default(group):
                raise ValidationFailed(
                    "默认分组的访问标识固定为 default，不能修改（它由系统创建，用于兜底归属）"
                )
            changed["slug"] = new_slug
            group.slug = new_slug
    if description is not None and description.strip() != group.description:
        changed["description"] = description.strip()
        group.description = description.strip()
    if icon is not None and icon.strip() != group.icon:
        changed["icon"] = icon.strip()
        group.icon = icon.strip()
    if changed:
        group.updated_at = utcnow()
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="group.book.update",
            target_type="book_group",
            target_id=group.id,
            target_label=group.title,
            detail=changed,
            ip=ip,
        )
    return group


def delete(session: Session, group: BookGroup, *, actor: User | None = None, ip: str = "") -> None:
    """默认分组不可删；非空组与最后一个组也不允许删除。"""
    if is_default(group):
        raise ValidationFailed(
            "默认分组由系统创建并随系统存在，不能删除（它是未指定分组时的兜底）"
        )
    total = session.execute(select(func.count()).select_from(BookGroup)).scalar_one()
    if int(total) <= 1:
        raise ValidationFailed("至少要保留一个分组，不能删除最后一个")
    # 含回收站里的 Book：软删除的行仍持有 group_id 外键，不拦住会在数据库层炸 FK 约束
    books = int(
        session.execute(
            select(func.count()).select_from(Book).where(Book.group_id == group.id)
        ).scalar_one()
    )
    if books:
        raise ValidationFailed(
            f"分组「{group.title}」下还有 {books} 个 Book（含回收站），先把它们移到别的分组"
        )
    title, group_id = group.title, group.id
    session.delete(group)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="group.book.delete",
        target_type="book_group",
        target_id=group_id,
        target_label=title,
        ip=ip,
    )


def _rewrite_order(session: Session, groups: list[BookGroup]) -> None:
    for index, item in enumerate(groups, start=1):
        item.sort_order = index * 10
    session.flush()


def move(
    session: Session,
    group: BookGroup,
    direction: int,
    *,
    actor: User | None = None,
    ip: str = "",
) -> None:
    groups = list_groups(session)
    ids = [item.id for item in groups]
    if group.id not in ids:
        raise NotFound("分组不存在")
    position = ids.index(group.id)
    target = position + direction
    if target < 0 or target >= len(groups):
        return
    groups[position], groups[target] = groups[target], groups[position]
    _rewrite_order(session, groups)
    audit.record(
        session,
        actor=actor,
        action="group.book.reorder",
        target_type="book_group",
        target_id=group.id,
        target_label=group.title,
        detail={"from": position + 1, "to": target + 1},
        ip=ip,
    )


def overview(
    session: Session,
    *,
    visibility: str | None = "public",
    group_ref: str | None = None,
    limit_per_group: int = 24,
) -> list[dict[str, object]]:
    """首页分区：[{group, books, total, truncated}]，组内按「置顶 + 热度」排序。

    limit_per_group 只截断展示（多出来的通过「查看全部」进筛选页），不丢数据。
    """
    from app.services import books as books_service
    from app.services import ranking

    groups = list_groups(session)
    if group_ref:
        groups = [item for item in groups if item.slug == group_ref or str(item.id) == str(group_ref)]

    rows, _total = books_service.list_books(
        session, visibility=visibility, page=1, page_size=10_000
    )
    ranked = ranking.rank_books(session, rows)
    buckets: dict[int, list[Book]] = {}
    for book in ranked:
        buckets.setdefault(book.group_id, []).append(book)

    sections: list[dict[str, object]] = []
    for group in groups:
        books = buckets.get(group.id, [])
        # 空分区不渲染；筛选态下也返回空列表，让页面落到「该分组还没有可见 Book」的空态
        if not books:
            continue
        total = len(books)
        shown = books[:limit_per_group] if limit_per_group > 0 else books
        sections.append(
            {"group": group, "books": shown, "total": total, "truncated": total > len(shown)}
        )
    return sections
