"""应用入口。

M1：初始化日志 → 建数据目录 → 建库 → 启动采集调度 → 常驻（Ctrl+C 退出）。
日报生成（M2）、托盘与查看窗口（M3）按 docs/开发状态.md 的顺序接入。
"""

from __future__ import annotations

import sys
import time

import config
from collector.screenshot import ScreenshotCollector, start_scheduler
from logger import get_logger, setup_logging
from storage import db


def main() -> int:
    setup_logging()
    log = get_logger(__name__)

    config.ensure_dirs()
    db.init_db()
    settings = config.load_settings()
    log.info("数据目录=%s，截图间隔=%s 分钟", config.get_data_dir(),
             settings["capture"]["screenshot_interval_min"])

    try:
        collector = ScreenshotCollector()
    except RuntimeError as e:
        log.error("AI 客户端初始化失败：%s（先运行 python tools/set_api_key.py 配 Key）", e)
        return 1

    scheduler = start_scheduler(collector)
    log.info("M1 采集已启动，Ctrl+C 退出")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.shutdown()
        log.info("收到退出信号，调度器已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
