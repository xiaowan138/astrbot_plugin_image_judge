"""模型输出的结构化评分解析。

模型被要求输出 SCORE / REASON / ROAST 三行；这里用宽松正则提取，
任何字段缺失都不至于失败，由调用方决定是展示部分字段还是降级为原文。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SCORE_RE = re.compile(r"SCORE\s*[:：]\s*(\d{1,3})", re.I)
_REASON_RE = re.compile(r"REASON\s*[:：]\s*(.+)", re.I)
_ROAST_RE = re.compile(r"ROAST\s*[:：]\s*([\s\S]+)", re.I)

_MARKDOWN_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*|\s*```")


@dataclass(frozen=True, slots=True)
class Judgement:
    score: int | None
    reason: str
    roast: str
    raw: str

    @property
    def is_structured(self) -> bool:
        return self.score is not None or bool(self.reason or self.roast)


def _clamp_score(value: str) -> int:
    try:
        return max(0, min(int(value), 100))
    except (TypeError, ValueError):
        return 0


def parse_judgement(text: str) -> Judgement:
    cleaned = _MARKDOWN_FENCE_RE.sub("", text or "").strip()
    score_match = _SCORE_RE.search(cleaned)
    reason_match = _REASON_RE.search(cleaned)
    roast_match = _ROAST_RE.search(cleaned)

    score = _clamp_score(score_match.group(1)) if score_match else None
    reason = reason_match.group(1).strip() if reason_match else ""
    roast = roast_match.group(1).strip() if roast_match else ""
    return Judgement(score=score, reason=reason, roast=roast, raw=text or "")
