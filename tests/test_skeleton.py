"""骨架验收：包结构完整、模块可导入、入口可跑通。

M1 后 main() 常驻运行，测试用替身把采集器/调度器/睡眠换掉，
验证的是接线顺序（建库→起调度→响应退出），不是真实截图。
"""

from __future__ import annotations

import importlib

import pytest

import config
import main


class _FakeScheduler:
    def __init__(self) -> None:
        self.shutdown_called = False

    def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.fixture
def wired_main(monkeypatch):
    """给 main 装替身：假采集器 + 假调度器 + 第一次 sleep 就 Ctrl+C。"""
    fake = _FakeScheduler()
    monkeypatch.setattr(main, "ScreenshotCollector", lambda: object())
    monkeypatch.setattr(main, "start_scheduler", lambda collector: fake)
    monkeypatch.setattr(main.time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt))
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
