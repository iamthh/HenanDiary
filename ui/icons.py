"""托盘图标：代码画圆点，绿色=正常，红色=AI 失败提示（需求 D14）。

不引入图标资源文件：一个纯色圆点已经够表达状态，资源文件是多余的复杂度。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

SIZE = 32


def circle_icon(color: str) -> QIcon:
    pm = QPixmap(SIZE, SIZE)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(4, 4, SIZE - 8, SIZE - 8)
    painter.end()
    return QIcon(pm)
