"""采集器核心逻辑测试：work_hours 门控 + run_once 不真截图不真调 AI。"""

from __future__ import annotations

import base64
import io
from datetime import datetime

import pytest
from PIL import Image

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


def test_in_work_hours_falls_back_on_bad_config() -> None:
    """历史坏配置不能让采集长期不跑：回落默认 09:00-19:00 而不是抛异常。"""
    bad = {"start": "abc", "end": "25:00"}
    assert screenshot.ScreenshotCollector.in_work_hours(datetime(2026, 9, 15, 10, 30), bad) is True
    assert screenshot.ScreenshotCollector.in_work_hours(datetime(2026, 9, 15, 8, 30), bad) is False


class _FakeAI:
    def __init__(self) -> None:
        self.mimes: list[str] = []

    def analyze_image(self, b64: str, mime: str = "image/jpeg") -> str:
        assert b64, "应收到 base64 图片"
        self.mimes.append(mime)
        return "在看文档"


def _patch_capture(
    monkeypatch: pytest.MonkeyPatch, png: bytes = b"png-bytes", jpeg: bytes = b"jpeg-bytes"
) -> None:
    """截屏与压缩都在测试里换成假数据，本文件只测编排，不碰真实屏幕。"""
    monkeypatch.setattr(screenshot, "capture_to_memory", lambda: png)
    monkeypatch.setattr(screenshot, "shrink_for_ai", lambda _data: jpeg)


def _new_collector() -> screenshot.ScreenshotCollector:
    collector = screenshot.ScreenshotCollector.__new__(screenshot.ScreenshotCollector)
    collector._ai = _FakeAI()
    return collector


def test_run_once_stores_analysis(monkeypatch) -> None:
    db.init_db()
    config.update_settings({"capture": {"work_hours": {"start": "00:00", "end": "23:59"}}})
    _patch_capture(monkeypatch)

    collector = _new_collector()
    collector.run_once()

    rows = db.get_today_analyses(datetime.now().strftime("%Y-%m-%d"))
    assert len(rows) == 1 and rows[0]["analysis"] == "在看文档"


def test_run_once_sends_compressed_jpeg_not_raw_screenshot(monkeypatch) -> None:
    """送 AI 的必须是压缩产物 + 对应 mime，否则压缩白做、模型还可能解不出图。"""
    db.init_db()
    config.update_settings({"capture": {"work_hours": {"start": "00:00", "end": "23:59"}}})
    _patch_capture(monkeypatch, png=b"raw-png", jpeg=b"tiny-jpeg")
    seen: dict = {}

    class _Recorder:
        def analyze_image(self, b64: str, mime: str = "image/jpeg") -> str:
            seen["b64"], seen["mime"] = b64, mime
            return "动作"

    collector = _new_collector()
    collector._ai = _Recorder()
    collector.run_once()

    assert base64.b64decode(seen["b64"]) == b"tiny-jpeg"
    assert seen["mime"] == screenshot.AI_IMAGE_MIME


def test_shrink_for_ai_limits_width_and_returns_jpeg() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), (30, 30, 30)).save(buffer, format="PNG")
    original = buffer.getvalue()

    shrunk = screenshot.shrink_for_ai(original)

    assert shrunk[:2] == b"\xff\xd8"  # JPEG 魔数
    with Image.open(io.BytesIO(shrunk)) as image:
        assert image.width == screenshot.MAX_AI_IMAGE_WIDTH
        assert image.height == round(1080 * screenshot.MAX_AI_IMAGE_WIDTH / 1920)
    assert len(shrunk) < len(original)


def test_shrink_for_ai_keeps_narrow_image_untouched() -> None:
    """已经比目标窄的图不该被放大——放大只增成本不增信息。"""
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (200, 200, 200)).save(buffer, format="PNG")

    with Image.open(io.BytesIO(screenshot.shrink_for_ai(buffer.getvalue()))) as image:
        assert (image.width, image.height) == (800, 600)


def test_run_once_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    db.init_db()
    config.update_settings({"capture": {"enabled": False}})
    monkeypatch.setattr(screenshot, "capture_to_memory", lambda: pytest.fail("不应截图"))

    _new_collector().run_once()  # 不应抛异常、不应入库
    assert db.get_today_analyses(datetime.now().strftime("%Y-%m-%d")) == []


def test_run_once_safe_swallows_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """单轮失败只记日志，不抛出——调度循环必须活过每一轮。"""
    monkeypatch.setattr(
        screenshot, "capture_to_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("屏幕锁定")),
    )
    _new_collector().run_once_safe()  # 不应抛出
