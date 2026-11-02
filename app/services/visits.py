"""访客访问计数：进程内去重 + 写入每日聚合表（粒度到节）。

计数只服务首页排序权重，因此刻意做得"轻且静默"：
- 同一访客（按 IP 识别）对同一 Book 在窗口内只计一次，避免刷新刷热度；
  一次访问记到当时读到的那一节上，Book 的热度由各节之和聚合。
- 去重把写入量压到「每个 IP × 每本书 × 每 30 分钟最多一次」，所以读页面的
  写放大上限取决于独立访客数而不是 PV；这个量级下不必再引入异步批量写
  （异步会带来崩溃丢计数与多 worker 不一致，收益不值）。
- 任何写库错误都被吞掉并记日志，绝不让阅读页因为统计失败而报错。
"""

from __future__ import annotations

import threading
import time

from sqlalchemy.orm import Session
from starlette.requests import Request

from app.logging_setup import log_event
from app.middleware import client_ip
from app.services.ranking import add_view

# 同一访客对同一 Book 的去重窗口
VISIT_DEDUPE_SECONDS = 30 * 60
# 进程内最多记住多少条去重键，超过就清理过期项
MAX_TRACKED_VISITS = 20_000


class VisitDeduper:
    """滑动窗口去重：窗口内同一 key 只放行一次。"""

    def __init__(
        self,
        window_seconds: int = VISIT_DEDUPE_SECONDS,
        max_entries: int = MAX_TRACKED_VISITS,
    ) -> None:
        self.window = max(1, window_seconds)
        self.max_entries = max(1, max_entries)
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def should_count(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._seen) >= self.max_entries:
                self._seen = {
                    item: stamp for item, stamp in self._seen.items() if now - stamp < self.window
                }
            last = self._seen.get(key)
            if last is not None and now - last < self.window:
                return False
            self._seen[key] = now
            return True

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


def visit_key(book_id: int, ip: str) -> str:
    return f"{book_id}:{ip}"


def record_section_view(
    request: Request, session: Session, *, book_id: int, section_id: int
) -> bool:
    """记一次「读了这本书的某一节」；返回是否真的计入（去重或写库失败为 False）。"""
    if request.method != "GET":
        return False
    deduper = getattr(request.app.state, "visit_deduper", None)
    key = visit_key(book_id, client_ip(request))
    if deduper is not None and not deduper.should_count(key):
        return False
    try:
        add_view(session, section_id)
        session.commit()
    except Exception as exc:  # pragma: no cover - 统计失败不能影响阅读
        session.rollback()
        log_event("visit.record.error", book_id=book_id, section_id=section_id, error=str(exc))
        return False
    return True
