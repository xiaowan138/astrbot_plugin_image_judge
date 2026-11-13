"""按群覆盖自动鉴图配置（JSON 持久化，供群管理指令使用）。

语义：全局 ``enable_auto_trigger`` 是总闸（关闭即全停），群覆盖只能在本群
关闭自动触发或调整概率／免打扰时段／每小时上限；``None`` 字段表示跟随全局
默认，空字符串表示本群显式关闭免打扰。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GroupOverride:
    enabled: bool | None = None  # None = 跟随全局
    probability: int | None = None  # None = 跟随全局
    quiet_hours: str | None = None  # None = 跟随全局；"" = 本群关闭
    hourly_limit: int | None = None  # None = 跟随全局


@dataclass(frozen=True, slots=True)
class EffectiveSettings:
    enabled: bool
    probability: int
    probability_source: str  # "本群" / "全局默认"
    quiet_hours: str = ""
    quiet_hours_source: str = "全局默认"
    hourly_limit: int = 0
    hourly_limit_source: str = "全局默认"


def effective_settings(
    *,
    global_enabled: bool,
    global_probability: int,
    override: GroupOverride,
    global_quiet_hours: str = "",
    global_hourly_limit: int = 0,
) -> EffectiveSettings:
    probability = (
        override.probability
        if override.probability is not None
        else global_probability
    )
    probability_source = (
        "本群" if override.probability is not None else "全局默认"
    )
    if override.quiet_hours is None:
        quiet_hours, quiet_hours_source = global_quiet_hours, "全局默认"
    else:
        quiet_hours, quiet_hours_source = override.quiet_hours, "本群"
    if override.hourly_limit is None:
        hourly_limit, hourly_limit_source = global_hourly_limit, "全局默认"
    else:
        hourly_limit, hourly_limit_source = override.hourly_limit, "本群"
    return EffectiveSettings(
        enabled=global_enabled and override.enabled is not False,
        probability=probability,
        probability_source=probability_source,
        quiet_hours=quiet_hours,
        quiet_hours_source=quiet_hours_source,
        hourly_limit=hourly_limit,
        hourly_limit_source=hourly_limit_source,
    )


class GroupConfigStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._data: dict[str, dict] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self._data = data if isinstance(data, dict) else {}

    def _save(self) -> None:
        # 先写临时文件再替换，避免写入中途被打断留下半个 JSON。
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _coerce(stored: object) -> GroupOverride:
        stored = stored if isinstance(stored, dict) else {}
        enabled = stored.get("enabled")
        probability = stored.get("probability")
        quiet_hours = stored.get("quiet_hours")
        hourly_limit = stored.get("hourly_limit")
        return GroupOverride(
            enabled=bool(enabled) if enabled is not None else None,
            probability=int(probability) if probability is not None else None,
            quiet_hours=quiet_hours if isinstance(quiet_hours, str) else None,
            hourly_limit=int(hourly_limit)
            if isinstance(hourly_limit, (int, float))
            and not isinstance(hourly_limit, bool)
            else None,
        )

    def get(self, group_id: str) -> GroupOverride:
        self._load()
        return self._coerce(self._data.get(group_id))

    def set(self, group_id: str, **fields) -> GroupOverride:
        """更新本群覆盖字段（传 None 表示恢复跟随全局）。"""
        self._load()
        entry = dict(self._data.get(group_id) or {})
        for key in ("enabled", "probability", "quiet_hours", "hourly_limit"):
            if key not in fields:
                continue
            value = fields[key]
            if value is None:
                entry[key] = None
            elif key == "enabled":
                entry[key] = bool(value)
            elif key == "quiet_hours":
                entry[key] = str(value)
            else:
                entry[key] = int(value)
        self._data[group_id] = entry
        self._save()
        return self._coerce(entry)
