"""M3 界面冒烟测试：offscreen 模式下构造不崩、托盘菜单项齐全。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

import config
from storage import db
from ui.icons import circle_icon
from ui.main_window import ReportWindow
from ui.tray import TrayIcon


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def seed_reports() -> None:
    db.init_db()
    db.save_daily_report("2026-09-15", "## 今日概览\n在写日报应用", "{}")
    db.save_daily_report("2026-09-14", "## 今日概览\n在做 M2", "{}", is_overwritten=True)


def test_report_window_lists_and_renders(qapp, seed_reports) -> None:
    window = ReportWindow()
    window.refresh()
    assert window._list.count() == 2  # 倒序，第一行是最新
    assert window._list.item(0).text() == "2026-09-15"
    assert "今日概览" in window._view.toPlainText()


def test_report_window_empty(qapp) -> None:
    db.init_db()
    window = ReportWindow()
    window.refresh()
    assert "还没有日报" in window._view.toPlainText()


def test_tray_menu(qapp) -> None:
    window = ReportWindow()
    tray = TrayIcon(window, on_open_settings=lambda: None)
    labels = [a.text() for a in tray.contextMenu().actions() if a.text()]
    assert "查看日报" in labels
    assert "暂停采集" in labels
    assert "退出" in labels


def test_tray_toggle_capture_writes_settings(qapp) -> None:
    window = ReportWindow()
    tray = TrayIcon(window, on_open_settings=lambda: None)
    tray.toggle_capture()
    assert config.load_settings()["capture"]["enabled"] is False
    assert tray._pause_action.text() == "继续采集"
    tray.toggle_capture()
    assert config.load_settings()["capture"]["enabled"] is True


def test_circle_icon_not_null(qapp) -> None:
    assert not circle_icon("#2ecc40").isNull()
