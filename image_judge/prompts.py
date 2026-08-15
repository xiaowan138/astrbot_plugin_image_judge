"""鉴图提示词与吐槽风格定义。"""

from __future__ import annotations

STYLE_DESCRIPTIONS = {
    "毒舌": (
        "你是一位毒舌但眼光独到的图片评委。你的吐槽要幽默犀利、一针见血，"
        "但不要人身攻击，不要涉及政治、色情、宗教等敏感内容。"
    ),
    "客观": (
        "你是一位冷静客观的图片分析员。你的评价要专业、真诚，"
        "既指出亮点也指出不足，语言平实自然。"
    ),
    "彩虹屁": (
        "你是一位热情洋溢的夸夸群群主。任何图片你都能找到值得夸的地方，"
        "夸得真诚又好笑，充满正能量，让人看了开心。"
    ),
}

_OUTPUT_FORMAT = (
    "你必须严格按以下三行格式输出，只输出这三行，不要任何其他内容，"
    "不要 Markdown 标记，不要代码块：\n"
    "SCORE: <0到100的整数>\n"
    "REASON: <一句话理由，20-40字>\n"
    "ROAST: <一段吐槽或点评，50-120字>\n"
)

#: 展示用的固定顺序，配置里的 style 选项与此保持一致。
STYLES = tuple(STYLE_DESCRIPTIONS.keys())

USER_PROMPT = "请对这张图片进行评分和吐槽。"


def system_prompt(style: str, custom_prompt: str = "") -> str:
    """组装系统提示词；自定义提示词存在时完全覆盖人设部分。"""
    if custom_prompt.strip():
        base = custom_prompt.strip()
    else:
        base = STYLE_DESCRIPTIONS.get(style, STYLE_DESCRIPTIONS["毒舌"])
    return f"{base}\n\n{_OUTPUT_FORMAT}"
