"""应用入口（M8：Web UI 版）。

默认：初始化日志 → 建目录建库 → 单实例占位 → 弹主窗口（pywebview）→ 托盘常驻（pystray）
→ 后台跑采集与定时调度（scheduler/jobs）。引导未完成时前端停在引导页，采集不启动（需求 F5）。
关闭窗口弹询问：退出进程 / 最小化到托盘。
--gen-report [日期]：手动生成指定日期（默认今天）的日报后退出。
"""

from __future__ import annotations

import argparse
import sys
import threading
from datetime import date as _date
from pathlib import Path

import config
from logger import get_logger, setup_logging
from storage import db

log = get_logger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"


def _gen_report(argv: list[str]) -> int:
    """手动生成日报。返回进程退出码。（与旧 CLI 行为一致，无 GUI。）"""
    config.ensure_dirs()
    db.init_db()
    target = argv[0] if argv else _date.today().isoformat()

    from report.generator import generate_daily_report

    try:
        result = generate_daily_report(target)
    except RuntimeError as e:  # 未配 Key 等初始化错误
        log.error("生成失败：%s（先完成首次引导或在设置里配 Key）", e)
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


# ------------------------------------------------------------------ 托盘

GREEN, RED = (46, 204, 64), (231, 76, 60)


def _circle_image(color: tuple[int, int, int]):
    """代码画圆点（绿色=正常 / 红色=AI 失败，需求 D14），零图标资源文件。"""
    from PIL import Image, ImageDraw

    size = 32
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 5, size - 5], fill=color + (255,))
    return img


def _build_tray(window, api, scheduler_box):
    """建 pystray 托盘。图标刷新读 settings + 欠账表，菜单动作复用 api。"""
    import pystray

    def current_color():
        if db.get_pending_reports():
            return RED
        return GREEN

    icon = pystray.Icon(
        "HenanDiary",
        _circle_image(current_color()),
        "HenanDiary",
        menu=pystray.Menu(
            pystray.MenuItem("打开主窗口", lambda: (window.show(), window.restore()), default=True),
            pystray.MenuItem(
                lambda item: "暂停采集" if config.load_settings()["capture"]["enabled"] else "继续采集",
                lambda: api.toggle_capture(),
            ),
            pystray.MenuItem("退出", lambda: (icon.stop(), api.quit_app())),
        ),
    )

    def refresh() -> None:
        try:
            icon.icon = _circle_image(current_color())
        except Exception:  # 托盘尚未跑起来（如测试环境）不影响主流程
            log.debug("托盘图标刷新跳过", exc_info=True)

    icon.refresh = refresh  # api._tray_refresh 用
    threading.Thread(target=icon.run, name="tray", daemon=True).start()
    return icon


# ------------------------------------------------------------------ 调度启停

def _start_scheduler(api, scheduler_box, collector_cls=None) -> None:
    """Key 配好后起调度。重复调用安全：已在跑就不动。"""
    if scheduler_box.get("scheduler") is not None:
        return
    try:
        from collector.screenshot import ScreenshotCollector
        from scheduler import jobs

        collector = (collector_cls or ScreenshotCollector)()
        scheduler = jobs.build_scheduler(collector, on_ai_failure=_make_failure_hook(api))
        scheduler_box["scheduler"] = scheduler
        threading.Thread(
            target=_startup_catch_up, args=(api,), name="startup-catchup", daemon=True
        ).start()
    except RuntimeError as e:  # Key 未配
        log.error("采集未启动：%s（完成引导或在设置里配 Key）", e)
    except Exception:
        log.exception("调度启动失败")


def _make_failure_hook(api):
    def hook(reason: str) -> None:
        log.warning("AI 调用失败（需求 D14）：%s", reason)
        refresh = getattr(api, "_tray_refresh", None)
        if refresh:
            refresh()

    return hook


def _startup_catch_up(api) -> None:
    """启动补跑（后台线程）：先销 AI 失败欠账，再补压根没跑的日报（需求 D14 / F2.1）。"""
    from scheduler import jobs

    try:
        db.init_db()
        hook = _make_failure_hook(api)
        jobs.retry_pending(on_ai_failure=hook)
        jobs.catch_up_missed_reports(on_ai_failure=hook)
    except Exception:
        log.exception("启动补生成失败")


# ------------------------------------------------------------------ 主窗口

def _run_ui() -> int:
    import webview

    from ui.api import Api
    from ui.single_instance import acquire

    config.ensure_dirs()
    db.init_db()
    api = Api()
    scheduler_box: dict = {"scheduler": None}

    def reschedule() -> None:
        from scheduler import jobs

        scheduler = scheduler_box.get("scheduler")
        if scheduler is not None:
            jobs.reschedule_report_jobs(scheduler)

    def show_window() -> None:
        api.show_window()

    instance_server = acquire(show_window)
    if instance_server is None:
        log.info("已有实例在运行，本次启动直接退出")
        return 0

    window = webview.create_window(
        "HenanDiary",
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=1100,
        height=720,
        min_size=(900, 560),
        text_select=True,
        frameless=True,        # 原生标题栏整个去掉，顶栏由 HTML 自绘
        easy_drag=False,       # 只允许拖 .pywebview-drag-region（logo 行），避免点按钮误拖
    )

    flags: dict = {"quitting": False}

    def on_closing() -> bool:
        """点 X / Alt+F4：取消真关闭，让前端弹「退出进程 / 最小化到托盘」询问（需求 M8）。

        两个坑（pywebview 6.2.1 源码踩过）：
        1. closing 事件语义反直觉（webview/event.py Event.set）：handler 返回 False 才
           置 args.Cancel=True 取消关闭；拦截返回 False、放行真退出返回 True。
        2. FormClosing 在 WinForms UI 线程回调，而 evaluate_js 要等 UI 线程泵消息——
           同步调用 = 死锁，窗口整体卡死（按钮全无响应）。必须另起线程。
        """
        if flags["quitting"]:
            return True
        threading.Thread(
            target=lambda: window.evaluate_js("showCloseAsk && showCloseAsk()"),
            name="close-ask", daemon=True).start()
        return False  # 取消原生关闭

    window.events.closing += on_closing

    def quit_for_real() -> None:
        flags["quitting"] = True
        window.destroy()

    tray = None
    try:
        tray = _build_tray(window, api, scheduler_box)
        api.attach(
            window=window,
            tray_refresh=lambda: getattr(tray, "refresh", lambda: None)(),
            on_settings_saved=reschedule,
            on_onboarding_done=lambda: _start_scheduler(api, scheduler_box),
            on_quit=quit_for_real,
        )
    except Exception:
        log.exception("托盘启动失败（继续跑，仅无托盘）")

    if config.load_settings()["onboarding"]["done"]:
        _start_scheduler(api, scheduler_box)

    log.info("主窗口启动，引导完成=%s", config.load_settings()["onboarding"]["done"])
    try:
        webview.start()  # 阻塞到窗口关闭（前端点「退出进程」→ api.quit_app → destroy）
    finally:
        scheduler = scheduler_box.get("scheduler")
        if scheduler:
            scheduler.shutdown(wait=False)
        if tray:
            tray.stop()
        instance_server.close()
        log.info("进程退出")
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
    return _run_ui()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
