"""媒体资源服务：类型判定、内容寻址落盘、配额、引用扫描与清理。

设计见 openspec/changes/add-media-library/design.md：
- 物理文件放 `{DATA_DIR}/media/{book_slug}/{hash16}-{safe_name}`，元数据入 `media_assets`；
- 内容寻址使重复上传天然去重，地址可长期缓存；
- 删除是软删除，物理回收只针对「已删除且超过宽限期仍无引用」的资源。
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import NotFound, PayloadTooLarge, QuotaExceeded, UnsupportedMediaType, ValidationFailed
from app.models import (
    MEDIA_ATTACHMENT,
    MEDIA_IMAGE,
    Book,
    Chapter,
    ChapterSection,
    MediaAsset,
    SectionVersion,
    utcnow,
)
from app.services import audit as audit_service

DEFAULT_ALLOWED = "png,jpg,jpeg,gif,webp,svg,avif,bmp,pdf,txt,md,csv,json,log,yaml,yml,zip"
MAX_STEM = 60

# Book slug 由 slug 服务生成，形态固定；媒体目录直接用它做路径段，必须严校验。
_SLUG_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,158}[a-z0-9])?")


@dataclass(frozen=True)
class MediaType:
    kind: str
    mime: str
    signatures: tuple[tuple[int, bytes], ...] = ()
    textual: bool = False


_TYPES: dict[str, MediaType] = {
    "png": MediaType(MEDIA_IMAGE, "image/png", ((0, b"\x89PNG\r\n\x1a\n"),)),
    "jpg": MediaType(MEDIA_IMAGE, "image/jpeg", ((0, b"\xff\xd8\xff"),)),
    "jpeg": MediaType(MEDIA_IMAGE, "image/jpeg", ((0, b"\xff\xd8\xff"),)),
    "gif": MediaType(MEDIA_IMAGE, "image/gif", ((0, b"GIF87a"), (0, b"GIF89a"))),
    "webp": MediaType(MEDIA_IMAGE, "image/webp", ((0, b"RIFF"), (8, b"WEBP"))),
    "avif": MediaType(MEDIA_IMAGE, "image/avif", ((4, b"ftypavif"), (4, b"ftypavis"))),
    "bmp": MediaType(MEDIA_IMAGE, "image/bmp", ((0, b"BM"),)),
    "svg": MediaType(MEDIA_IMAGE, "image/svg+xml", textual=True),
    "pdf": MediaType(MEDIA_ATTACHMENT, "application/pdf", ((0, b"%PDF-"),)),
    "zip": MediaType(MEDIA_ATTACHMENT, "application/zip", ((0, b"PK\x03\x04"),)),
    "txt": MediaType(MEDIA_ATTACHMENT, "text/plain; charset=utf-8", textual=True),
    "md": MediaType(MEDIA_ATTACHMENT, "text/markdown; charset=utf-8", textual=True),
    "csv": MediaType(MEDIA_ATTACHMENT, "text/csv; charset=utf-8", textual=True),
    "json": MediaType(MEDIA_ATTACHMENT, "application/json; charset=utf-8", textual=True),
    "log": MediaType(MEDIA_ATTACHMENT, "text/plain; charset=utf-8", textual=True),
    "yaml": MediaType(MEDIA_ATTACHMENT, "application/yaml; charset=utf-8", textual=True),
    "yml": MediaType(MEDIA_ATTACHMENT, "application/yaml; charset=utf-8", textual=True),
}

# SVG 在站内只作为 <img> 使用，脚本不会执行；但被直接打开时仍有风险，做特征拒绝。
_SVG_DANGER = ("<script", "javascript:", "onload=", "onerror=", "<foreignobject")

_SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")
_DASHES_RE = re.compile(r"-{2,}")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MEDIA_REF_RE = re.compile(r"/media/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)")
_TEXT_ATTR_RE = re.compile(r'(src|href)\s*=\s*"(/media/)', re.IGNORECASE)


# ------------------------------------------------------------------ 类型判定


def extension_of(filename: str) -> str:
    name = (filename or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].strip().lower()


def allowed_set(allowed: str | None = None) -> tuple[str, ...]:
    raw = (allowed or DEFAULT_ALLOWED).replace(",", " ").split()
    return tuple(item.lower().lstrip(".") for item in raw if item)


def _check_textual(ext: str, data: bytes) -> None:
    if b"\x00" in data:
        raise UnsupportedMediaType(f"文件内容与扩展名 .{ext} 不匹配（疑似二进制文件）")
    for encoding in ("utf-8", "gb18030"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if ext == "svg":
            lowered = text.lower()
            if not lowered.lstrip().startswith(("<?xml", "<svg")) and "<svg" not in lowered:
                raise UnsupportedMediaType("这个 .svg 文件里没有找到 <svg> 根元素")
            for token in _SVG_DANGER:
                if token in lowered:
                    raise UnsupportedMediaType(f"SVG 内含可执行内容（{token.strip()}），已拒绝上传")
        return
    raise UnsupportedMediaType(f"无法识别 .{ext} 文件的文本编码（请用 UTF-8 保存后重试）")


def detect_media_type(
    filename: str,
    data: bytes,
    allowed: str | None = None,
) -> MediaType:
    """扩展名白名单 + 内容嗅探，两者必须一致。"""
    ext = extension_of(filename)
    if not ext:
        raise UnsupportedMediaType("文件名缺少扩展名，无法判断类型")
    permit = allowed_set(allowed)
    if ext not in permit:
        raise UnsupportedMediaType(f"不支持的文件类型 .{ext}；允许：{', '.join('.' + item for item in permit)}")
    spec = _TYPES.get(ext)
    if spec is None:
        raise UnsupportedMediaType(f"不支持的文件类型 .{ext}")
    if not data:
        raise ValidationFailed("文件内容为空")
    if spec.textual:
        _check_textual(ext, data)
        return spec
    for offset, signature in spec.signatures:
        if data[offset : offset + len(signature)] == signature:
            return spec
    raise UnsupportedMediaType(f"文件内容与扩展名 .{ext} 不匹配（可能被改过后缀）")


# ------------------------------------------------------------------ 路径


def media_root(settings: Settings) -> Path:
    return Path(settings.data_dir).expanduser().resolve() / "media"


def safe_stem(filename: str) -> str:
    name = (filename or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    stem = _CTRL_RE.sub("", stem)
    stem = _SAFE_STEM_RE.sub("-", stem).strip("-._")
    stem = _DASHES_RE.sub("-", stem)
    if not stem:
        stem = "file"
    return stem[:MAX_STEM]


def safe_name(filename: str) -> str:
    ext = extension_of(filename) or "bin"
    return f"{safe_stem(filename)}.{ext}"


def book_dir(settings: Settings, book_slug: str) -> Path:
    slug = (book_slug or "").strip()
    if not slug or not _SLUG_RE.fullmatch(slug):
        raise ValidationFailed(f"Book slug 非法：{book_slug!r}")
    return media_root(settings) / slug


def storage_path(settings: Settings, book_slug: str, stored_name: str) -> Path:
    """解析存储路径，并保证结果落在媒体根目录内。"""
    root = media_root(settings)
    target = (book_dir(settings, book_slug) / stored_name).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:  # pragma: no cover - 防御性
        raise ValidationFailed("非法的资源路径") from exc
    if target.parent != book_dir(settings, book_slug).resolve():
        raise ValidationFailed("非法的资源路径")
    return target


def media_url(book_slug: str, stored_name: str, root_path: str = "") -> str:
    prefix = (root_path or "").rstrip("/")
    return f"{prefix}/media/{book_slug}/{stored_name}"


def prefix_media_urls(html: str, root_path: str) -> str:
    """把正文里的根相对媒体地址补上部署前缀（渲染输出阶段使用）。"""
    prefix = (root_path or "").rstrip("/")
    if not prefix or not html:
        return html
    return _TEXT_ATTR_RE.sub(lambda m: f'{m.group(1)}="{prefix}{m.group(2)}', html)


# ------------------------------------------------------------------ 读写


def _checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_media(
    session: Session,
    book: Book,
    stored_name: str,
    *,
    include_deleted: bool = False,
) -> MediaAsset | None:
    asset = session.execute(
        select(MediaAsset).where(
            MediaAsset.book_id == book.id, MediaAsset.stored_name == stored_name
        )
    ).scalar_one_or_none()
    if asset is None:
        return None
    if asset.deleted_at is not None and not include_deleted:
        return None
    return asset


def cover_url(session: Session, book: Book, settings: Settings) -> str | None:
    """Book 的封面地址；封面缺失或资源已删时返回 None（页面回退到图标）。"""
    if not book.cover_media_id:
        return None
    asset = session.get(MediaAsset, book.cover_media_id)
    if asset is None or asset.deleted_at is not None or asset.book_id != book.id:
        return None
    return media_url(book.slug, asset.stored_name, settings.root_path)


def find_media_by_id(session: Session, book: Book, media_id: int) -> MediaAsset:
    asset = session.get(MediaAsset, media_id)
    if asset is None or asset.book_id != book.id:
        raise NotFound("资源不存在")
    return asset


def usage(session: Session, book_id: int, settings: Settings) -> dict[str, int]:
    used = session.execute(
        select(func.coalesce(func.sum(MediaAsset.byte_size), 0)).where(
            MediaAsset.book_id == book_id, MediaAsset.deleted_at.is_(None)
        )
    ).scalar_one()
    limit = settings.media_quota_bytes
    return {"used": int(used), "limit": limit, "remaining": max(0, limit - int(used))}


def list_media(session: Session, book_id: int, *, include_deleted: bool = False) -> list[MediaAsset]:
    stmt = select(MediaAsset).where(MediaAsset.book_id == book_id)
    if not include_deleted:
        stmt = stmt.where(MediaAsset.deleted_at.is_(None))
    return list(session.execute(stmt.order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())).scalars())


def save_media(
    session: Session,
    *,
    book: Book,
    filename: str,
    data: bytes,
    settings: Settings,
    actor,
    ip: str = "",
) -> MediaAsset:
    """校验 → 内容寻址落盘 → 幂等复用 → 记审计。"""
    if not data:
        raise ValidationFailed("请选择要上传的文件")
    if len(data) > settings.media_max_bytes:
        limit = settings.media_max_bytes
        human = f"{limit // 1024 // 1024} MiB" if limit >= 1024 * 1024 else f"{limit} 字节"
        raise PayloadTooLarge(f"文件超过单文件上限（{human}）")

    spec = detect_media_type(filename, data, settings.media_allowed_types)
    checksum = _checksum(data)
    name = f"{checksum[:16]}-{safe_name(filename)}"

    existing = session.execute(
        select(MediaAsset).where(MediaAsset.book_id == book.id, MediaAsset.stored_name == name)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.deleted_at is not None:
            existing.deleted_at = None
            audit_service.record(
                session,
                actor=actor,
                action="media.restore",
                target_type="media",
                target_id=existing.id,
                target_label=existing.filename,
                book_id=book.id,
                detail={"stored_name": name},
                ip=ip,
            )
        return existing

    current = usage(session, book.id, settings)
    if current["used"] + len(data) > current["limit"]:
        raise QuotaExceeded(
            f"该 Book 的媒体配额已用尽（已用 {current['used']} 字节，上限 {current['limit']} 字节）；"
            "可先清理未引用资源"
        )

    target = storage_path(settings, book.slug, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        tmp = target.with_name(f".{name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)

    asset = MediaAsset(
        book_id=book.id,
        filename=(filename or name).strip()[:255],
        stored_name=name,
        mime=spec.mime,
        byte_size=len(data),
        checksum=checksum,
        kind=spec.kind,
        created_by=getattr(actor, "id", None),
    )
    session.add(asset)
    session.flush()
    audit_service.record(
        session,
        actor=actor,
        action="media.upload",
        target_type="media",
        target_id=asset.id,
        target_label=asset.filename,
        book_id=book.id,
        detail={"stored_name": name, "mime": spec.mime, "byte_size": asset.byte_size},
        ip=ip,
    )
    return asset


def delete_media(session: Session, *, book: Book, asset: MediaAsset, actor, ip: str = "") -> MediaAsset:
    """软删除（幂等）：物理文件保留，已发布正文因此不会裂图。"""
    if asset.deleted_at is not None:
        audit_service.record(
            session,
            actor=actor,
            action="media.delete",
            target_type="media",
            target_id=asset.id,
            target_label=asset.filename,
            book_id=book.id,
            detail={"stored_name": asset.stored_name, "already_deleted": True},
            ip=ip,
        )
        return asset
    asset.deleted_at = utcnow()
    session.flush()
    audit_service.record(
        session,
        actor=actor,
        action="media.delete",
        target_type="media",
        target_id=asset.id,
        target_label=asset.filename,
        book_id=book.id,
        detail={"stored_name": asset.stored_name},
        ip=ip,
    )
    _unbind_cover(session, book=book, asset=asset, actor=actor, ip=ip)
    return asset


def _unbind_cover(
    session: Session,
    *,
    book: Book,
    asset: MediaAsset,
    actor,
    ip: str,
) -> None:
    """被删的图片若正被用作封面，立刻解绑，避免页面引用一个必然 404 的地址。"""
    if book.cover_media_id != asset.id:
        return
    book.cover_media_id = None
    book.updated_at = utcnow()
    session.flush()
    audit_service.record(
        session,
        actor=actor,
        action="book.cover",
        target_type="book",
        target_id=book.id,
        target_label=book.title,
        book_id=book.id,
        detail={"from": asset.id, "to": None, "unbound": True},
        ip=ip,
    )


# ------------------------------------------------------------------ 引用


def book_bodies(session: Session, book_id: int) -> list[str]:
    """该 Book 全部正文（含草稿、已删除章节/节及其历史版本），用于引用判定。"""
    stmt = (
        select(ChapterSection.content_raw)
        .join(Chapter, Chapter.id == ChapterSection.chapter_id)
        .where(Chapter.book_id == book_id)
    )
    bodies = [row for row in session.execute(stmt).scalars() if row]
    version_stmt = (
        select(SectionVersion.content_raw)
        .join(ChapterSection, ChapterSection.id == SectionVersion.section_id)
        .join(Chapter, Chapter.id == ChapterSection.chapter_id)
        .where(Chapter.book_id == book_id)
    )
    bodies.extend(row for row in session.execute(version_stmt).scalars() if row)
    return bodies


def referenced_names(session: Session, book_id: int) -> set[str]:
    """返回仍被正文引用的 stored_name 集合（文本匹配，误判方向偏向保留文件）。"""
    names = [asset.stored_name for asset in list_media(session, book_id, include_deleted=True)]
    if not names:
        return set()
    bodies = book_bodies(session, book_id)
    if not bodies:
        return set()
    blob = "\n".join(bodies)
    return {name for name in names if name in blob}


def unreferenced(session: Session, book_id: int) -> list[MediaAsset]:
    referenced = referenced_names(session, book_id)
    return [
        asset
        for asset in list_media(session, book_id, include_deleted=True)
        if asset.deleted_at is None and asset.stored_name not in referenced
    ]


def _plan(
    session: Session, book: Book, settings: Settings
) -> tuple[dict[str, object], list[MediaAsset], list[MediaAsset]]:
    referenced = referenced_names(session, book.id)
    candidates = [
        asset
        for asset in list_media(session, book.id, include_deleted=True)
        if asset.stored_name not in referenced
    ]
    to_delete = [asset for asset in candidates if asset.deleted_at is None]
    cutoff = utcnow() - timedelta(days=settings.media_purge_grace_days)
    to_purge = [
        asset
        for asset in candidates
        if asset.deleted_at is not None and asset.deleted_at <= cutoff
    ]
    preview: dict[str, object] = {
        "deleted": [
            {"id": asset.id, "filename": asset.filename, "byte_size": asset.byte_size}
            for asset in to_delete
        ],
        "purged": [
            {"id": asset.id, "filename": asset.filename, "byte_size": asset.byte_size}
            for asset in to_purge
        ],
        "bytes": sum(asset.byte_size for asset in to_delete),
        "purged_bytes": sum(asset.byte_size for asset in to_purge),
    }
    return preview, to_delete, to_purge


def cleanup_plan(session: Session, book: Book, settings: Settings) -> dict[str, object]:
    """只读预览：会被软删的未引用资源 + 会被物理回收的超期已删除资源。"""
    preview, _to_delete, _to_purge = _plan(session, book, settings)
    return preview


def cleanup(
    session: Session,
    *,
    book: Book,
    settings: Settings,
    actor,
    confirm: bool = False,
    ip: str = "",
) -> dict[str, object]:
    """未引用资源清理：默认只预览；确认后软删未引用资源并物理回收超期已删除资源。"""
    preview, to_delete, to_purge = _plan(session, book, settings)
    if not confirm:
        return {"applied": False, **preview}

    for asset in to_delete:
        delete_media(session, book=book, asset=asset, actor=actor, ip=ip)
    for asset in to_purge:
        path = storage_path(settings, book.slug, asset.stored_name)
        try:
            path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - 文件被占用时保留记录，下轮再试
            continue
        session.delete(asset)
    session.flush()
    audit_service.record(
        session,
        actor=actor,
        action="media.cleanup",
        target_type="book",
        target_id=book.id,
        target_label=book.title,
        book_id=book.id,
        detail={"deleted": len(to_delete), "purged": len(to_purge), "bytes": preview["bytes"]},
        ip=ip,
    )
    return {"applied": True, **preview}


def stale_references(session: Session, book: Book) -> list[str]:
    """正文里指向不存在资源的站内媒体地址（例如 Book 改过 slug 之后）。"""
    known = {asset.stored_name for asset in list_media(session, book.id, include_deleted=True)}
    stale: list[str] = []
    for body in book_bodies(session, book.id):
        for match in _MEDIA_REF_RE.finditer(body):
            slug, name = match.group(1), match.group(2)
            if slug != book.slug or name not in known:
                url = match.group(0)
                if url not in stale:
                    stale.append(url)
    return stale
