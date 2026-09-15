"""骨架验收：包结构完整、模块可导入、入口分发与接线顺序。

M3 后常驻入口改为 GUI（托盘+事件循环），offscreen 下用 QTimer 退出 exec，
验证的是接线顺序（建库→引导门控→起调度→退出时停调度），不是真实截图。
"""

from __future__ import annotations

import importlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import config
import main


class _FakeScheduler:
    def __init__(self) -> None:
        self.shutdown_called = False

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_called = True


@pytest.fixture
def wired_main(monkeypatch):
    """假采集器/调度器 + 引导已完成 + exec 立即 quit。"""
    import collector.screenshot as cs
    import scheduler.jobs as jobs
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    fake = _FakeScheduler()
    monkeypatch.setattr(cs, "ScreenshotCollector", lambda: object())
    # M5 起调度统一收在 scheduler/jobs.build_scheduler，采集器不再自带 start_scheduler
    monkeypatch.setattr(jobs, "build_scheduler", lambda collector, on_ai_failure=None: fake)
    config.load_settings()  # 先生成 settings.json 再翻引导标记
    config.update_settings({"onboarding": {"done": True}})
    app = QApplication.instance() or QApplication([])
    QTimer.singleShot(0, app.quit)
    return fake


def test_package_importable() -> None:
    for package in ["collector", "ai", "storage", "report", "scheduler", "ui"]:
        assert importlib.import_module(package) is not None


@pytest.mark.parametrize("module", ["config", "logger", "storage.db", "storage.cleanup"])
def test_module_importable(module: str) -> None:
    assert importlib.import_module(module) is not None


def test_entry_point_runs(wired_main) -> None:
    assert main.main() == 0


def test_entry_point_stops_scheduler_on_exit(wired_main) -> None:
    main.main()
    assert wired_main.shutdown_called


def test_entry_point_prepares_data_dirs(wired_main) -> None:
    main.main()
    assert config.get_config_path().is_file()
    assert config.get_db_path().parent.is_dir()


def test_cli_dispatch(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(main, "_gen_report", lambda argv: calls.append(("gen", argv)) or 0)
    monkeypatch.setattr(main, "_run_ui", lambda open_settings_only: calls.append(("ui", open_settings_only)) or 0)
    assert main.main(["--gen-report", "2026-09-14"]) == 0
    assert main.main(["--settings"]) == 0
    assert main.main([]) == 0
    assert calls == [("gen", ["2026-09-14"]), ("ui", True), ("ui", False)]
