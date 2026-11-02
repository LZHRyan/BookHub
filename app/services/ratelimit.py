"""进程内滑动窗口限流（单实例部署，无需 Redis）。"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int, max_entries: int = 20_000) -> None:
        self.limit = max(1, limit)
        self.window = max(1, window_seconds)
        # 键只增不减会把内存拖爆（海量 IP / 用户名），超过上限就清扫一遍过期桶
        self.max_entries = max(1, max_entries)
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        self._hits = {
            key: bucket
            for key, bucket in self._hits.items()
            if bucket and now - bucket[-1] < self.window
        }
        if len(self._hits) >= self.max_entries:
            # 全都还在窗口内：按最近命中时间淘汰最旧的一部分，保证有硬上限
            ordered = sorted(self._hits.items(), key=lambda item: item[1][-1])
            for key, _bucket in ordered[: len(self._hits) - self.max_entries + 1]:
                self._hits.pop(key, None)

    def check(self, key: str) -> tuple[bool, int]:
        """返回 (是否允许, 建议的 Retry-After 秒数)。"""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) >= self.max_entries:
                self._prune(now)
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] >= self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, int(self.window - (now - bucket[0])) + 1)
                return False, retry_after
            bucket.append(now)
            return True, 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()
