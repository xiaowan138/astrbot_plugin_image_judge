"""评分结果渲染：文本输出与评分卡片上下文。"""

from __future__ import annotations

import html
from typing import Any

from .judge import Judgement

#: 评分卡片视觉主题：中文名 -> 模板 body class。
THEME_ALIASES = {
    "霓虹": "neon",
    "极简": "minimal",
    "复古": "retro",
    "赛博朋克": "cyber",
    "马卡龙": "macaron",
}

DEFAULT_THEME = "neon"


def resolve_theme(name: str) -> str:
    return THEME_ALIASES.get((name or "").strip(), DEFAULT_THEME)


def stars(score: int) -> str:
    score = max(0, min(score, 100))
    # 每 20 分一星；(score + 10) // 20 让 90 分以上得满星，避免 round 的银行家舍入。
    full = (score + 10) // 20
    return "★" * full + "☆" * (5 - full)


def score_color(score: int) -> str:
    """按分数段给出卡片主题色，方便模板直接使用。"""
    if score >= 80:
        return "#ffd54f"  # 金
    if score >= 60:
        return "#ff8a65"  # 橙
    return "#ff5252"  # 红


def build_text_result(judgement: Judgement, style_name: str) -> str:
    lines = []
    if judgement.score is not None:
        lines.append(
            f"鉴图结果（{style_name}）：{judgement.score}/100 分 {stars(judgement.score)}"
        )
    if judgement.reason:
        lines.append(f"理由：{judgement.reason}")
    if judgement.roast:
        lines.append(f"吐槽：{judgement.roast}")
    return "\n".join(lines)


def build_card_context(
    judgement: Judgement,
    style_name: str,
    *,
    image_src: str = "",
    theme: str = DEFAULT_THEME,
) -> dict[str, Any]:
    score = judgement.score if judgement.score is not None else 0
    # 卡片模板对文本字段用了 | safe，模型输出可能带 HTML 标签，这里先转义，
    # 防止排版被破坏（文本输出 build_text_result 不转义）。
    return {
        "score": score,
        "score_label": f"{score}/100",
        "stars": stars(score),
        "score_color": score_color(score),
        "style_name": html.escape(style_name, quote=False),
        "reason": html.escape(judgement.reason or "（模型没有给出理由）", quote=False),
        "roast": html.escape(judgement.roast or "（模型没有给出吐槽）", quote=False),
        "image_src": image_src,
        "theme": resolve_theme(theme),
        "footer": "AI 鉴图评分 · 纯娱乐",
    }
