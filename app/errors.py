"""统一的应用异常与错误响应结构。"""

from __future__ import annotations

from starlette.requests import Request


class AppError(Exception):
    """业务异常：状态码 + 机器可读 code + 人类可读 message（可选响应头）。"""

    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.headers = headers or {}
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class NotFound(AppError):
    status_code = 404
    code = "not_found"

    def __init__(self, message: str = "资源不存在"):
        super().__init__(message)


class ValidationFailed(AppError):
    status_code = 400
    code = "validation_error"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "file_too_large"


class UnsupportedMediaType(AppError):
    """媒体类型不在白名单内，或扩展名与内容不一致。"""

    status_code = 415
    code = "unsupported_media_type"


class QuotaExceeded(AppError):
    """超出每 Book 的媒体配额。"""

    status_code = 413
    code = "quota_exceeded"


class ContentTooLong(AppError):
    status_code = 422
    code = "content_too_long"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


def error_body(code: str, message: str, request_id: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "-")
