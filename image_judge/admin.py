"""群管理子指令解析（鉴图开启/关闭/概率/状态/榜/我的）。

指令是关键词触发的前缀子集（如“鉴图开启”本身含触发词“鉴图”），
在 main 里先于普通触发解析，避免同一条消息被当成普通鉴图指令。

中文输入法习惯在词间加空格（“鉴图 开启”），所以词与词之间一律允许空白。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SIMPLE_RE = re.compile(r"鉴图\s*(开启|关闭|状态)")
_PROBABILITY_RE = re.compile(r"鉴图\s*概率(?:\s*(\S+))?")
_BOARD_RE = re.compile(r"鉴图\s*榜(.*)", re.S)
_MINE_RE = re.compile(r"我的\s*(?:鉴图|战绩|鉴定)(.*)", re.S)

#: @提及：部分平台会把被 @ 的人渲染进 message_str，解析范围词前要先剔掉。
_MENTION_RE = re.compile(r"@\S+")

#: “鉴图榜”的时间范围词 -> 内部标识（today / week / all）。
_BOARD_SCOPES = {
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
    action: str  # 开启 / 关闭 / 状态 / 概率 / 榜 / 我的
    value: int | None = None  # 仅“概率”有值；None 表示缺参数（提示用法）
    invalid: bool = False  # “概率”参数存在但不是数字（提示用法）
    scope: str = ""  # 仅“榜”“我的”有值：today / week / all；空串表示无法识别


def is_valid_board_scope(scope: str) -> bool:
    return scope in _BOARD_SCOPES_VALID


def _board_scope(remainder: str) -> str:
    """从指令尾部文本提取时间范围；未指定默认今日，无法识别返回空串。

    带 @ 提及的查询（“鉴图榜 @张三 本周”）先剔掉 @ 部分，再判断剩余文本；
    平台把 @ 渲染成不带 @ 的昵称时剩余文本无法识别，由调用方回退到今日。
    """
    text = _MENTION_RE.sub(" ", remainder or "").strip()
    if not text:
        return "today"
    return _BOARD_SCOPES.get(text, "")


def parse_admin_command(text: str) -> AdminCommand | None:
    """从消息文本解析群管理指令；不匹配返回 None。"""
    value = (text or "").strip()
    if not value.startswith("鉴图") and not value.startswith("我的"):
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
        return AdminCommand("榜", scope=_board_scope(match.group(1)))
    match = _MINE_RE.fullmatch(value)
    if match:
        return AdminCommand("我的", scope=_board_scope(match.group(1)))
    return None
