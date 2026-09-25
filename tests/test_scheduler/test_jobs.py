"""调度层测试（M5）：失败记账、成功销账、启动补跑、漏生成补齐、调度装配。

这里用 monkeypatch 把 generate_* 换成假函数——本文件测的是调度层的编排与状态流转，
生成器自身的行为在 tests/test_report/test_generator.py 里测。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest

import config
from scheduler import jobs
from storage import db


class _Collector:
    """鸭子类型的采集器替身：调度层只要求它有 run_once_safe()。"""

    def run_once_safe(self) -> None:
        pass


def _boom(*_args, **_kwargs):
    raise RuntimeError("APIConnectionError: 网络不通")


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


# ---------------------------------------------------------------- 日报失败与销账


def test_daily_failure_records_pending(monkeypatch) -> None:
    db.init_db()
    monkeypatch.setattr(jobs, "generate_daily_report", _boom)

    result = jobs.run_daily_report("2026-09-15")

    assert "error" in result
    rows = db.get_pending_reports()
    assert len(rows) == 1
    assert rows[0]["type"] == "daily"
    assert rows[0]["date"] == "2026-09-15"
    assert "网络不通" in rows[0]["reason"]


def test_daily_failure_notifies_callback(monkeypatch) -> None:
    db.init_db()
    monkeypatch.setattr(jobs, "generate_daily_report", _boom)
    seen: list[str] = []

    jobs.run_daily_report("2026-09-15", on_ai_failure=seen.append)

    assert seen and "网络不通" in seen[0]


def test_daily_success_clears_existing_pending(monkeypatch) -> None:
    db.init_db()
    db.add_pending_report("2026-09-15", "daily", "上一次失败")
    monkeypatch.setattr(
        jobs, "generate_daily_report", lambda date, is_overwritten=False: {"date": date}
    )

    assert "error" not in jobs.run_daily_report("2026-09-15")
    assert db.get_pending_reports() == []


def test_daily_skip_also_clears_pending(monkeypatch) -> None:
    """没素材是客观事实不是 AI 失败，留着欠账只会每天白重试。"""
    db.init_db()
    db.add_pending_report("2026-09-16", "daily", "旧欠账")
    monkeypatch.setattr(
        jobs, "generate_daily_report",
        lambda date, is_overwritten=False: {"skipped": True, "reason": "当日无采集素材"},
    )

    jobs.run_daily_report("2026-09-16")

    assert db.get_pending_reports() == []


def test_repeated_failure_keeps_one_pending_row(monkeypatch) -> None:
    db.init_db()
    monkeypatch.setattr(jobs, "generate_daily_report", _boom)

    jobs.run_daily_report("2026-09-15")
    jobs.run_daily_report("2026-09-15")

    assert len(db.get_pending_reports()) == 1


def test_overwrite_report_targets_yesterday(monkeypatch) -> None:
    """需求 D7：次日 00:30 覆盖的是**前一天**，不是当天。"""
    db.init_db()
    captured: dict[str, Any] = {}

    def _fake(date, is_overwritten=False):
        captured["date"] = date
        captured["is_overwritten"] = is_overwritten
        return {"date": date}

    monkeypatch.setattr(jobs, "generate_daily_report", _fake)
    jobs.run_overwrite_report()

    assert captured == {"date": _yesterday(), "is_overwritten": True}


# ---------------------------------------------------------------- 周报


def test_weekly_failure_records_pending(monkeypatch) -> None:
    db.init_db()
    monkeypatch.setattr(jobs, "generate_weekly_report", _boom)

    jobs.run_weekly_report("2026-09-14")

    rows = db.get_pending_reports()
    assert len(rows) == 1
    assert rows[0]["type"] == "weekly"
    assert rows[0]["date"] == "2026-09-14"


def test_weekly_success_clears_pending(monkeypatch) -> None:
    db.init_db()
    db.add_pending_report("2026-09-14", "weekly", "旧欠账")
    monkeypatch.setattr(
        jobs, "generate_weekly_report", lambda week_start: {"week_start": week_start}
    )

    jobs.run_weekly_report("2026-09-14")

    assert db.get_pending_reports() == []


def test_current_week_start_is_monday() -> None:
    monday = date.fromisoformat(jobs.current_week_start())
    assert monday.weekday() == 0
    assert monday <= date.today() <= monday + timedelta(days=6)


# ---------------------------------------------------------------- 启动补跑


def test_retry_pending_replays_both_types_and_clears(monkeypatch) -> None:
    db.init_db()
    db.add_pending_report("2026-09-14", "daily", "断网")
    db.add_pending_report("2026-09-14", "weekly", "断网")
    monkeypatch.setattr(
        jobs, "generate_daily_report", lambda date, is_overwritten=False: {"date": date}
    )
    monkeypatch.setattr(
        jobs, "generate_weekly_report", lambda week_start: {"week_start": week_start}
    )

    assert jobs.retry_pending() == {"retried": 2, "succeeded": 2}
    assert db.get_pending_reports() == []


def test_retry_pending_noop_when_no_debt() -> None:
    db.init_db()
    assert jobs.retry_pending() == {"retried": 0, "succeeded": 0}


def test_retry_pending_keeps_debt_when_still_failing(monkeypatch) -> None:
    db.init_db()
    db.add_pending_report("2026-09-14", "daily", "断网")
    monkeypatch.setattr(jobs, "generate_daily_report", _boom)

    assert jobs.retry_pending() == {"retried": 1, "succeeded": 0}
    assert len(db.get_pending_reports()) == 1  # 仍失败，欠账留着下次再试


def test_retry_pending_skips_unknown_type() -> None:
    db.init_db()
    db.add_pending_report("2026-09-14", "unknown", "手滑")
    assert jobs.retry_pending() == {"retried": 0, "succeeded": 0}


def test_catch_up_generates_missing_yesterday(monkeypatch) -> None:
    """需求 F2.1：22:00 关机没跑成，次日启动补出昨天那份并标覆盖版。"""
    db.init_db()
    db.save_screenshot_analysis(f"{_yesterday()}T10:00:00", "在写 M5")
    captured: dict[str, Any] = {}

    def _fake(date, is_overwritten=False):
        captured["date"] = date
        captured["is_overwritten"] = is_overwritten
        return {"date": date}

    monkeypatch.setattr(jobs, "generate_daily_report", _fake)

    assert jobs.catch_up_missed_reports() == [_yesterday()]
    assert captured == {"date": _yesterday(), "is_overwritten": True}


def test_catch_up_skips_when_yesterday_has_report(monkeypatch) -> None:
    db.init_db()
    db.save_screenshot_analysis(f"{_yesterday()}T10:00:00", "素材")
    db.save_daily_report(_yesterday(), "已有日报", "{}")
    monkeypatch.setattr(jobs, "generate_daily_report", lambda *a, **k: pytest.fail("不该再生成"))

    assert jobs.catch_up_missed_reports() == []


def test_catch_up_skips_when_no_materials(monkeypatch) -> None:
    """没采集数据的日期本来就该跳过，不能凭空造日报。"""
    db.init_db()
    monkeypatch.setattr(jobs, "generate_daily_report", lambda *a, **k: pytest.fail("不该生成"))

    assert jobs.catch_up_missed_reports() == []


def test_catch_up_fills_every_missing_day_within_retention(monkeypatch) -> None:
    """关机好几天回来：保留期内每个缺日报的日子都要补，不能只看昨天。"""
    db.init_db()
    offsets = (1, 2)
    for offset in offsets:
        day = (date.today() - timedelta(days=offset)).isoformat()
        db.save_screenshot_analysis(f"{day}T10:00:00", f"素材{offset}")
    generated: list[str] = []

    def _fake(target, is_overwritten=False):
        generated.append(target)
        return {"date": target}

    monkeypatch.setattr(jobs, "generate_daily_report", _fake)

    expected = [(date.today() - timedelta(days=o)).isoformat() for o in offsets]
    assert jobs.catch_up_missed_reports() == expected
    assert generated == expected


def test_catch_up_stops_at_retention_window(monkeypatch) -> None:
    """超出素材保留期的日期不再扫：素材已被清理，硬生成只会造出空日报。"""
    db.init_db()
    retention = config.DEFAULT_SETTINGS["storage"]["raw_retention_days"]
    beyond = (date.today() - timedelta(days=retention + 1)).isoformat()
    db.save_screenshot_analysis(f"{beyond}T10:00:00", "过期素材")
    monkeypatch.setattr(jobs, "generate_daily_report", lambda *a, **k: pytest.fail("不该生成"))

    assert jobs.catch_up_missed_reports() == []


# ---------------------------------------------------------------- 清理


def test_run_cleanup_swallows_failure(monkeypatch) -> None:
    db.init_db()
    monkeypatch.setattr(jobs, "cleanup_expired", _boom)
    assert jobs.run_cleanup() == 0  # 清理失败只记日志，不影响其他任务


def test_run_cleanup_also_clears_app_usage(monkeypatch) -> None:
    """M9：素材 3 天、应用明细 90 天，两个保留期在每日清理里都要跑到。"""
    db.init_db()
    db.save_app_usage("2020-01-01T10:00:00", "Code", 300)
    monkeypatch.setattr(jobs, "cleanup_expired", lambda: 0)

    jobs.run_cleanup()

    assert db.get_app_usage_summary("2020-01-01") == []


# ---------------------------------------------------------------- 应用采样门控


class _UsageCollector:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def run_once_safe(self) -> None:
        self._calls.append("sampled")


def test_run_app_usage_skips_outside_work_hours() -> None:
    """需求 F1.3：与截图采集同一工作时间窗口，窗口外不采样。"""
    config.update_settings({"capture": {"work_hours": {"start": "00:00", "end": "00:01"}}})
    calls: list[str] = []

    jobs.run_app_usage(_UsageCollector(calls))

    assert calls == []


def test_run_app_usage_delegates_inside_work_hours() -> None:
    config.update_settings({"capture": {"work_hours": {"start": "00:00", "end": "23:59"}}})
    calls: list[str] = []

    jobs.run_app_usage(_UsageCollector(calls))

    assert calls == ["sampled"]


# ---------------------------------------------------------------- 调度装配


def _build(monkeypatch, patch: dict | None = None):
    """建调度器前先把任务体换成假函数，避免测试期间真跑 AI。"""
    if patch:
        config.update_settings(patch)
    monkeypatch.setattr(jobs, "run_daily_report", lambda *a, **k: {})
    monkeypatch.setattr(jobs, "run_overwrite_report", lambda *a, **k: {})
    monkeypatch.setattr(jobs, "run_weekly_report", lambda *a, **k: {})
    monkeypatch.setattr(jobs, "run_cleanup", lambda: 0)
    return jobs.build_scheduler(_Collector())


def test_build_scheduler_registers_all_jobs(monkeypatch) -> None:
    scheduler = _build(monkeypatch)
    try:
        assert {job.id for job in scheduler.get_jobs()} == {
            "capture", "app_usage", "daily_report", "daily_overwrite",
            "weekly_report", "cleanup",
        }
    finally:
        scheduler.shutdown(wait=False)


def test_build_scheduler_skips_weekly_when_disabled(monkeypatch) -> None:
    scheduler = _build(monkeypatch, {"report": {"weekly_enabled": False}})
    try:
        ids = {job.id for job in scheduler.get_jobs()}
        assert "weekly_report" not in ids
        assert {"capture", "daily_report", "cleanup"} <= ids
    finally:
        scheduler.shutdown(wait=False)


def test_reschedule_moves_daily_job(monkeypatch) -> None:
    scheduler = _build(monkeypatch)
    try:
        config.update_settings({"report": {"daily_time": "21:15"}})
        jobs.reschedule_report_jobs(scheduler)

        fields = {f.name: str(f) for f in scheduler.get_job("daily_report").trigger.fields}
        assert fields["hour"] == "21"
        assert fields["minute"] == "15"
    finally:
        scheduler.shutdown(wait=False)


def test_build_scheduler_falls_back_on_corrupt_settings(monkeypatch) -> None:
    """校验上线前写入的坏配置不能让调度器整体起不来——那等于采集与日报永久失效。"""
    path = config.get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"report": {"daily_time": "abc", "overwrite_time": "25:99"}}),
                    encoding="utf-8")

    scheduler = _build(monkeypatch)
    try:
        fields = {f.name: str(f) for f in scheduler.get_job("daily_report").trigger.fields}
        assert (int(fields["hour"]), int(fields["minute"])) == config.parse_hhmm(
            config.DEFAULT_SETTINGS["report"]["daily_time"]
        )
    finally:
        scheduler.shutdown(wait=False)
