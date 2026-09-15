"""单实例运行测试（需求 F6）。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from ui.single_instance import SERVER_NAME, acquire


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def test_first_acquire_wins_and_second_is_rejected(qapp) -> None:
    server = acquire()
    assert server is not None
    try:
        assert acquire() is None  # 已在监听，第二个抢位的必须被拒
    finally:
        server.close()


def test_second_launch_triggers_callback(qapp) -> None:
    """有人再启动本程序时，已有实例应收到通知（用它把自己的窗口显示出来）。"""
    hits: list[int] = []
    server = acquire(lambda: hits.append(1))
    assert server is not None
    try:
        probe = QLocalSocket()
        probe.connectToServer(SERVER_NAME)
        assert probe.waitForConnected(500)
        assert server.waitForNewConnection(500)
        probe.abort()
        assert hits == [1]
    finally:
        server.close()


def test_acquire_after_release_is_allowed(qapp) -> None:
    """上一个实例退出（server 关闭）后，新的启动要能正常抢到。"""
    first = acquire()
    assert first is not None
    first.close()
    second = acquire()
    assert second is not None
    second.close()
