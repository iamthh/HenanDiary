"""素材清理测试（M6 / 需求 D13：截图分析文字保留 3 天，日报周报永久保留）。"""

from __future__ import annotations

from datetime import date, timedelta

import config
from storage import cleanup, db


def _day(offset: int) -> str:
    """相对今天的偏移日期，YYYY-MM-DD。"""
    return (date.today() + timedelta(days=offset)).isoformat()


def _seed(offsets: list[int]) -> None:
    db.init_db()
    for offset in offsets:
        db.save_screenshot_analysis(f"{_day(offset)}T10:00:00", f"{offset} 天前的素材")


def test_cleanup_keeps_recent_days_and_returns_count() -> None:
    _seed([0, -1, -2, -3, -10])

    assert cleanup.cleanup_expired(3) == 2  # 只删 -3 与 -10
    assert db.get_today_analyses(_day(0))
    assert db.get_today_analyses(_day(-1))
    assert db.get_today_analyses(_day(-2))
    assert db.get_today_analyses(_day(-3)) == []
    assert db.get_today_analyses(_day(-10)) == []


def test_cleanup_returns_zero_when_nothing_expired() -> None:
    _seed([0, -1])
    assert cleanup.cleanup_expired(3) == 0


def test_cleanup_falls_back_to_config_retention() -> None:
    _seed([0, -1])
    config.update_settings({"storage": {"raw_retention_days": 1}})
    assert cleanup.cleanup_expired() == 1  # 只留今天


def test_cleanup_never_touches_reports() -> None:
    """D13：日报/周报永久保留，清理只动截图素材。"""
    _seed([-30])
    db.save_daily_report(_day(-30), "很久以前的日报", "{}")
    db.save_weekly_report(_day(-30), "很久以前的周报")

    cleanup.cleanup_expired(3)

    assert db.get_daily_report(_day(-30)) is not None
    assert db.get_weekly_report(_day(-30)) is not None
