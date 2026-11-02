"""请求上下文、安全响应头、API Key 与限流中间件。"""

from __future__ import annotations

import ipaddress
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.errors import error_body
from app.logging_setup import log_event
from app.security import safe_compare

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """生成 request_id、记录访问日志，并在响应头回传。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        if not request.url.path.startswith("/static/"):
            log_event(
                "http.request",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                ip=client_ip(request),
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if headers.get("content-type", "").startswith("text/html"):
            headers.setdefault("Content-Security-Policy", CSP_POLICY)
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """请求体大小上限：声明了 `Content-Length` 且超限时直接 413。

    分块传输（chunked）没有 Content-Length，此处放行；那类请求由各上传入口的
    分块读取逐段计数兜底（见 `app/uploads.read_limited`）。
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max(1, int(max_bytes))

    async def dispatch(self, request: Request, call_next) -> Response:
        raw = request.headers.get("content-length", "")
        if raw.isdigit() and int(raw) > self.max_bytes:
            payload = error_body(
                "payload_too_large",
                f"请求体超过上限（{self.max_bytes // 1024 // 1024} MiB）",
                getattr(request.state, "request_id", "-"),
            )
            return JSONResponse(payload, status_code=413)
        return await call_next(request)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """配置了 API_KEY 时，`/api/v1` 下除站点元信息外都要求 X-API-Key。"""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = request.app.state.settings
        path = request.url.path
        exempt = {"/api/v1/site"}
        # /api/v1/admin 用 Bearer Token 自行鉴权，不受公共读 API_KEY 约束
        if path.startswith("/api/v1/admin"):
            return await call_next(request)
        if settings.api_key and path.startswith("/api/v1") and path not in exempt:
            provided = request.headers.get("x-api-key", "")
            if not provided or not safe_compare(provided, settings.api_key):
                payload = error_body(
                    "unauthorized", "缺少或错误的 X-API-Key", getattr(request.state, "request_id", "-")
                )
                return JSONResponse(payload, status_code=401)
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = request.app.state.settings
        path = request.url.path
        if settings.rate_limit_enabled and path.startswith("/api/v1"):
            limiter = request.app.state.limiter
            allowed, retry_after = limiter.check(f"api:{client_ip(request)}")
            if not allowed:
                payload = error_body(
                    "rate_limited",
                    "请求过于频繁，请稍后重试",
                    getattr(request.state, "request_id", "-"),
                )
                return JSONResponse(payload, status_code=429, headers={"Retry-After": str(retry_after)})
        return await call_next(request)


def _is_trusted_proxy(peer: str, trusted: tuple[str, ...]) -> bool:
    """直连 peer 是否在 TRUSTED_PROXIES 里（配置为空表示谁都不信）。"""
    if not trusted:
        return False
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for item in trusted:
        try:
            if address in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str:
    """客户端 IP：只有直连 peer 是可信代理时才采信转发头。

    否则 X-Forwarded-For 可以被任意客户端伪造，限流（尤其登录失败限流）与审计
    IP 都会失真。配置见 TRUSTED_PROXIES。
    """
    client = request.client
    peer = client.host if client else ""
    settings = getattr(request.app.state, "settings", None)
    trusted = tuple(getattr(settings, "trusted_proxies", ()) or ())
    if _is_trusted_proxy(peer, trusted):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
    return peer or "-"
