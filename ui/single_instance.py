"""单实例运行（需求 F6）。

已有实例在跑时，新进程通知它把窗口显示出来，自己安静退出。
实现：固定回环端口占位——bind 失败即说明已有实例；通知 = 连上去发一行 "show"。
（原来是 Qt QLocalServer，PySide6 移除后换标准库 socket，行为一致。）
"""

from __future__ import annotations

import socket
import threading
from typing import Callable

from logger import get_logger

log = get_logger(__name__)

HOST, PORT = "127.0.0.1", 45719


def acquire(on_second_launch: Callable[[], None] | None = None) -> socket.socket | None:
    """抢占单实例位，返回监听 socket（调用方必须一直持有，否则监听随对象回收断掉）。

    已有实例在跑：通知它唤窗，返回 None，调用方应直接退出。
    端口被无关程序占用：只记警告，返回 None 之外按多实例放行（同旧版尽力而为语义）——
    区分不了"被别的实例占"和"被别的程序占"，先 connect 探一次能区分。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    try:
        probe.connect((HOST, PORT))
    except OSError:
        pass  # 连不上 = 没有实例在跑
    else:
        try:
            probe.sendall(b"show")
        except OSError:
            pass
        finally:
            probe.close()
        log.info("已有实例在运行，已通知其显示窗口，本次不再启动")
        return None
    probe.close()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
    except OSError:
        server.close()
        # 探不到实例但端口又绑不上：多半是无关程序占用，不拦启动（返回非 None 继续跑）
        log.warning("单实例端口 %s 绑定失败，本次按多实例继续运行", PORT)
        return server

    server.listen(4)

    def loop() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return  # 进程退出，监听随 socket 关闭结束
            conn.close()
            if on_second_launch:
                log.info("收到第二次启动请求，唤起主窗口")
                try:
                    on_second_launch()
                except Exception:
                    log.exception("唤起窗口失败")

    threading.Thread(target=loop, name="single-instance", daemon=True).start()
    return server
