"""自动触发免打扰时段。

配置形如 ``23:00-08:00``，起止时间倒置表示跨零点的夜间时段。只影响自动
触发；关键词触发是用户主动发起，任何时段都照常响应。
"""

from __future__ import annotations

import re
from datetime import datetime

_RANGE_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")


def parse_quiet_hours(spec: str) -> tuple[int, int] | None:
    """把 "23:00-08:00" 解析成 (起始分钟, 结束分钟)；留空或格式无效返回 None。"""
    match = _RANGE_RE.match((spec or "").strip())
    if not match:
        return None
    start_hour, start_minute, end_hour, end_minute = (
        int(part) for part in match.groups()
    )
    if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
        return None
    return start_hour * 60 + start_minute, end_hour * 60 + end_minute


def is_quiet_now(spec: str, *, now: datetime | None = None) -> bool:
    """当前是否处于免打扰时段；配置留空或无效一律视为不启用。"""
    window = parse_quiet_hours(spec)
    if window is None:
        return False
    start, end = window
    if start == end:
        # 起止相同视为不启用，否则会整天静默。
        return False
    current = now or datetime.now()
    minute = current.hour * 60 + current.minute
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end
