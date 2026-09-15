"""托盘图标 + 右键菜单：查看日报 / 立即生成 / 暂停·继续采集 / 设置 / 退出。

采集开关只改 settings 的 capture.enabled，采集器每轮都重读配置，无需重启（见 screenshot.run_once）。
"""

from __future__ import annotations

from datetime import date as _date

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import config
from logger import get_logger
from report.generator import generate_daily_report
from ui.icons import circle_icon

log = get_logger(__name__)

GREEN = "#2ecc40"
RED = "#e74c3c"


class _GenerateWorker(QThread):
    """后台线程跑日报生成，避免 AI 调用（可能几十秒）卡死托盘。"""

    finished = Signal(dict)

    def run(self) -> None:
        try:
            result = generate_daily_report(_date.today().isoformat())
        except Exception as e:
            log.exception("托盘立即生成日报失败")
            result = {"error": str(e)}
        self.finished.emit(result)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, on_open_settings) -> None:
        super().__init__(circle_icon(GREEN))
        self.setToolTip("HenanDiary")
        self._window = window
        self._worker: _GenerateWorker | None = None
        self._settings_cb = on_open_settings

        menu = QMenu()
        menu.addAction(QAction("查看日报", menu, triggered=self.show_window))
        menu.addAction(QAction("立即生成今日日报", menu, triggered=self.generate_now))
        self._pause_action = QAction("暂停采集", menu, triggered=self.toggle_capture)
        menu.addAction(self._pause_action)
        menu.addAction(QAction("设置", menu, triggered=self._settings_cb))
        menu.addSeparator()
        menu.addAction(QAction("退出", menu, triggered=self._quit))
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self._sync_capture_label()

    def show_window(self) -> None:
        self._window.refresh()
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:  # 单击左键 = 唤出窗口
            self.show_window()

    def toggle_capture(self) -> None:
        enabled = not config.load_settings()["capture"]["enabled"]
        config.update_settings({"capture": {"enabled": enabled}})
        self._sync_capture_label()
        self.showMessage("HenanDiary", "已继续采集" if enabled else "已暂停采集",
                         self.icon(), 3000)

    def _sync_capture_label(self) -> None:
        enabled = config.load_settings()["capture"]["enabled"]
        self._pause_action.setText("暂停采集" if enabled else "继续采集")

    def generate_now(self) -> None:
        if self._worker and self._worker.isRunning():
            self.showMessage("HenanDiary", "日报正在生成中…", self.icon(), 3000)
            return
        self.setIcon(circle_icon(GREEN))
        self._worker = _GenerateWorker()
        self._worker.finished.connect(self._on_generated)
        self._worker.start()

    def _on_generated(self, result: dict) -> None:
        if "error" in result:
            self.setIcon(circle_icon(RED))
            self.showMessage("HenanDiary", f"生成失败：{result['error']}",
                             circle_icon(RED), 5000)
            return
        if result.get("skipped"):
            self.showMessage("HenanDiary", f"未生成：{result['reason']}",
                             self.icon(), 3000)
        else:
            self.showMessage("HenanDiary", "今日日报已生成", self.icon(), 3000)
        self._window.refresh()

    def _quit(self) -> None:
        log.info("托盘退出")
        QApplication.quit()
