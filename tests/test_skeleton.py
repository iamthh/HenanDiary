"""骨架验收：包结构完整、模块可导入、入口分发。

M8 起常驻入口是 Web 主窗口（pywebview），GUI 接线靠真窗口测成本高，
offscreen 测试只验 CLI 分发；桥接层逻辑在 tests/test_ui/test_api.py 覆盖。
"""

from __future__ import annotations

import importlib

import pytest

import main


def test_package_importable() -> None:
    for package in ["collector", "ai", "storage", "report", "scheduler", "ui"]:
        assert importlib.import_module(package) is not None


@pytest.mark.parametrize("module", ["config", "logger", "storage.db", "storage.cleanup"])
def test_module_importable(module: str) -> None:
    assert importlib.import_module(module) is not None


def test_ui_packages_importable() -> None:
    # M8 后 ui 包只剩 Web 桥与单实例，都不该再拖 PySide6
    for module in ["ui.api", "ui.single_instance"]:
        mod = importlib.import_module(module)
        assert mod is not None
    import subprocess, sys
    out = subprocess.run([sys.executable, "-c",
                          "import ui.api, ui.single_instance; "
                          "import sys; sys.exit('PySide6' in sys.modules)"],
                         capture_output=True)
    assert out.returncode == 0, "ui 包导入时不应拉起 PySide6"


def test_cli_dispatch(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(main, "_gen_report", lambda argv: calls.append(("gen", argv)) or 0)
    monkeypatch.setattr(main, "_run_ui", lambda: calls.append(("ui",)) or 0)
    assert main.main(["--gen-report", "2026-09-14"]) == 0
    assert main.main([]) == 0
    assert calls == [("gen", ["2026-09-14"]), ("ui",)]
