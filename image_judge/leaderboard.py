"""本群鉴图历史与排行榜（JSON 持久化）。

每次成功鉴图记录一条（分数、受评者、时间、一句话理由），按群分组保存，
支持按时间窗口查询最高分榜单与最低分“最惨”记录。存储有界：每群只保留
最近 ``max_per_group`` 条，避免无限增长。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class JudgeRecord:
    score: int
    subject_id: str  # 受评者（图的主人）ID
    ts: float
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "subject_id": self.subject_id,
            "ts": self.ts,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: object) -> "JudgeRecord | None":
        if not isinstance(data, dict):
            return None
        try:
            score = int(data["score"])
            subject_id = str(data.get("subject_id") or "").strip()
            ts = float(data["ts"])
        except (KeyError, TypeError, ValueError):
            return None
        if not subject_id:
            return None
        return cls(
            score=max(0, min(score, 100)),
            subject_id=subject_id,
            ts=ts,
            reason=str(data.get("reason") or ""),
        )


class LeaderboardStore:
    def __init__(self, path: Path, *, max_per_group: int = 500) -> None:
        self._path = Path(path)
        self._max_per_group = max(int(max_per_group), 1)
        self._data: dict[str, list[JudgeRecord]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self._data = {}
        if isinstance(data, dict):
            for group_id, records in data.items():
                if not isinstance(records, list):
                    continue
                parsed = [
                    record
                    for record in (
                        JudgeRecord.from_dict(item) for item in records
                    )
                    if record is not None
                ]
                if parsed:
                    self._data[str(group_id)] = parsed

    def _save(self) -> None:
        # 先写临时文件再替换，避免写入中途被打断留下半个 JSON。
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        group: [record.to_dict() for record in records]
                        for group, records in self._data.items()
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(tmp, self._path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _window(self, group_id: str, since: float | None) -> list[JudgeRecord]:
        self._load()
        return [
            record
            for record in self._data.get(str(group_id), [])
            if since is None or record.ts >= since
        ]

    def add(self, group_id: str, record: JudgeRecord) -> None:
        self._load()
        records = self._data.setdefault(str(group_id), [])
        records.append(record)
        if len(records) > self._max_per_group:
            del records[: len(records) - self._max_per_group]
        self._save()

    def top(
        self, group_id: str, *, since: float | None = None, limit: int = 5
    ) -> list[JudgeRecord]:
        """时间窗口内分数最高的前 ``limit`` 条（同分先到先得）。"""
        records = self._window(group_id, since)
        records.sort(key=lambda record: (-record.score, record.ts))
        return records[: max(int(limit), 1)]

    def worst(self, group_id: str, *, since: float | None = None) -> JudgeRecord | None:
        """时间窗口内分数最低的一条（同分取最近一次）。"""
        records = self._window(group_id, since)
        if not records:
            return None
        return min(records, key=lambda record: (record.score, -record.ts))
