"""全文检索：中文二元组切分 + SQLite FTS5（Postgres 退化为 ILIKE）。

索引粒度是**节**：标题与正文都属于节，搜索结果是节，链接指向节页。
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import STATUS_PUBLISHED, VISIBILITY_PUBLIC

CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x3040, 0x30FF),
)
_ASCII_WORD = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_+#.\-]*")
CJK_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff]")
SNIPPET_RADIUS = 90
MAX_QUERY_LENGTH = 500


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in CJK_RANGES)


def tokenize(text: str) -> list[str]:
    """中文切二元组、ASCII 切词小写化。"""
    tokens: list[str] = []
    run: list[str] = []
    for char in text or "":
        if _is_cjk(char):
            run.append(char)
            continue
        if run:
            tokens.extend(_flush_run(run))
            run = []
    if run:
        tokens.extend(_flush_run(run))
    tokens.extend(word.lower() for word in _ASCII_WORD.findall(text or ""))
    return tokens


def _flush_run(run: list[str]) -> list[str]:
    if len(run) == 1:
        return [run[0]]
    return ["".join(run[index : index + 2]) for index in range(len(run) - 1)]


def index_text(text: str) -> str:
    return " ".join(tokenize(text))


def build_match_query(query: str) -> str | None:
    tokens = [token for token in tokenize(query) if token]
    if not tokens:
        return None
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return " AND ".join(f'"{token}"' for token in seen[:24])


def needs_like_fallback(query: str) -> bool:
    stripped = (query or "").strip()
    if not stripped:
        return False
    cjk_only = "".join(CJK_CHAR.findall(stripped))
    return len(cjk_only) == 1 and len(stripped) == 1


def _supports_fts(session: Session) -> bool:
    """FTS5 只存在于 SQLite；Postgres 走 ILIKE 分支，索引同步自动跳过。"""
    return session.get_bind().dialect.name == "sqlite"


def index_section(
    session: Session,
    *,
    section_id: int,
    book_id: int,
    chapter_id: int,
    title: str,
    body: str,
) -> None:
    """按节覆盖写索引：先删后插，同一事务内完成。

    `book_id` / `chapter_id` / `section_id` 是 FTS 表里的 UNINDEXED 列：只为查询
    时少一次 join 而存，不参与 MATCH 匹配（标题与正文才是索引内容）。
    """
    if not _supports_fts(session):
        return
    session.execute(text("DELETE FROM chapter_fts WHERE rowid = :rid"), {"rid": section_id})
    session.execute(
        text(
            "INSERT INTO chapter_fts (rowid, book_id, chapter_id, section_id, title, body)"
            " VALUES (:rid, :book_id, :chapter_id, :section_id, :title, :body)"
        ),
        {
            "rid": section_id,
            "book_id": str(book_id),
            "chapter_id": str(chapter_id),
            "section_id": str(section_id),
            "title": index_text(title),
            "body": index_text(body),
        },
    )


def remove_from_index(session: Session, section_id: int) -> None:
    if not _supports_fts(session):
        return
    session.execute(text("DELETE FROM chapter_fts WHERE rowid = :rid"), {"rid": section_id})


def reindex_all(session: Session) -> int:
    """供运维脚本整库重建索引。"""
    from app.models import Chapter, ChapterSection
    from app.services.render import to_plain_text

    if not _supports_fts(session):
        return 0
    session.execute(text("DELETE FROM chapter_fts"))
    rows = (
        session.query(ChapterSection)
        .join(Chapter, Chapter.id == ChapterSection.chapter_id)
        .filter(ChapterSection.deleted_at.is_(None), Chapter.deleted_at.is_(None))
        .all()
    )
    for section in rows:
        index_section(
            session,
            section_id=section.id,
            book_id=section.chapter.book_id,
            chapter_id=section.chapter_id,
            title=section.title,
            body=to_plain_text(section.content_rendered),
        )
    session.flush()
    return len(rows)


def _needles(query: str) -> list[str]:
    stripped = (query or "").strip()
    if not stripped:
        return []
    found = [stripped]
    found.extend(token for token in tokenize(stripped) if token)
    unique: list[str] = []
    for item in found:
        if item and item not in unique:
            unique.append(item)
    return sorted(unique, key=len, reverse=True)


def make_snippet(text: str, query: str) -> str:
    """在纯文本中截取命中片段，只有命中词被 <mark> 包裹。"""
    plain = re.sub(r"\s+", " ", text or "").strip()
    needles = _needles(query)
    lowered = plain.lower()
    position = -1
    hit = ""
    for needle in needles:
        index = lowered.find(needle.lower())
        if index >= 0 and (position < 0 or index < position):
            position = index
            hit = plain[index : index + len(needle)]
    if position < 0:
        head = plain[: SNIPPET_RADIUS * 2]
        return html_lib.escape(head + ("…" if len(plain) > len(head) else ""))
    start = max(0, position - SNIPPET_RADIUS)
    end = min(len(plain), position + len(hit) + SNIPPET_RADIUS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(plain) else ""
    body = plain[start:end]
    escaped = html_lib.escape(body)
    for needle in needles:
        if not needle:
            continue
        escaped = re.sub(
            f"({re.escape(html_lib.escape(needle))})",
            r"<mark>\1</mark>",
            escaped,
            flags=re.IGNORECASE,
        )
    # 避免嵌套 <mark>
    escaped = escaped.replace("<mark><mark>", "<mark>").replace("</mark></mark>", "</mark>")
    return f"{prefix}{escaped}{suffix}"


def _base_conditions() -> list[str]:
    return [
        "c.status = :published",
        "c.deleted_at IS NULL",
        "s.deleted_at IS NULL",
        "b.deleted_at IS NULL",
        "b.visibility = :public",
    ]


_SELECT_COLUMNS = (
    "s.id AS section_id, s.slug AS section_slug, s.title AS section_title,"
    " c.id AS chapter_id, c.slug AS chapter_slug, c.title AS chapter_title,"
    " c.book_id AS book_id, b.slug AS book_slug, b.title AS book_title,"
    " s.content_rendered AS rendered, s.updated_at AS updated_at"
)
_JOINS = (
    " JOIN chapter_sections s ON s.id = f.rowid"
    " JOIN chapters c ON c.id = s.chapter_id"
    " JOIN books b ON b.id = c.book_id"
)


def search(
    session: Session,
    *,
    query: str,
    book_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, object]], int]:
    """返回 (结果条目, 命中总数)。条目里的 snippet 已可直接渲染。"""
    stripped = (query or "").strip()
    if not stripped:
        return [], 0
    params: dict[str, object] = {
        "published": STATUS_PUBLISHED,
        "public": VISIBILITY_PUBLIC,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    filters = list(_base_conditions())
    if book_id is not None:
        filters.append("c.book_id = :book_id")
        params["book_id"] = book_id

    use_like = needs_like_fallback(stripped) or session.get_bind().dialect.name != "sqlite"
    match_expr = build_match_query(stripped)

    if not use_like and match_expr:
        sql = text(
            f"SELECT {_SELECT_COLUMNS} FROM chapter_fts f{_JOINS}"
            f" WHERE chapter_fts MATCH :match AND {' AND '.join(filters)}"
            " ORDER BY f.rank LIMIT :limit OFFSET :offset"
        )
        params["match"] = match_expr
        rows = session.execute(sql, params).mappings().all()
        count_sql = text(
            f"SELECT COUNT(*) FROM chapter_fts f{_JOINS}"
            f" WHERE chapter_fts MATCH :match AND {' AND '.join(filters)}"
        )
        total = int(session.execute(count_sql, params).scalar_one())
    else:
        pattern = f"%{stripped.replace('%', '').replace('_', '')}%"
        params["pattern"] = pattern
        like_filter = "(s.title LIKE :pattern OR s.content_raw LIKE :pattern)"
        sql = text(
            f"SELECT {_SELECT_COLUMNS}"
            " FROM chapter_sections s"
            " JOIN chapters c ON c.id = s.chapter_id"
            " JOIN books b ON b.id = c.book_id"
            f" WHERE {like_filter} AND {' AND '.join(filters)}"
            " ORDER BY s.updated_at DESC LIMIT :limit OFFSET :offset"
        )
        rows = session.execute(sql, params).mappings().all()
        count_sql = text(
            "SELECT COUNT(*) FROM chapter_sections s"
            " JOIN chapters c ON c.id = s.chapter_id"
            " JOIN books b ON b.id = c.book_id"
            f" WHERE {like_filter} AND {' AND '.join(filters)}"
        )
        total = int(session.execute(count_sql, params).scalar_one())

    from app.services.render import to_plain_text

    items: list[dict[str, object]] = []
    for row in rows:
        plain = to_plain_text(row["rendered"])
        items.append(
            {
                "section_id": int(row["section_id"]),
                "section_slug": row["section_slug"],
                "section_title": row["section_title"],
                "chapter_id": int(row["chapter_id"]),
                "chapter_slug": row["chapter_slug"],
                "chapter_title": row["chapter_title"],
                "book_id": int(row["book_id"]),
                "book_slug": row["book_slug"],
                "book_title": row["book_title"],
                "updated_at": _as_datetime(row["updated_at"]),
                "snippet": make_snippet(plain, stripped),
                "exact": use_like,
            }
        )
    return items, total


def _as_datetime(value: object) -> datetime:
    """原生 SQL 查询在 SQLite 上返回字符串时间，这里统一成 datetime。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min
    return datetime.min
