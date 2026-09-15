"""单实例运行（需求 F6）。

已有实例在跑时，新进程不再起第二个托盘图标，而是让旧实例把窗口显示出来，自己安静退出。
用 QLocalServer/QLocalSocket——Qt 自带的本地 socket，比手拼 Windows 互斥体省事，
也不用操心残留句柄（残留的 socket 文件名在 listen 前清一次即可）。
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtNetwork import QLocalServer, QLocalSocket

from logger import get_logger

log = get_logger(__name__)

SERVER_NAME = "henandiary-single-instance"
_CONNECT_TIMEOUT_MS = 300


def acquire(on_second_launch: Callable[[], None] | None = None) -> QLocalServer | None:
    """抢占单实例位。已有实例在跑时通知它、返回 None。

    参数：
        on_second_launch: 又有人启动本程序时回调（用来把已有窗口显示出来）
    返回：
        QLocalServer——调用方**必须一直持有引用**，否则对象被回收、监听就断了；
        返回 None 表示已有实例在运行，调用方应直接退出。
    """
    probe = QLocalSocket()
    probe.connectToServer(SERVER_NAME)
    if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
        probe.abort()
        log.info("已有实例在运行，已通知其显示窗口，本次不再启动")
        return None

    # 上次异常退出可能留下同名 socket，listen 前先清掉
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    if on_second_launch is not None:
        server.newConnection.connect(on_second_launch)
    if not server.listen(SERVER_NAME):
        # 单实例是尽力而为，监听失败不该拦住程序启动
        log.warning("单实例监听失败（%s），本次按多实例继续运行", server.errorString())
    return server
