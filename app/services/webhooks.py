"""Webhook 服务：登记、签名、投递与重试。

设计见 openspec/changes/add-integrations/design.md，本轮改为「先落库、提交后投递」：
- `dispatch()` 只在事务里写待投递记录，不发网络请求；
- 事务提交后由 `app.db` 的监听器把记录 id 交给后台线程（`EXECUTOR`），
  用独立会话真正发送，失败只落库 + 日志，绝不让内容保存回滚、也不占着写锁；
- 签名 = HMAC-SHA256(secret, 原始请求体)，头为 `X-BookHub-Signature: sha256=<hex>`；
- 每次尝试写一条 `webhook_deliveries`，失败可在管理 API 里重试。
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFound, ValidationFailed
from app.models import Webhook, WebhookDelivery, utcnow
from app.services import audit as audit_service

EVENTS = (
    "chapter.published",
    "chapter.unpublished",
    "chapter.updated",
    "section.published",
    "section.updated",
    "book.created",
    "book.deleted",
)
TIMEOUT_SECONDS = 5
MAX_EVENTS = 8
# 后台投递线程数：投递是纯 I/O 等待，2 个线程足够；同一 hook 的顺序不保证，
# 接收方应按 occurred_at 而不是到达顺序处理。
DELIVERY_WORKERS = 2


class _ThreadExecutor:
    """默认执行器：提交到后台线程，绝不在请求线程里等网络。"""

    def __init__(self, workers: int = DELIVERY_WORKERS) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="webhook")

    def submit(self, fn, *args) -> None:  # type: ignore[no-untyped-def]
        self._pool.submit(fn, *args)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class InlineExecutor:
    """同步执行器（测试用）：提交即执行，断言可以直接读结果。"""

    def submit(self, fn, *args) -> None:  # type: ignore[no-untyped-def]
        fn(*args)

    def shutdown(self) -> None:
        return


EXECUTOR: _ThreadExecutor | InlineExecutor = _ThreadExecutor()


def use_executor(executor: _ThreadExecutor | InlineExecutor) -> None:
    """替换投递执行器（测试把它换成同步实现）。"""
    global EXECUTOR
    EXECUTOR = executor


@dataclass(frozen=True)
class DeliveryResult:
    status_code: int | None
    error: str

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300


def normalize_events(events: list[str] | tuple[str, ...] | str) -> list[str]:
    if isinstance(events, str):
        items = [part.strip() for part in events.replace(" ", ",").split(",") if part.strip()]
    else:
        items = [str(part).strip() for part in events if str(part).strip()]
    unknown = [item for item in items if item not in EVENTS]
    if unknown:
        raise ValidationFailed(f"未知事件：{', '.join(unknown)}；可选：{', '.join(EVENTS)}")
    if not items:
        raise ValidationFailed("至少订阅一个事件")
    if len(items) > MAX_EVENTS:
        raise ValidationFailed(f"事件数量不能超过 {MAX_EVENTS}")
    return sorted(set(items))


def _is_forbidden_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """回调目标不能是内网/本机/链路本地等内部地址（防 SSRF）。"""
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _resolved_addresses(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return {ipaddress.ip_address(info[4][0]) for info in infos}


def validate_url(url: str) -> str:
    """登记时做静态校验：协议、主机形态、字面量内网地址。

    域名是否解析到内网在投递时再查（见 `_post`），避免登记时做 DNS 依赖。
    """
    candidate = (url or "").strip()
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationFailed("回调地址必须是 http(s) 绝对 URL")
    if parsed.username or parsed.password:
        raise ValidationFailed("回调地址不能带用户名/密码")
    host = (parsed.hostname or "").strip()
    if not host:
        raise ValidationFailed("回调地址缺少主机名")
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        raise ValidationFailed("回调地址不能指向本机（localhost）")
    address = _literal_ip(host)
    if address is not None and _is_forbidden_ip(address):
        raise ValidationFailed("回调地址不能指向内网/本机地址")
    return candidate


def events_of(hook: Webhook) -> list[str]:
    return [part for part in (hook.events or "").split(",") if part]


def create(
    session: Session,
    *,
    url: str,
    events,
    description: str = "",
    created_by: int | None = None,
    actor=None,
    ip: str = "",
) -> tuple[Webhook, str]:
    hook = Webhook(
        url=validate_url(url),
        secret=secrets.token_urlsafe(24),
        events=",".join(normalize_events(events)),
        description=(description or "").strip()[:200],
        created_by=created_by,
    )
    session.add(hook)
    session.flush()
    audit_service.record(
        session,
        actor=actor,
        action="webhook.create",
        target_type="webhook",
        target_id=hook.id,
        target_label=hook.url,
        detail={"events": events_of(hook)},
        ip=ip,
    )
    return hook, hook.secret


def list_hooks(session: Session) -> list[Webhook]:
    return list(session.execute(select(Webhook).order_by(Webhook.id.desc())).scalars())


def get_hook(session: Session, hook_id: int) -> Webhook:
    hook = session.get(Webhook, int(hook_id))
    if hook is None:
        raise NotFound("Webhook 不存在")
    return hook


def deactivate(session: Session, hook: Webhook, *, actor=None, ip: str = "") -> Webhook:
    hook.is_active = False
    session.flush()
    audit_service.record(
        session,
        actor=actor,
        action="webhook.delete",
        target_type="webhook",
        target_id=hook.id,
        target_label=hook.url,
        ip=ip,
    )
    return hook


def sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _post(url: str, body: bytes, headers: dict[str, str]) -> DeliveryResult:
    """真正发请求；测试里替换这个函数即可。

    投递前解析主机并拒绝内网地址：域名可以登记后才把 A 记录改到内网（DNS rebinding）。
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = _resolved_addresses(host, port)
    except OSError as exc:
        return DeliveryResult(status_code=None, error=f"回调地址无法解析：{exc}"[:300])
    if not addresses or any(_is_forbidden_ip(item) for item in addresses):
        return DeliveryResult(status_code=None, error="回调地址解析到内网/本机，已拒绝投递")
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            return DeliveryResult(status_code=response.status, error="")
    except urllib.error.HTTPError as exc:
        return DeliveryResult(status_code=exc.code, error=f"HTTP {exc.code}")
    except Exception as exc:  # 连接失败、超时、DNS 等
        return DeliveryResult(status_code=None, error=str(exc)[:300])


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _send(hook: Webhook, event: str, payload_json: str) -> DeliveryResult:
    body = payload_json.encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-BookHub-Event": event,
        "X-BookHub-Signature": sign(hook.secret, body),
        "User-Agent": "BookHub-Webhook/1.0",
    }
    return _post(hook.url, body, headers)


