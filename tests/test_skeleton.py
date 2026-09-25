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


# ---------------------------------------------------------------- WebView2 检测（M8 遗留补齐）


class _FakeKey:
    def __init__(self, value: str) -> None:
        self._value = value

    def __enter__(self) -> "_FakeKey":
        return self

    def __exit__(self, *_args) -> bool:
        return False


_WEBVIEW2_SUB = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _patch_registry(monkeypatch, pv_by_sub: dict[tuple, str]) -> None:
    """把 winreg 换成内存字典：键 (root, 子路径) 不在字典里 = 该登记点不存在。"""
    import winreg

    def fake_open(root, sub):
        if (root, sub) not in pv_by_sub:
            raise OSError
        return _FakeKey(pv_by_sub[(root, sub)])

    def fake_query(key, name):
        assert name == "pv"
        return key._value, None

    monkeypatch.setattr(winreg, "OpenKey", fake_open)
    monkeypatch.setattr(winreg, "QueryValueEx", fake_query)


def test_find_webview2_runtime_reads_pv_from_registry(monkeypatch) -> None:
    import winreg

    _patch_registry(monkeypatch, {(winreg.HKEY_CURRENT_USER, _WEBVIEW2_SUB): "140.0.3313.0"})
    assert main._find_webview2_runtime() == "140.0.3313.0"


def test_find_webview2_runtime_ignores_placeholder_and_missing(monkeypatch) -> None:
    """三处登记点全缺返回 None；pv="0.0.0.0" 是 EdgeUpdate 的"未安装"占位，同样不算数。"""
    import winreg

    _patch_registry(monkeypatch, {
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"):
        "0.0.0.0",
    })
    assert main._find_webview2_runtime() is None


def test_ensure_webview2_blocks_and_offers_download_when_missing(monkeypatch) -> None:
    boxes: list[tuple] = []
    opened: list[str] = []
    import ctypes

    monkeypatch.setattr(main, "_find_webview2_runtime", lambda: None)
    monkeypatch.setattr(ctypes.windll.user32, "MessageBoxW",
                        lambda *args: boxes.append(args) or 6)  # IDYES
    monkeypatch.setattr(main, "_WEBVIEW2_DOWNLOAD_URL", "https://example.com/webview2")

    import os
    monkeypatch.setattr(os, "startfile", lambda url: opened.append(url))

    assert main._ensure_webview2() is False
    assert len(boxes) == 1
    assert opened == ["https://example.com/webview2"]


def test_ensure_webview2_passes_silently_when_runtime_present(monkeypatch) -> None:
    import ctypes

    monkeypatch.setattr(main, "_find_webview2_runtime", lambda: "140.0.0.0")
    monkeypatch.setattr(ctypes.windll.user32, "MessageBoxW",
                        lambda *args: pytest.fail("运行时存在时不该弹对话框"))

    assert main._ensure_webview2() is True
