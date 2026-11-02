"""ORM 模型：用户、Book、章、节、版本、审计、站点设置。"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLES = (ROLE_ADMIN, ROLE_EDITOR)

VISIBILITY_PUBLIC = "public"
VISIBILITY_UNLISTED = "unlisted"
VISIBILITIES = (VISIBILITY_PUBLIC, VISIBILITY_UNLISTED)

FORMAT_MARKDOWN = "markdown"
FORMAT_HTML = "html"
FORMATS = (FORMAT_MARKDOWN, FORMAT_HTML)

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED)

# 章默认节（迁移后每章都有一条，旧链接 `/b/<book>/<chapter>` 直出它）
DEFAULT_SECTION_SLUG = "main"

# HTML Book 的阅读方式：站内净化渲染，还是把上传的原文档放到新标签页里原样运行
HTML_VIEW_INLINE = "inline"
HTML_VIEW_DOCUMENT = "document"
HTML_VIEWS = (HTML_VIEW_INLINE, HTML_VIEW_DOCUMENT)

# 媒体资源类别：图片在正文里内联展示，附件按原文件名下载
MEDIA_IMAGE = "image"
MEDIA_ATTACHMENT = "attachment"
MEDIA_KINDS = (MEDIA_IMAGE, MEDIA_ATTACHMENT)


def utcnow() -> datetime:
    """统一的 UTC 时间源（不带时区信息，库里按 UTC 存储）。"""
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_EDITOR, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    session_epoch: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


class BookGroup(Base):
    """Book 的分组：决定首页分区与顺序；每本 Book 必属于一个组。"""

    __tablename__ = "book_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    icon: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        Index(
            "uq_books_slug_active",
            "slug",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_books_listing", "deleted_at", "visibility"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("book_groups.id"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    icon: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    format: Mapped[str] = mapped_column(String(16), default=FORMAT_MARKDOWN, nullable=False)
    html_view: Mapped[str] = mapped_column(String(16), default=HTML_VIEW_INLINE, nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), default=VISIBILITY_PUBLIC, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 内置指南：系统在启动时幂等创建，随系统生命周期存在。整本不可删除、
    # 访问标识与文档类型锁定（见 app/services/builtin.py）。
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cover_media_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    chapters: Mapped[list[Chapter]] = relationship(back_populates="book")


class Chapter(Base):
    """目录里的一章：只保存标题、序号与发布状态，正文都在 ChapterSection 里。"""

    __tablename__ = "chapters"
    __table_args__ = (
        Index(
            "uq_chapters_book_slug_active",
            "book_id",
            "slug",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_chapters_order", "book_id", "deleted_at", "sort_order"),
        Index("ix_chapters_changes", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_DRAFT, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    book: Mapped[Book] = relationship(back_populates="chapters")
    sections: Mapped[list[ChapterSection]] = relationship(
        back_populates="chapter", order_by="ChapterSection.sort_order"
    )


class ChapterSection(Base):
    """章下面的一节：一份文件（Markdown 或 HTML）以及它的正文与版本号。"""

    __tablename__ = "chapter_sections"
    __table_args__ = (
        Index(
            "uq_chapter_sections_slug_active",
            "chapter_id",
            "slug",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_chapter_sections_order", "chapter_id", "deleted_at", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    format: Mapped[str] = mapped_column(String(16), default=FORMAT_MARKDOWN, nullable=False)
    content_raw: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_safe: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_rendered: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_toc: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    content_checksum: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    chapter: Mapped[Chapter] = relationship(back_populates="sections")


class SectionVersion(Base):
    """节的版本快照：每节各自递增，互不影响。"""

    __tablename__ = "section_versions"
    __table_args__ = (UniqueConstraint("section_id", "version_no", name="uq_section_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("chapter_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    format: Mapped[str] = mapped_column(String(16), default=FORMAT_MARKDOWN, nullable=False)
    content_raw: Mapped[str] = mapped_column(Text, default="", nullable=False)
    note: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SectionViewDaily(Base):
    """节的每日访问计数：Book 热度按其各节之和聚合。

    计数粒度到节，是因为「哪一节真的被读了」比「Book 被打开了」更有信息量；
    Book 页（目录）本身不再计数。
    """

    __tablename__ = "section_view_daily"
    __table_args__ = (Index("ix_section_view_daily_day", "day"),)

    section_id: Mapped[int] = mapped_column(
        ForeignKey("chapter_sections.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class MediaAsset(Base):
    """Book 名下的图片与附件：物理文件以内容寻址存放在 DATA_DIR/media 下。"""

    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("book_id", "stored_name", name="uq_media_book_stored"),
        Index("ix_media_book_active", "book_id", "deleted_at"),
        Index("ix_media_checksum", "book_id", "checksum"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    stored_name: Mapped[str] = mapped_column(String(200), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default=MEDIA_ATTACHMENT, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_label: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    book_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    detail: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SiteSetting(Base):
    __tablename__ = "site_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ApiToken(Base):
    """程序化凭据。只存哈希，明文仅在创建时返回一次。"""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    prefix: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    scopes: Mapped[str] = mapped_column(String(64), default="read", nullable=False)
    # 限定的 Book id（逗号分隔）；空字符串表示全部 Book
    book_scope: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Webhook(Base):
    """外部回调登记：内容变更时向其 URL 推送签名 JSON。"""

    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    events: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WebhookDelivery(Base):
    """一次投递尝试的结果，用于排查与重试。"""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (Index("ix_webhook_deliveries_hook", "webhook_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    webhook_id: Mapped[int] = mapped_column(
        ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IdempotencyKey(Base):
    """写接口的幂等键：同键同指纹重放首次结果。"""

    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("ix_idempotency_expires", "expires_at"),)

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    token_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
