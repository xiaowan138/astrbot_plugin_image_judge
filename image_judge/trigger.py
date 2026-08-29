"""关键词触发意图判定。

触发词用子串匹配，而“评价 / 点评”这类词在中文聊天里非常常见（如
“帮我评价一下这个方案”）。误触发不仅打扰群聊，还会 stop_event 拦截
主 agent 对这条消息的处理，因此无图片上下文时要求消息基本就是一条指令。
"""

from __future__ import annotations

import re

#: 去掉指令词后允许残留的最大字符数（不含空白），超过视为普通聊天。
MAX_RESIDUAL_CHARS = 4


def strip_command_words(
    text: str,
    keywords_re: re.Pattern,
    style_re: re.Pattern,
    theme_re: re.Pattern,
) -> str:
    """去掉触发词、风格词、主题词与空白后剩下的文本。"""
    residual = keywords_re.sub("", text or "")
    residual = style_re.sub("", residual)
    residual = theme_re.sub("", residual)
    return re.sub(r"\s+", "", residual)


def is_command_like(
    text: str,
    keywords_re: re.Pattern,
    style_re: re.Pattern,
    theme_re: re.Pattern,
    *,
    max_residual_chars: int = MAX_RESIDUAL_CHARS,
) -> bool:
    """无图片上下文时，消息是否仍应视为一条鉴图指令。

    “打分”“打分 毒舌”“锐评吧”这类基本只剩指令词的消息算指令（回复用法
    提示）；“帮我评价一下这个方案”残留“帮我一下这个方案”，不算，应放行
    给主流程处理。空消息不算指令。
    """
    if not (text or "").strip():
        return False
    residual = strip_command_words(text, keywords_re, style_re, theme_re)
    return len(residual) <= max_residual_chars
