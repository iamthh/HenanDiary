"""日报查看窗口：QTextBrowser 渲染 Markdown（需求 D15）。

侧栏列出历史日报（list_daily_reports），点击加载正文（get_daily_report）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QTextBrowser, QWidget,
)

from logger import get_logger
from storage import db

log = get_logger(__name__)


class ReportWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HenanDiary 日报")
        self.resize(900, 600)

        self._list = QListWidget()
        self._list.setMaximumWidth(200)
        self._view = QTextBrowser()

        layout = QHBoxLayout(self)
        layout.addWidget(self._list)
        layout.addWidget(self._view)
        self._list.currentItemChanged.connect(self._on_select)

    def closeEvent(self, event) -> None:  # 关窗只隐藏，进程常驻托盘
        event.ignore()
        self.hide()

    def refresh(self) -> None:
        """重拉日报目录，尽量保持原选中日期。"""
        selected = self._list.currentItem()
        keep = selected.text() if selected else None
        self._list.blockSignals(True)
        self._list.clear()
        for row in db.list_daily_reports():
            QListWidgetItem(row["date"], self._list)
        self._list.blockSignals(False)
        if self._list.count() == 0:
            self._view.setPlainText("今天还没有日报。")
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
        report = db.get_daily_report(item.text())
        if report:
            self._view.setMarkdown(report["content_md"])
            if report["is_overwritten"]:
                log.info("展示的是 00:30 补生成版 date=%s", item.text())
        else:
            self._view.setPlainText("读取该日报失败，详见日志。")
