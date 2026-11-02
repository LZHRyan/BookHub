"""媒体资源的公开读取通道。

不挂 `StaticFiles`：`unlisted` Book、已删除 Book、已软删资源都需要按数据库状态判定，
静态挂载做不到（见 openspec/changes/add-media-library/design.md D2）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import NotFound, Unauthorized
from app.models import VISIBILITY_UNLISTED
from app.services import books as books_service
from app.services import media as media_service
from app.services import tokens as token_service
from app.web.common import current_user, get_settings

router = APIRouter(tags=["media"])

IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


def _has_credential(request: Request, session: Session, book_id: int) -> bool:
    """unlisted Book 的媒体要凭据：登录用户，或**范围覆盖该 Book** 的 API Token。"""
    if current_user(request, session) is not None:
        return True
    header = request.headers.get("authorization", "")
    raw = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not raw:
        return False
    token = token_service.verify_token(session, raw)
    if token is None:
        return False
    scope = token_service.book_scope_of(token)
    return not scope or book_id in scope


@router.get("/media/{book_slug}/{stored_name}", include_in_schema=False)
def read_media(
    request: Request,
    book_slug: str,
    stored_name: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    settings = get_settings(request)
    book = books_service.get_book(session, book_slug)
    asset = media_service.find_media(session, book, stored_name)
    if asset is None:
        raise NotFound("资源不存在")
    if book.visibility == VISIBILITY_UNLISTED and not _has_credential(request, session, book.id):
        raise Unauthorized("该资源所在 Book 未公开列出")

    path = media_service.storage_path(settings, book.slug, asset.stored_name)
    if not path.exists():
        raise NotFound("资源文件不存在")

    headers = {
        "Cache-Control": IMMUTABLE_CACHE,
        "X-Content-Type-Options": "nosniff",
        "Cross-Origin-Resource-Policy": "same-site",
    }
    if asset.mime == "image/svg+xml":
        # SVG 是可以内嵌脚本的“图片”：同源直接打开会执行，必须用 CSP sandbox 关掉
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    if asset.kind == "image":
        return FileResponse(path, media_type=asset.mime, headers=headers)
    headers["Content-Disposition"] = f'attachment; filename="{asset.stored_name}"'
    return FileResponse(path, media_type=asset.mime, filename=asset.filename, headers=headers)
