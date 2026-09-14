"""应用入口。

M0 骨架：初始化日志 → 建数据目录 → 加载配置 → 打印关键路径。
采集（M1）、日报生成（M2）、托盘与查看窗口（M3）按 docs/开发状态.md 的顺序接入。
"""

from __future__ import annotations

import sys

import config
from logger import get_logger, setup_logging


def main() -> int:
    setup_logging()
    log = get_logger(__name__)

    config.ensure_dirs()
    settings = config.load_settings()

    log.info("启动完成，数据目录=%s", config.get_data_dir())
    log.info(
        "当前配置：截图间隔=%s 分钟，工作时间=%s-%s，日报时间=%s",
        settings["capture"]["screenshot_interval_min"],
        settings["capture"]["work_hours"]["start"],
        settings["capture"]["work_hours"]["end"],
        settings["report"]["daily_time"],
    )
    log.info("M0 骨架就绪：截图采集、日报生成、托盘界面尚未实现")
    return 0


if __name__ == "__main__":
    sys.exit(main())