def send_now(session: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    """立刻发送一条刚登记的投递（管理端的「测试」按钮用）。

    会把它从待投递队列里摘掉，避免 commit 之后后台线程再发一次。
    """
    from app.db import WEBHOOK_PENDING_KEY

    pending = session.info.get(WEBHOOK_PENDING_KEY)
    if pending and delivery.id in pending:
        pending.remove(delivery.id)
    hook = get_hook(session, delivery.webhook_id)
    result = _send(hook, delivery.event, delivery.payload)
    _apply(hook, delivery, result)
    session.flush()
    return delivery


def dispatch(
    session: Session,
    event: str,
    payload: dict[str, object],
    *,
    hooks: list[Webhook] | None = None,
) -> list[WebhookDelivery]:
    """把事件登记成待投递记录；真正的 HTTP 请求在 commit 之后由后台线程做。

    任何失败都只影响投递记录，不抛错、不回滚内容写入，也不在写事务里等网络。
    """
    body = json.dumps({"event": event, "occurred_at": utcnow().isoformat(), **payload}, ensure_ascii=False)
    explicit = hooks is not None
    candidates = hooks if explicit else list_hooks(session)
    created: list[WebhookDelivery] = []
    for hook in candidates:
        if not hook.is_active:
            continue
        # 显式指定 hook（测试投递/重试）时不再按订阅事件过滤
        if not explicit and event not in events_of(hook):
            continue
        delivery = WebhookDelivery(webhook_id=hook.id, event=event, payload=body)
        session.add(delivery)
        session.flush()
        created.append(delivery)
    if created:
        from app.db import WEBHOOK_PENDING_KEY

        session.info.setdefault(WEBHOOK_PENDING_KEY, []).extend(item.id for item in created)
    return created


def deliver_pending(factory, delivery_ids: list[int]) -> None:
    """在独立会话里发送已提交的待投递记录；任何异常都只记日志。

    由 `app.db` 的 after_commit 监听器投递到 `EXECUTOR`，因此这里绝不能抛错，
    也不能依赖请求上下文（request / session）。
    """
    from app.logging_setup import log_event

    try:
        with factory() as session:
            for delivery_id in delivery_ids:
                delivery = session.get(WebhookDelivery, delivery_id)
                if delivery is None or delivery.status_code is not None or delivery.delivered_at:
                    continue
                hook = session.get(Webhook, delivery.webhook_id)
                if hook is None:
                    delivery.error = "Webhook 不存在"
                    continue
                if not hook.is_active:
                    delivery.error = "Webhook 已停用，未投递"
                    continue
                result = _send(hook, delivery.event, delivery.payload)
                _apply(hook, delivery, result)
            session.commit()
    except Exception as exc:  # pragma: no cover - 后台线程兜底
        log_event("webhook.deliver.error", error=str(exc)[:300], count=len(delivery_ids))


def _apply(hook: Webhook, delivery: WebhookDelivery, result: DeliveryResult) -> None:
    delivery.status_code = result.status_code
    delivery.error = result.error[:300]
    delivery.delivered_at = utcnow() if result.ok else None
    hook.last_status = result.status_code
    hook.last_error = result.error[:300]
    hook.last_sent_at = utcnow()


def deliver_now(session: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    """重新投递一条已有记录（手动重试）。"""
    hook = get_hook(session, delivery.webhook_id)
    if not hook.is_active:
        raise ValidationFailed("该 Webhook 已停用，不能重试")
    result = _send(hook, delivery.event, delivery.payload)
    delivery.attempts += 1
    _apply(hook, delivery, result)
    session.flush()
    return delivery


def list_deliveries(session: Session, hook_id: int, *, limit: int = 20) -> list[WebhookDelivery]:
    return list(
        session.execute(
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == hook_id)
            .order_by(WebhookDelivery.id.desc())
            .limit(limit)
        ).scalars()
    )


def get_delivery(session: Session, delivery_id: int) -> WebhookDelivery:
    delivery = session.get(WebhookDelivery, int(delivery_id))
    if delivery is None:
        raise NotFound("投递记录不存在")
    return delivery


def detail_of(hook: Webhook) -> dict[str, object]:
    return {
        "id": hook.id,
        "url": hook.url,
        "events": events_of(hook),
        "active": hook.is_active,
        "description": hook.description,
        "last_status": hook.last_status,
        "last_error": hook.last_error,
        "last_sent_at": hook.last_sent_at,
        "created_at": hook.created_at,
    }
