"""鉴图结果缓存：同一张图在有效期内重复鉴图直接复用模型输出。

群友常把同一张图反复丢出来打分，每次都调模型很浪费额度。key 取「归一化后
的图片内容 + 风格」，同一张图（哪怕 URL 带不同的过期参数）归一化后的
data URL 一致，因此能命中。纯内存、有界，插件重载即清空。
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable


def cache_key(data_url: str, style: str) -> str:
    digest = hashlib.sha256()
    digest.update(style.encode("utf-8"))
    digest.update(b"\x1f")
    digest.update((data_url or "").encode("utf-8"))
    return digest.hexdigest()


class ResultCache:
    def __init__(
        self,
        ttl_seconds: float,
        *,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = max(float(ttl_seconds), 0.0)
        self._max_entries = max(int(max_entries), 1)
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, str]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, value = item
        if self._clock() >= expires_at:
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return value

    def put(self, key: str, value: str) -> None:
        if not self.enabled or not (value or "").strip():
            return
        self._items[key] = (self._clock() + self.ttl_seconds, value)
        self._items.move_to_end(key)
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)
