"""日报/周报查看窗口：QTextBrowser 渲染 Markdown（需求 D15 / F4.3）。

侧栏下拉切换日报与周报，列出历史（list_daily_reports / list_weekly_reports），
点击加载正文（get_daily_report / get_weekly_report）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QListWidget, QListWidgetItem, QTextBrowser, QVBoxLayout,
    QWidget,
)

from logger import get_logger
from storage import db

log = get_logger(__name__)

EMPTY_HINT = {"daily": "今天还没有日报。", "weekly": "还没有周报。"}


class ReportWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HenanDiary 报表")
        self.resize(900, 600)

        self._kind = QComboBox()
        self._kind.addItem("日报", "daily")
        self._kind.addItem("周报", "weekly")
        self._kind.currentIndexChanged.connect(lambda _index: self.refresh())

        self._list = QListWidget()
        self._view = QTextBrowser()

        side = QWidget()
        side.setMaximumWidth(200)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(self._kind)
        side_layout.addWidget(self._list)

        layout = QHBoxLayout(self)
        layout.addWidget(side)
        layout.addWidget(self._view)
        self._list.currentItemChanged.connect(self._on_select)

    def closeEvent(self, event) -> None:  # 关窗只隐藏，进程常驻托盘
        event.ignore()
        self.hide()

    def current_kind(self) -> str:
        """当前侧栏类别，"daily" 或 "weekly"。"""
        return self._kind.currentData()

    def refresh(self) -> None:
        """重拉当前类别的目录，尽量保持原选中项。"""
        selected = self._list.currentItem()
        keep = selected.text() if selected else None
        self._list.blockSignals(True)
        self._list.clear()
        rows = db.list_daily_reports() if self.current_kind() == "daily" else db.list_weekly_reports()
        for row in rows:
            QListWidgetItem(row["date"] if "date" in row else row["week_start"], self._list)
        self._list.blockSignals(False)
        if self._list.count() == 0:
            self._view.setPlainText(EMPTY_HINT[self.current_kind()])
            return
        target = 0
        if keep:
            found = self._list.findItems(keep, Qt.MatchExactly)
            if found:
                target = self._list.row(found[0])
        self._list.setCurrentRow(target)

    def _on_select(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        if self.current_kind() == "daily":
            report = db.get_daily_report(item.text())
        else:
            report = db.get_weekly_report(item.text())
        if report:
            self._view.setMarkdown(report["content_md"])
            if report.get("is_overwritten"):
                log.info("展示的是 00:30 补生成版 date=%s", item.text())
        else:
            self._view.setPlainText("读取该报表失败，详见日志。")
