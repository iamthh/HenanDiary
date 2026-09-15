"""应用入口。

默认：初始化日志 → 建目录建库 → 首次引导（未完成时）→ 启动采集与定时调度 → 托盘常驻。
引导未走完（settings.onboarding.done）时不启动采集（需求 F5）。
启动时在后台补跑漏掉的生成任务，不阻塞界面（需求 D14 / F2.1）。
--gen-report [日期]：手动生成指定日期（默认今天）的日报后退出。
--settings：打开设置窗口。
"""

from __future__ import annotations

import argparse
import sys
import threading
from datetime import date as _date

import config
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
        log.error("生成失败：%s（先完成首次引导或在设置窗口配 Key）", e)
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


def _build_failure_bridge():
    """把调度线程里的 AI 失败转成 Qt 信号。

    调度任务跑在后台线程，直接改托盘控件不安全；Signal 跨线程 emit 会自动排队到
    接收者所在线程（主线程）执行。
    """
    from PySide6.QtCore import QObject, Signal

    class _FailureBridge(QObject):
        failed = Signal(str)

    return _FailureBridge()


def _startup_catch_up(bridge) -> None:
    """启动补跑（后台线程）：先销 AI 失败欠账，再补压根没跑的日报。

    线程自己先建库——它跑在主流程之外，不能假设 init_db 已经在自己这一轮之前完成。
    """
    from scheduler import jobs

    log = get_logger(__name__)
    try:
        db.init_db()
        jobs.retry_pending(on_ai_failure=bridge.failed.emit)
        jobs.catch_up_missed_reports(on_ai_failure=bridge.failed.emit)
    except Exception:
        log.exception("启动补生成失败")


def _run_ui(open_settings_only: bool) -> int:
    """GUI 模式：--settings 只开设置窗；默认引导 → 采集+调度 → 托盘常驻。"""
    from PySide6.QtWidgets import QApplication

    from ui.main_window import ReportWindow
    from ui.settings import SettingsDialog
    from ui.single_instance import acquire as _acquire_single_instance
    from ui.tray import TrayIcon

    log = get_logger(__name__)
    config.ensure_dirs()
    db.init_db()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if open_settings_only:
        SettingsDialog().exec()
        return 0

    if not config.load_settings()["onboarding"]["done"]:
        from ui.onboarding import OnboardingWizard
        OnboardingWizard().exec()

    window = ReportWindow()
    scheduler = None

    def open_settings() -> None:
        nonlocal scheduler
        SettingsDialog(window).exec()
        if scheduler is not None:  # 改了日报/覆盖时间要立刻重排，否则仍按启动时的时刻跑
            _jobs.reschedule_report_jobs(scheduler)

    tray = TrayIcon(window, on_open_settings=open_settings)
    bridge = _build_failure_bridge()
    bridge.failed.connect(tray.on_ai_failure)

    # 需求 F6：单实例。已有实例在跑就让它把窗口显示出来，本次不再起第二个托盘。
    # 返回值需一直持有（见 ui.single_instance.acquire 的说明），否则监听会随对象回收断掉。
    instance_server = _acquire_single_instance(tray.show_window)
    if instance_server is None:
        log.info("已有实例在运行，本次启动直接退出")
        return 0

    ready = config.load_settings()["onboarding"]["done"]
    if ready:
        try:
            from collector.screenshot import ScreenshotCollector
            from scheduler import jobs as _jobs

            collector = ScreenshotCollector()
            scheduler = _jobs.build_scheduler(collector, on_ai_failure=bridge.failed.emit)
        except RuntimeError as e:  # 引导被跳过 / Key 未配
            log.error("采集未启动：%s（完成引导或在设置里配 Key）", e)
            ready = False
    else:
        log.info("引导未完成，采集暂不启动")

    tray.show()
    if not tray.isSystemTrayAvailable():  # 无托盘环境（测试/精简系统）退化为直接开窗口
        log.warning("系统托盘不可用，直接显示日报窗口")
        window.show()

    if ready and scheduler is not None:
        threading.Thread(
            target=_startup_catch_up, args=(bridge,), name="startup-catchup", daemon=True
        ).start()

    log.info("托盘常驻中，退出请走托盘菜单")
    code = app.exec()
    if scheduler:
        scheduler.shutdown(wait=False)
    log.info("进程退出 code=%s", code)
    return code


def main(argv: list[str] = []) -> int:
    parser = argparse.ArgumentParser(prog="henandiary")
    parser.add_argument("--gen-report", nargs="*", metavar="YYYY-MM-DD",
                        help="手动生成指定日期（默认今天）的日报后退出")
    parser.add_argument("--settings", action="store_true", help="打开设置窗口")
    # 默认空参数=常驻模式，测试调 main() 不会被 pytest 的命令行参数干扰
    args = parser.parse_args(argv)

    setup_logging()
    if args.gen_report is not None:
        return _gen_report(args.gen_report)
    if args.settings:
        return _run_ui(open_settings_only=True)
    return _run_ui(open_settings_only=False)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
