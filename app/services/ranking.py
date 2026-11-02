"""Book 排序权重：由访问热度与创建时间自动计算，不接受人工设置。

权重由两部分相加：

- 热度分 `HOT_VIEW_WEIGHT * ln(1 + 近 7 天访问数) + TOTAL_VIEW_WEIGHT * ln(1 + 累计访问数)`
- 新鲜度分 `FRESHNESS_WEIGHT * 2 ** (-创建天数 / FRESHNESS_HALF_LIFE_DAYS)`

访问计数按**节**记录（`section_view_daily`），Book 的热度 = 它各节之和。

取对数是为了避免一次访问顶掉所有历史积累：访问量线性增长时权重只缓慢上升。
新鲜度分让刚建好的 Book 起点靠前，之后按 14 天半衰期衰减。

对同一次请求里的所有 Book，"现在" 是同一个值，所以新鲜度项相当于
`2 ** (-now/tau) * 2 ** (created_at/tau)`，公共因子不影响相对顺序：
**只要访问量不变，列表顺序就稳定**，不会每刷新一次就抖一下。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Book, Chapter, ChapterSection, SectionViewDaily, utcnow

# 热度统计窗口（含今天）
HOT_WINDOW_DAYS = 7
# 近 7 天每次访问的权重系数
HOT_VIEW_WEIGHT = 100.0
# 累计访问的长期权重系数（打 1/4 折，避免老 Book 靠历史流量永久霸榜）
TOTAL_VIEW_WEIGHT = 25.0
# 全新 Book 的新鲜度加成
FRESHNESS_WEIGHT = 60.0
# 新鲜度半衰期：每过这么多天，新鲜度加成减半
FRESHNESS_HALF_LIFE_DAYS = 14.0


@dataclass(frozen=True)
class BookStats:
    """单个 Book 的热度数据与最终权重。"""

    total_views: int = 0
    recent_views: int = 0
    weight: float = 0.0


def _age_days(created_at: datetime, now: datetime) -> float:
    seconds = (now - created_at).total_seconds()
    return max(0.0, seconds / 86400.0)


def compute_weight(
    *,
    recent_views: int,
    total_views: int,
    created_at: datetime,
    now: datetime,
) -> float:
    """计算排序权重：热度越高、创建越晚，权重越大。"""
    popularity = HOT_VIEW_WEIGHT * math.log1p(max(0, recent_views))
    popularity += TOTAL_VIEW_WEIGHT * math.log1p(max(0, total_views))
    freshness = FRESHNESS_WEIGHT * 2 ** (-_age_days(created_at, now) / FRESHNESS_HALF_LIFE_DAYS)
    return popularity + freshness


def hot_cutoff(today: date) -> date:
    """热度窗口的起始日（含当天）。"""
    return today - timedelta(days=HOT_WINDOW_DAYS - 1)


def stats_for(session: Session, books: list[Book], *, now: datetime | None = None) -> dict[int, BookStats]:
    """批量查询访问统计并算出权重；没有访问记录的 Book 热度为 0。

    访问行按节存（`section_view_daily`），这里 join 回章与 Book 求和：
    一本书的热度 = 它各节访问数之和。
    """
    if not books:
        return {}
    now = now or utcnow()
    ids = [book.id for book in books]
    recent_sum = func.coalesce(
        func.sum(
            case((SectionViewDaily.day >= hot_cutoff(now.date()), SectionViewDaily.views), else_=0)
        ),
        0,
    )
    rows = session.execute(
        select(Chapter.book_id, func.coalesce(func.sum(SectionViewDaily.views), 0), recent_sum)
        .select_from(SectionViewDaily)
        .join(ChapterSection, ChapterSection.id == SectionViewDaily.section_id)
        .join(Chapter, Chapter.id == ChapterSection.chapter_id)
        .where(Chapter.book_id.in_(ids))
        .group_by(Chapter.book_id)
    ).all()
    counters = {int(book_id): (int(total), int(recent)) for book_id, total, recent in rows}

    stats: dict[int, BookStats] = {}
    for book in books:
        total, recent = counters.get(book.id, (0, 0))
        stats[book.id] = BookStats(
            total_views=total,
            recent_views=recent,
            weight=compute_weight(
                recent_views=recent,
                total_views=total,
                created_at=book.created_at,
                now=now,
            ),
        )
    return stats


def stats_of(session: Session, book: Book, *, now: datetime | None = None) -> BookStats:
    return stats_for(session, [book], now=now).get(book.id, BookStats())


def _sort_key(book: Book, stats: BookStats) -> tuple[int, float, float, int]:
    created = book.created_at if book.created_at.tzinfo else book.created_at.replace(tzinfo=UTC)
    # 置顶优先（0 排在前），组内仍按权重降序；权重相同时新建的靠前，再以 id 兜底，
    # 保证同一份数据多次排序结果一致。
    return (0 if book.pinned else 1, -stats.weight, -created.timestamp(), -book.id)


def rank_books(session: Session, books: list[Book], *, now: datetime | None = None) -> list[Book]:
    """按自动权重降序返回 Book（不修改数据库里的任何字段）。"""
    if not books:
        return []
    stats = stats_for(session, books, now=now)
    return sorted(books, key=lambda book: _sort_key(book, stats[book.id]))


def add_view(session: Session, section_id: int, *, now: datetime | None = None) -> int:
    """给某一节的当天访问计数 +1，返回该节当天的累计值（调用方负责 commit）。"""
    now = now or utcnow()
    today = now.date()
    row = session.execute(
        select(SectionViewDaily).where(
            SectionViewDaily.section_id == section_id, SectionViewDaily.day == today
        )
    ).scalar_one_or_none()
    if row is None:
        row = SectionViewDaily(section_id=section_id, day=today, views=1, updated_at=now)
        session.add(row)
    else:
        row.views += 1
        row.updated_at = now
    session.flush()
    return int(row.views)
