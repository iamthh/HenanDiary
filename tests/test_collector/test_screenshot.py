"""采集器核心逻辑测试：work_hours 门控 + run_once 不真截图不真调 AI。"""

from __future__ import annotations

from datetime import datetime

import pytest

import config
from collector import screenshot
from storage import db


@pytest.mark.parametrize(
    "hour,expected",
    [(9, True), (18, True), (19, False), (8, False), (0, False), (23, False)],
)
def test_in_work_hours(hour: int, expected: bool) -> None:
    hours = {"start": "09:00", "end": "19:00"}
    now = datetime(2026, 9, 15, hour, 30)
    assert screenshot.ScreenshotCollector.in_work_hours(now, hours) is expected


class _FakeAI:
    def analyze_image(self, b64: str) -> str:
        assert b64, "应收到 base64 图片"
        return "在看文档"


def test_run_once_stores_analysis(monkeypatch) -> None:
    db.init_db()
    config.update_settings({"capture": {"work_hours": {"start": "00:00", "end": "23:59"}}})
    monkeypatch.setattr(screenshot, "capture_to_memory", lambda: b"png-bytes")

    collector = screenshot.ScreenshotCollector.__new__(screenshot.ScreenshotCollector)
    collector._ai = _FakeAI()
    collector.run_once()

    rows = db.get_today_analyses(datetime.now().strftime("%Y-%m-%d"))
    assert len(rows) == 1 and rows[0]["analysis"] == "在看文档"


def test_run_once_skips_when_disabled(monkeypatch) -> None:
    db.init_db()
    config.update_settings({"capture": {"enabled": False}})
    monkeypatch.setattr(screenshot, "capture_to_memory", lambda: pytest.fail("不应截图"))

    collector = screenshot.ScreenshotCollector.__new__(screenshot.ScreenshotCollector)
    collector._ai = _FakeAI()
    collector.run_once()  # 不应抛异常、不应入库
    assert db.get_today_analyses(datetime.now().strftime("%Y-%m-%d")) == []


def test_run_once_safe_swallows_exception(monkeypatch) -> None:
    """单轮失败只记日志，不抛出——调度循环必须活过每一轮。"""
    collector = screenshot.ScreenshotCollector.__new__(screenshot.ScreenshotCollector)
    collector._ai = _FakeAI()
    monkeypatch.setattr(
        screenshot, "capture_to_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("屏幕锁定")),
    )
    collector.run_once_safe()  # 不应抛出
