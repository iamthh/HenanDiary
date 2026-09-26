"""前台应用采样测试（M9）：空闲剔除、门控、时长快照、容错。

不碰真窗口：`foreground_process_name` / `idle_seconds` 一律换成替身，
本文件只验证 run_once 的门控与写入行为，以及 tick 回绕的算术。
"""

from __future__ import annotations

from datetime import datetime

import pytest

import config
from collector import app_usage
from storage import db


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _prep(monkeypatch, app="Code", idle=0.0, enabled=True, interval=5) -> None:
    """建库 + 写配置 + 换掉两个 Win32 探针。"""
    db.init_db()
    config.update_settings({
        "capture": {"enabled": enabled, "screenshot_interval_min": interval},
    })
    monkeypatch.setattr(app_usage, "foreground_process_name", lambda: app)
    monkeypatch.setattr(app_usage, "idle_seconds", lambda: idle)


def test_run_once_stores_sample(monkeypatch) -> None:
    _prep(monkeypatch, app="Code", idle=0.0, interval=5)
    app_usage.AppUsageCollector().run_once()

    rows = db.get_app_usage_summary(_today())
    assert len(rows) == 1
    assert rows[0]["app"] == "Code"
    assert rows[0]["seconds"] == 300      # 5 分钟间隔 → 300 秒，写入时定死
    assert rows[0]["samples"] == 1


def test_duration_s_is_snapshot_of_current_interval(monkeypatch) -> None:
    """间隔是 2/5/10 可配的，写进去的是当时的间隔，查询侧不再乘任何东西。

    否则用户改一次设置，全部历史时长会跟着变（需求 F7.1）。
    """
    _prep(monkeypatch, interval=10)
    app_usage.AppUsageCollector().run_once()

    assert db.get_app_usage_summary(_today())[0]["seconds"] == 600


def test_run_once_skips_when_idle(monkeypatch) -> None:
    """挂机不计入，否则挂着 VS Code 去吃饭会被算成「编码两小时」。"""
    _prep(monkeypatch, idle=app_usage.IDLE_THRESHOLD_S + 1)
    app_usage.AppUsageCollector().run_once()

    assert db.get_app_usage_summary(_today()) == []


def test_run_once_skips_when_capture_disabled(monkeypatch) -> None:
    """跟随「暂停采集」全局开关，不另设开关。"""
    _prep(monkeypatch, enabled=False)
    app_usage.AppUsageCollector().run_once()

    assert db.get_app_usage_summary(_today()) == []


def test_run_once_skips_own_process(monkeypatch) -> None:
    """用户开着自己看日报时前台就是自己，计入会污染统计。"""
    _prep(monkeypatch, app="HenanDiary")
    app_usage.AppUsageCollector().run_once()

    assert db.get_app_usage_summary(_today()) == []


def test_run_once_skips_when_name_unavailable(monkeypatch) -> None:
    """权限不足 / 受保护进程取不到名字时跳过本轮，不写脏数据。"""
    _prep(monkeypatch, app=None)
    app_usage.AppUsageCollector().run_once()

    assert db.get_app_usage_summary(_today()) == []


def test_run_once_safe_swallows_exception(monkeypatch) -> None:
    """单轮失败只记日志：调度循环要活过每一轮，也不能连坐截图采集。"""
    db.init_db()
    monkeypatch.setattr(app_usage, "idle_seconds", lambda: 0.0)

    def _boom() -> str:
        raise RuntimeError("foreground 探针炸了")

    monkeypatch.setattr(app_usage, "foreground_process_name", _boom)
    app_usage.AppUsageCollector().run_once_safe()  # 不应抛出


# ---------------------------------------------------------------- tick 回绕


def test_elapsed_seconds_normal() -> None:
    assert app_usage._elapsed_seconds(7000, 1000) == pytest.approx(6.0)


def test_elapsed_seconds_handles_32bit_wraparound() -> None:
    """不 & 0xFFFFFFFF 会算出「空闲 40 亿秒」，当天统计全废。"""
    assert app_usage._elapsed_seconds(0x64, 0xFFFFFF00) == pytest.approx(0.356, abs=0.001)
