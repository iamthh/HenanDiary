r"""配置读写与数据目录解析。

数据路径与安装路径完全分离（需求文档 D12）：
- 安装路径：默认 C:\Program Files\，由安装包决定，用户可改
- 数据路径：固定 %APPDATA%\HenanDiary\

开发规范 1.4：任何模块需要配置都从本模块读，禁止自己存配置、禁止写死路径/Key/URL。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "HenanDiary"

# 需求文档 D9：截图间隔只能三选一，默认 5 分钟
ALLOWED_INTERVAL_MIN = (2, 5, 10)
DEFAULT_SCREENSHOT_INTERVAL_MIN = 5

DEFAULT_SETTINGS: dict[str, Any] = {
    "ai": {
        "api_key_encrypted": "",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "capture": {
        "screenshot_interval_min": DEFAULT_SCREENSHOT_INTERVAL_MIN,
        "work_hours": {"start": "09:00", "end": "19:00"},
        "enabled": True,
    },
    "report": {
        "daily_time": "22:00",
        "overwrite_time": "00:30",
        "weekly_enabled": True,
    },
    "storage": {
        "raw_retention_days": 3,
        "usage_retention_days": 90,   # 应用使用明细保留期（需求 D20 / F7.1）
    },
    "onboarding": {
        "done": False,
    },
}


def parse_hhmm(text: str, field: str = "时间") -> tuple[int, int]:
    """把 "HH:MM" 解析成 (时, 分)；格式或范围非法时抛 ValueError。

    抽成公开函数的理由：写入前校验（_validate）与使用侧解析（scheduler / collector）
    必须是同一套口径，否则会出现"值写进去了但任务起不来"的静默失效。
    非法示例：非字符串、缺冒号、'abc'、'25:99'。
    """
    if not isinstance(text, str):
        raise ValueError(f"{field} 必须是 HH:MM 字符串，收到: {text!r}")
    hour_text, sep, minute_text = text.partition(":")
    if sep != ":" or not hour_text.isdigit() or not minute_text.isdigit():
        raise ValueError(f"{field} 必须是 HH:MM 格式，收到: {text!r}")
    hour, minute = int(hour_text), int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"{field} 超出范围 00:00-23:59，收到: {text!r}")
    return hour, minute


def get_data_dir() -> Path:
    r"""数据根目录 %APPDATA%\HenanDiary\（只解析路径，不创建）。"""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("环境变量 APPDATA 缺失，无法定位数据目录")
    return Path(appdata) / APP_NAME


def get_db_path() -> Path:
    """SQLite 主库路径。"""
    return get_data_dir() / "data.db"


def get_config_path() -> Path:
    """settings.json 路径。"""
    return get_data_dir() / "config" / "settings.json"


def get_reports_dir(kind: str = "daily") -> Path:
    """报表目录，kind 取 daily 或 weekly。"""
    if kind not in ("daily", "weekly"):
        raise ValueError(f"未知的报表类型: {kind}")
    return get_data_dir() / "reports" / kind


def get_logs_dir() -> Path:
    """日志目录。"""
    return get_data_dir() / "logs"


def get_exports_dir() -> Path:
    """用户手动导出的落盘目录。"""
    return get_data_dir() / "exports"


def ensure_dirs() -> None:
    """创建全部数据目录（幂等），只建目录不动已有文件。"""
    for path in (
        get_data_dir() / "config",
        get_data_dir() / "reports" / "daily",
        get_data_dir() / "reports" / "weekly",
        get_logs_dir(),
        get_exports_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    """读取 settings.json。

    文件不存在时先写入一份默认配置再返回（开箱即用，用户知道去哪填 Key）。
    返回值必然包含全部默认键，缺失的键由默认值补齐，调用方无需判空。
    """
    path = get_config_path()
    if not path.exists():
        save_settings(DEFAULT_SETTINGS)
        return _deep_copy(DEFAULT_SETTINGS)
    with path.open("r", encoding="utf-8") as file:
        raw = json.load(file)
    return _deep_merge(_deep_copy(DEFAULT_SETTINGS), raw)


def save_settings(settings: dict[str, Any]) -> None:
    """整体写回 settings.json，先写临时文件再替换，避免写坏原文件。"""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """深合并局部改动后落盘，返回合并后的完整配置。"""
    merged = _deep_merge(load_settings(), patch)
    _validate(merged)
    save_settings(merged)
    return merged


def _validate(settings: dict[str, Any]) -> None:
    """写入前校验全部可配置的取值。

    为什么必须拦在这里：非法值一旦落盘，`scheduler.build_scheduler` 会在启动时抛异常
    并被 `main._start_scheduler` 吞掉——采集与日报**再也不会跑**，而界面仍显示"采集运行中"。
    这种静默失效查起来极贵，所以在写入这一道就掐死。
    """
    interval = settings["capture"]["screenshot_interval_min"]
    if interval not in ALLOWED_INTERVAL_MIN:
        raise ValueError(
            f"截图间隔只允许 {sorted(ALLOWED_INTERVAL_MIN)} 分钟，收到: {interval!r}"
        )

    work_hours = settings["capture"]["work_hours"]
    start = parse_hhmm(work_hours["start"], "capture.work_hours.start")
    end = parse_hhmm(work_hours["end"], "capture.work_hours.end")
    if start >= end:
        # 需求 F1.2 只要求一个工作时段，未定义跨天语义，所以结束必须晚于开始
        raise ValueError(
            f"工作时间结束须晚于开始（当前 {work_hours['start']}-{work_hours['end']}，不支持跨天）"
        )

    parse_hhmm(settings["report"]["daily_time"], "report.daily_time")
    parse_hhmm(settings["report"]["overwrite_time"], "report.overwrite_time")


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = _deep_copy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value
