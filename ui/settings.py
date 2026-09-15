"""设置窗口：AI 接口、截图间隔、工作时间、日报生成时间。

保存走 config.update_settings（非法间隔会被拒）；Key 经 DPAPI 加密后才落盘。
"""

from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QComboBox, QFormLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QPushButton, QTimeEdit, QVBoxLayout, QWidget,
)

import config
from ai.client import AIClient, encrypt_key
from logger import get_logger

log = get_logger(__name__)


def _parse_hhmm(text: str) -> QTime:
    h, _, m = text.partition(":")
    return QTime(int(h), int(m))


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        settings = config.load_settings()

        self._url = QLineEdit(settings["ai"]["base_url"])
        self._model = QLineEdit(settings["ai"]["model"])
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.Password)
        self._key.setPlaceholderText("留空表示不修改")
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self.test_connection)
        key_row = QHBoxLayout()
        key_row.addWidget(self._key)
        key_row.addWidget(test_btn)

        self._interval = QComboBox()
        for minute in sorted(config.ALLOWED_INTERVAL_MIN):
            self._interval.addItem(f"{minute} 分钟", minute)
        idx = self._interval.findData(settings["capture"]["screenshot_interval_min"])
        self._interval.setCurrentIndex(max(idx, 0))

        self._work_start = QTimeEdit(_parse_hhmm(settings["capture"]["work_hours"]["start"]))
        self._work_end = QTimeEdit(_parse_hhmm(settings["capture"]["work_hours"]["end"]))
        self._daily_time = QTimeEdit(_parse_hhmm(settings["report"]["daily_time"]))
        self._daily_time.setDisplayFormat("HH:mm")
        self._work_start.setDisplayFormat("HH:mm")
        self._work_end.setDisplayFormat("HH:mm")

        form = QFormLayout()
        form.addRow("Base URL", self._url)
        form.addRow("模型名", self._model)
        form.addRow("API Key", key_row)
        form.addRow("截图间隔", self._interval)
        form.addRow("工作时间起", self._work_start)
        form.addRow("工作时间止", self._work_end)
        form.addRow("日报生成时间", self._daily_time)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def test_connection(self) -> None:
        """当场试一次最短对话。有改动时先落盘，保证测的是界面上的新配置。"""
        try:
            self._apply()
            AIClient().test_connection()
        except Exception as e:
            log.exception("测试连接失败")
            QMessageBox.warning(self, "测试连接", f"失败：{e}")
            return
        QMessageBox.information(self, "测试连接", "成功：接口可用")

    def save(self) -> None:
        try:
            self._apply()
        except Exception as e:
            log.exception("保存设置失败")
            QMessageBox.warning(self, "设置", f"保存失败：{e}")
            return
        log.info("设置已保存")
        self.accept()

    def _apply(self) -> None:
        patch: dict = {
            "ai": {
                "base_url": self._url.text().strip(),
                "model": self._model.text().strip(),
            },
            "capture": {
                "screenshot_interval_min": self._interval.currentData(),
                "work_hours": {
                    "start": self._work_start.time().toString("HH:mm"),
                    "end": self._work_end.time().toString("HH:mm"),
                },
            },
            "report": {"daily_time": self._daily_time.time().toString("HH:mm")},
        }
        if self._key.text():
            patch["ai"]["api_key_encrypted"] = encrypt_key(self._key.text())
        config.update_settings(patch)
