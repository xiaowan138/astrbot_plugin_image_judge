"""群管理子指令解析（鉴图开启/关闭/概率/状态）。

指令是关键词触发的前缀子集（如“鉴图开启”本身含触发词“鉴图”），
在 main 里先于普通触发解析，避免同一条消息被当成普通鉴图指令。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SIMPLE_RE = re.compile(r"鉴图(开启|关闭|状态)")
_PROBABILITY_RE = re.compile(r"鉴图概率(?:\s+(\d{1,3}))?")


@dataclass(frozen=True, slots=True)
class AdminCommand:
    action: str  # 开启 / 关闭 / 状态 / 概率
    value: int | None  # 仅“概率”有值；None 表示缺参数（提示用法）


def parse_admin_command(text: str) -> AdminCommand | None:
    """从消息文本解析群管理指令；不匹配返回 None。"""
    value = (text or "").strip()
    if not value.startswith("鉴图"):
        return None
    match = _SIMPLE_RE.fullmatch(value)
    if match:
        return AdminCommand(match.group(1), None)
    match = _PROBABILITY_RE.fullmatch(value)
    if match:
        raw = match.group(1)
        return AdminCommand("概率", int(raw) if raw is not None else None)
    return None
