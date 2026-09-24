"""按用户冷却与每日限额（纯内存，有界）。

冷却遵循"成功才计时"：只有真正调用模型成功后才开始计时，
失败/超时不会消耗冷却与配额。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import date


class UserCooldown:
    def __init__(self, window_seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.window_seconds = max(float(window_seconds), 0.0)
        self._clock = clock
        self._marks: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def is_ok(self, key: str) -> bool:
        """是否已过冷却；不消耗额度。"""
        if self.window_seconds <= 0:
            return True
        now = self._clock()
        async with self._lock:
            last = self._marks.get(key)
            if last is not None and now - last < self.window_seconds:
                return False
            self._prune(now)
            return True

    async def mark(self, key: str) -> None:
        """记录一次成功调用，开始计时冷却。"""
        if self.window_seconds <= 0:
            return
        now = self._clock()
        async with self._lock:
            self._marks[key] = now
            self._prune(now)

    def _prune(self, now: float) -> None:
        if len(self._marks) <= 2048:
            return
        cutoff = now - self.window_seconds
        self._marks = {key: ts for key, ts in self._marks.items() if ts >= cutoff}
        while len(self._marks) > 2048:
            oldest = min(self._marks, key=self._marks.get)
            self._marks.pop(oldest, None)


class HourlyCap:
    """滑动窗口次数上限（群级自动触发防刷屏用）。

    与 ``UserCooldown`` 一样区分 ``is_ok``（只判断）与 ``mark``（计数），
    这样取图失败时不会白白占掉配额。
    """

    def __init__(
        self,
        limit: int,
        *,
        window_seconds: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = max(int(limit), 0)
        self.window_seconds = max(float(window_seconds), 1.0)
        self._clock = clock
        self._marks: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self.limit > 0

    async def is_ok(self, key: str) -> bool:
        """窗口内是否还有余量；不消耗配额。"""
        if not self.enabled:
            return True
        now = self._clock()
        async with self._lock:
            recent = self._recent(key, now)
            self._marks[key] = recent
            return len(recent) < self.limit

    async def mark(self, key: str) -> None:
        now = self._clock()
        if not self.enabled:
            return
        async with self._lock:
            recent = self._recent(key, now)
            recent.append(now)
            self._marks[key] = recent
            self._prune(now)

    def _recent(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        return [ts for ts in self._marks.get(key, []) if ts > cutoff]

    def _prune(self, now: float) -> None:
        if len(self._marks) <= 1024:
            return
        self._marks = {key: self._recent(key, now) for key in self._marks}
        while len(self._marks) > 1024:
            oldest = min(
                self._marks, key=lambda key: max(self._marks[key], default=0.0)
            )
            self._marks.pop(oldest, None)


class DailyQuota:
    def __init__(self, limit: int) -> None:
        self.limit = max(int(limit), 0)
        self._counts: dict[str, tuple[str, int]] = {}
        self._lock = asyncio.Lock()

    async def can_use(self, key: str, day: str | None = None) -> bool:
        if self.limit <= 0:
            return True
        today = day or date.today().isoformat()
        async with self._lock:
            stored_day, count = self._counts.get(key, ("", 0))
            if stored_day != today:
                return True
            return count < self.limit

    async def consume(self, key: str, day: str | None = None) -> None:
        """成功调用后计数；同一天内累加，跨天重置。"""
        if self.limit <= 0:
            return
        today = day or date.today().isoformat()
        async with self._lock:
            stored_day, count = self._counts.get(key, ("", 0))
            self._counts[key] = (today, count + 1 if stored_day == today else 1)
            if len(self._counts) > 2048:
                self._counts = dict(
                    sorted(self._counts.items(), key=lambda item: item[1][0])[-2048:]
                )
