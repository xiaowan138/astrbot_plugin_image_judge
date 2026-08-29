"""群管理子指令解析（鉴图开启/关闭/概率/状态/榜）。

指令是关键词触发的前缀子集（如“鉴图开启”本身含触发词“鉴图”），
在 main 里先于普通触发解析，避免同一条消息被当成普通鉴图指令。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SIMPLE_RE = re.compile(r"鉴图(开启|关闭|状态)")
_PROBABILITY_RE = re.compile(r"鉴图概率(?:\s*(\S+))?")
_BOARD_RE = re.compile(r"鉴图榜(?:\s*(\S+))?")

#: “鉴图榜”的时间范围词 -> 内部标识（today / week / all）。
_BOARD_SCOPES = {
    "": "today",
    "今日": "today",
    "今天": "today",
    "周": "week",
    "本周": "week",
    "近一周": "week",
    "总": "all",
    "全部": "all",
    "历史": "all",
}

_BOARD_SCOPES_VALID = ("today", "week", "all")


@dataclass(frozen=True, slots=True)
class AdminCommand:
    action: str  # 开启 / 关闭 / 状态 / 概率 / 榜
    value: int | None = None  # 仅“概率”有值；None 表示缺参数（提示用法）
    invalid: bool = False  # “概率”参数存在但不是数字（提示用法）
    scope: str = ""  # 仅“榜”有值：today / week / all；空串表示今日


def is_valid_board_scope(scope: str) -> bool:
    return scope in _BOARD_SCOPES_VALID


def parse_admin_command(text: str) -> AdminCommand | None:
    """从消息文本解析群管理指令；不匹配返回 None。"""
    value = (text or "").strip()
    if not value.startswith("鉴图"):
        return None
    match = _SIMPLE_RE.fullmatch(value)
    if match:
        return AdminCommand(match.group(1))
    match = _PROBABILITY_RE.fullmatch(value)
    if match:
        raw = match.group(1)
        if raw is None:
            return AdminCommand("概率")
        try:
            return AdminCommand("概率", int(raw))
        except ValueError:
            # “鉴图概率 abc”此前会回退成普通鉴图触发，体验差；整体拦下给用法提示。
            return AdminCommand("概率", invalid=True)
    match = _BOARD_RE.fullmatch(value)
    if match:
        raw = match.group(1) or ""
        return AdminCommand("榜", scope=_BOARD_SCOPES.get(raw, raw))
    return None
