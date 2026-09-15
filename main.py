"""应用入口。

默认：初始化日志 → 建数据目录 → 建库 → 启动采集调度 → 常驻（Ctrl+C 退出）。
--gen-report [日期]：手动生成指定日期（默认今天）的日报后退出，M3 托盘"立即生成"复用同一路径。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date as _date

import config
from collector.screenshot import ScreenshotCollector, start_scheduler
from logger import get_logger, setup_logging
from storage import db


def _gen_report(argv: list[str]) -> int:
    """手动生成日报。返回进程退出码。"""
    log = get_logger(__name__)
    config.ensure_dirs()
    db.init_db()
    target = argv[0] if argv else _date.today().isoformat()

    from report.generator import generate_daily_report

    try:
        result = generate_daily_report(target)
    except RuntimeError as e:  # 未配 Key 等初始化错误
        log.error("生成失败：%s（先运行 python tools/set_api_key.py 配 Key）", e)
        return 1
    except Exception:
        log.exception("日报生成失败 date=%s", target)
        return 1

    if result.get("skipped"):
        log.info("未生成：%s", result["reason"])
        return 0
    log.info("日报已生成 date=%s", target)
    print(result["content_md"])
    return 0


def main(argv: list[str] = []) -> int:
    parser = argparse.ArgumentParser(prog="henandiary")
    parser.add_argument("--gen-report", nargs="*", metavar="YYYY-MM-DD",
                        help="手动生成指定日期（默认今天）的日报后退出")
    # 默认空参数=常驻模式，测试调 main() 不会被 pytest 的命令行参数干扰
    args = parser.parse_args(argv)

    setup_logging()
    if args.gen_report is not None:
        return _gen_report(args.gen_report)

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
    sys.exit(main(sys.argv[1:]))
