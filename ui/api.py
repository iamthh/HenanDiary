"""js_api 桥：Web 界面与后端的唯一通道。

pywebview 把本类实例的公开方法暴露给 window.pywebview.api.*。
全部方法是普通同步 Python，可脱离 webview 单测；窗口/托盘引用用 attach() 注入，
没有它们时各方法照常工作（close/quit 变成空操作），测试因此不用起 GUI。

约定：方法返回可 JSON 序列化的 dict/list；失败不抛异常，统一返回 {"error": "..."}，
让前端拿错误弹 toast 而不是白屏。
"""

from __future__ import annotations

import shutil
import zipfile
from datetime import date as _date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import config
from logger import get_logger
from storage import db

log = get_logger(__name__)


def _parse_work_hours(capture: dict[str, Any]) -> tuple[tuple[int, int], tuple[int, int]]:
    """解析工作时段；历史坏配置回落默认值（与 collector.in_work_hours 同一口径）。"""
    work_hours = capture["work_hours"]
    try:
        return (
            config.parse_hhmm(work_hours["start"], "capture.work_hours.start"),
            config.parse_hhmm(work_hours["end"], "capture.work_hours.end"),
        )
    except (ValueError, KeyError, TypeError):
        fallback = config.DEFAULT_SETTINGS["capture"]["work_hours"]
        log.error(
            "工作时间配置非法 %r，推算下次采集时回落默认 %s-%s",
            work_hours, fallback["start"], fallback["end"],
        )
        return config.parse_hhmm(fallback["start"]), config.parse_hhmm(fallback["end"])


def _next_work_start(now: datetime, start: tuple[int, int]) -> datetime:
    """下一个工作时段开始时刻：今天还没到点就是今天，否则明天。"""
    today_start = now.replace(hour=start[0], minute=start[1], second=0, microsecond=0)
    return today_start if now < today_start else today_start + timedelta(days=1)


def _next_capture_at(now: datetime, capture: dict[str, Any], last_ts: str | None) -> datetime:
    """推算下一次采集时刻，三种情况分开算。

    旧实现只在"当天没有采集记录"时拿工作时段起点当答案，于是下午打开界面会看到
    「下次截图 09:00」这种已经过去的时间。现在：
    - 工作时间外：下一个工作时段开始
    - 工作时间内且有记录：上一条 + 采集间隔；间隔落到了下班之后，就顺延到下一个工作日
    - 工作时间内且当天还没采过（或上一轮已过期）：就是现在，马上要采
    """
    start, end = _parse_work_hours(capture)
    if not (start <= (now.hour, now.minute) < end):
        return _next_work_start(now, start)

    if last_ts:
        candidate = datetime.fromisoformat(last_ts) + timedelta(
            minutes=capture["screenshot_interval_min"]
        )
        if candidate > now:
            if (candidate.hour, candidate.minute) < end:
                return candidate
            return _next_work_start(now, start)  # 这一轮会落在下班后，实际不再采
    return now


class Api:
    def __init__(self) -> None:
        self._window = None                       # pywebview.Window
        self._tray_refresh: Callable[[], None] | None = None  # 托盘红绿点重绘
        self._on_settings_saved: Callable[[], None] | None = None  # 改完时间要重排调度
        self._on_onboarding_done: Callable[[], None] | None = None  # 引导完成后起采集
        self._on_quit: Callable[[], None] | None = None  # 真退出：解除关闭拦截后 destroy
        self._scheduler = None                    # 可选：有调度器时报告下次任务时间
        self._maximized = False                   # 自绘顶栏最大化按钮的状态镜像

    def attach(self, window=None, tray_refresh=None, on_settings_saved=None,
               on_onboarding_done=None, on_quit=None, scheduler=None) -> None:
        self._window = window
        self._tray_refresh = tray_refresh
        self._on_settings_saved = on_settings_saved
        self._on_onboarding_done = on_onboarding_done
        self._on_quit = on_quit
        self._scheduler = scheduler

    # ---------------------------------------------------------- 错误包装

    @staticmethod
    def _guard(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as e:
            log.exception("js_api 调用失败")
            return {"error": f"{type(e).__name__}: {e}"}

    # ---------------------------------------------------------- 总览页

    def get_state(self) -> dict[str, Any]:
        return self._guard(self._state)

    def _state(self) -> dict[str, Any]:
        settings = config.load_settings()
        today = _date.today().isoformat()
        analyses = db.get_today_analyses(today)
        last_ts = analyses[-1]["timestamp"] if analyses else None
        capture = settings["capture"]
        next_ts = None
        if capture["enabled"]:
            now = datetime.now()
            next_ts = _next_capture_at(now, capture, last_ts).isoformat(timespec="seconds")
        report = db.get_daily_report(today)
        pending = db.get_pending_reports()
        return {
            "date": today,
            "onboarding_done": settings["onboarding"]["done"],
            "capture": {
                "enabled": capture["enabled"],
                "interval_min": capture["screenshot_interval_min"],
                "work_hours": capture["work_hours"],
                "count_today": len(analyses),
                "last_ts": last_ts,
                "next_ts": next_ts,
            },
            "report": {
                "daily_time": settings["report"]["daily_time"],
                "overwrite_time": settings["report"]["overwrite_time"],
                "today_generated": report is not None,
                "today_overwritten": bool(report and report["is_overwritten"]),
                "pending": [
                    {"date": p["date"], "type": p["type"], "reason": p["reason"]}
                    for p in pending
                ],
            },
        }

    def toggle_capture(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            enabled = not config.load_settings()["capture"]["enabled"]
            config.update_settings({"capture": {"enabled": enabled}})
            log.info("采集开关切换 enabled=%s", enabled)
            if self._tray_refresh:
                self._tray_refresh()
            return {"enabled": enabled}
        return self._guard(run)

    # ---------------------------------------------------------- 时间线页

    def list_timeline_dates(self) -> Any:
        def run() -> list[dict[str, Any]]:
            days = config.load_settings()["storage"]["raw_retention_days"]
            out = []
            for offset in range(days):
                day = (_date.today() - timedelta(days=offset)).isoformat()
                count = len(db.get_today_analyses(day))
                if count:
                    out.append({"date": day, "count": count})
            return out
        return self._guard(run)

    def get_timeline(self, date: str) -> Any:
        def run() -> list[dict[str, Any]]:
            rows = db.get_today_analyses(date)
            return [{
                "time": r["timestamp"][11:16],
                "analysis": r["analysis"],
                "app": r["app"],
                "category": r["category"],
            } for r in reversed(rows)]  # 需求：从最近一次往下展示
        return self._guard(run)

    # ---------------------------------------------------------- 报表页

    def list_reports(self, kind: str) -> Any:
        def run() -> list[dict[str, Any]]:
            if kind == "weekly":
                return db.list_weekly_reports()
            return db.list_daily_reports()
        return self._guard(run)

    def get_report(self, kind: str, key: str) -> Any:
        def run() -> dict[str, Any]:
            row = db.get_weekly_report(key) if kind == "weekly" else db.get_daily_report(key)
            return row or {"error": "该报表不存在"}
        return self._guard(run)

    def generate(self, kind: str) -> Any:
        """同步跑一次生成（AI 可能要几十秒，前端负责转圈）。失败走调度层同款欠账记账。"""
        def run() -> dict[str, Any]:
            from scheduler import jobs
            if kind == "weekly":
                result = jobs.run_weekly_report(on_ai_failure=self._notify_failure)
            else:
                result = jobs.run_daily_report(on_ai_failure=self._notify_failure)
            if self._tray_refresh:
                self._tray_refresh()
            return result
        return self._guard(run)

    def _notify_failure(self, reason: str) -> None:
        """AI 失败：刷新托盘红点 + 通过事件推给前端（若有窗口）。"""
        if self._tray_refresh:
            self._tray_refresh()

    # ---------------------------------------------------------- 应用统计页

    def get_app_usage(self, date: str) -> Any:
        """某天的应用使用汇总（需求 F7.2）。只给结构化数据，画图归前端。"""

        def run() -> dict[str, Any]:
            rows = db.get_app_usage_summary(date)
            total_s = sum(r["seconds"] for r in rows)
            items = [
                {
                    "app": _friendly_app(r["app"]),
                    "minutes": round(r["seconds"] / 60),
                    "percent": round(r["seconds"] * 100 / total_s, 1) if total_s else 0.0,
                    "samples": r["samples"],
                }
                for r in rows
            ]
            return {
                "date": date,
                "total_min": round(total_s / 60),
                "samples": sum(r["samples"] for r in rows),
                "items": items,
            }

        return self._guard(run)

    # ---------------------------------------------------------- 剪贴板

    def copy_text(self, text: str) -> Any:
        """把文本放进系统剪贴板（报表页「复制全文」用）。

        不走前端 navigator.clipboard：WebView2 对它的权限行为不可控；
        pywin32 本来就是依赖，Python 侧写剪贴板最稳。
        """
        def run() -> dict[str, Any]:
            import win32clipboard

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
            log.info("已复制文本到剪贴板（%d 字）", len(text))
            return {"ok": True}

        return self._guard(run)

    # ---------------------------------------------------------- 设置页

    def get_settings(self) -> Any:
        def run() -> dict[str, Any]:
            s = config.load_settings()
            return {
                "base_url": s["ai"]["base_url"],
                "model": s["ai"]["model"],
                "has_key": bool(s["ai"]["api_key_encrypted"]),
                "screenshot_interval_min": s["capture"]["screenshot_interval_min"],
                "work_hours": s["capture"]["work_hours"],
                "daily_time": s["report"]["daily_time"],
                "overwrite_time": s["report"]["overwrite_time"],
            }
        return self._guard(run)

    def save_settings(self, patch: dict[str, Any]) -> Any:
        """只合并 patch 里出现的键，缺省项不动（Key 留空 = 保留现有 Key）。"""
        def run() -> dict[str, Any]:
            from ai.client import encrypt_key
            merged: dict[str, Any] = {"ai": {}, "capture": {}, "report": {}}
            if "base_url" in patch:
                merged["ai"]["base_url"] = patch["base_url"].strip()
            if "model" in patch:
                merged["ai"]["model"] = patch["model"].strip()
            if patch.get("api_key"):
                merged["ai"]["api_key_encrypted"] = encrypt_key(patch["api_key"])
            if "screenshot_interval_min" in patch:
                merged["capture"]["screenshot_interval_min"] = patch["screenshot_interval_min"]
            if "work_hours" in patch:
                merged["capture"]["work_hours"] = patch["work_hours"]
            for key in ("daily_time", "overwrite_time"):
                if key in patch:
                    merged["report"][key] = patch[key]
            config.update_settings(merged)
            log.info("设置已保存")
            if self._on_settings_saved:
                self._on_settings_saved()
            return {"ok": True}
        return self._guard(run)

    def test_connection(self) -> Any:
        """当场测一次连通性（用已落盘的当前配置；引导页要求先 save 再 test）。"""
        def run() -> dict[str, Any]:
            from ai.client import AIClient
            AIClient().test_connection()
            return {"ok": True}
        return self._guard(run)

    # ---------------------------------------------------------- 数据管理（F4.4）

    def export_data(self) -> Any:
        """全部日报/周报导出为 Markdown + settings.json（不含 Key），打包 zip 落 exports/。"""
        def run() -> dict[str, Any]:
            config.ensure_dirs()
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            zip_path = config.get_exports_dir() / f"henandiary-{stamp}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for row in db.list_daily_reports(limit=10000):
                    full = db.get_daily_report(row["date"])
                    if full:
                        archive.writestr(f"daily/{row['date']}.md", full["content_md"])
                for row in db.list_weekly_reports(limit=1000):
                    full = db.get_weekly_report(row["week_start"])
                    if full:
                        archive.writestr(f"weekly/{row['week_start']}.md", full["content_md"])
                settings = config.load_settings()
                settings["ai"]["api_key_encrypted"] = ""
                archive.writestr("settings.json", _dumps(settings))
            log.info("数据已导出 %s", zip_path)
            return {"path": str(zip_path)}
        return self._guard(run)

    def open_data_dir(self) -> Any:
        def run() -> dict[str, Any]:
            Path(config.get_data_dir()).mkdir(parents=True, exist_ok=True)
            shutil.os.startfile(config.get_data_dir())
            return {"ok": True}
        return self._guard(run)

    def clear_data(self) -> Any:
        """清空全部数据（前端已二次确认）：日报/周报/素材/欠账全删，设置与导出保留。"""
        def run() -> dict[str, Any]:
            conn = db._connect()
            try:
                with conn:
                    for table in ("screenshot_analysis", "daily_report",
                                  "weekly_report", "pending_report"):
                        conn.execute(f"DELETE FROM {table}")
            finally:
                conn.close()
            log.warning("全部数据已清空（设置与导出文件保留）")
            return {"ok": True}
        return self._guard(run)

    # ---------------------------------------------------------- 引导（F5）

    def finish_onboarding(self, base_url: str, model: str, api_key: str) -> Any:
        """写配置 → 测连通 → 测通才放行（onboarding.done）。失败不标记，下次启动重弹。"""
        def run() -> dict[str, Any]:
            patch = {"base_url": base_url, "model": model}
            if api_key:
                patch["api_key"] = api_key
            saved = self.save_settings(patch)
            if isinstance(saved, dict) and "error" in saved:
                return saved
            if not config.load_settings()["ai"]["api_key_encrypted"]:
                return {"error": "请填写 API Key"}
            result = self.test_connection()
            if isinstance(result, dict) and "error" in result:
                return result
            config.update_settings({"onboarding": {"done": True}})
            log.info("首次引导完成")
            if self._on_onboarding_done:
                self._on_onboarding_done()
            return {"ok": True}
        return self._guard(run)

    # ---------------------------------------------------------- 窗口控制

    def quit_app(self) -> Any:
        """用户在关闭询问里选「退出进程」。必须走 on_quit 解除 closing 拦截，
        否则 window.destroy() 触发的 FormClosing 又被拦截回来，窗口关不掉。"""
        if self._on_quit:
            self._on_quit()
        elif self._window:
            self._window.destroy()
        return {"ok": True}

    def minimize_to_tray(self) -> Any:
        if self._window:
            self._window.hide()
        return {"ok": True}

    def minimize(self) -> Any:
        """自绘顶栏的「—」：最小化到任务栏。"""
        if self._window:
            self._window.minimize()
        return {"ok": True}

    def toggle_maximize(self) -> Any:
        """自绘顶栏的「□」：最大化/还原。状态记在这里，Window 属性不可靠。"""
        if self._window:
            if self._maximized:
                self._window.restore()
            else:
                self._window.maximize()
            self._maximized = not self._maximized
        return {"ok": True}

    def show_window(self) -> None:
        if self._window:
            self._window.show()
            self._window.restore()


# ---------------------------------------------------------- 应用名映射

# 进程名 → 界面显示名（需求 F7.2）。只覆盖常见软件，未命中的原样显示——
# 不做模糊匹配：猜错一个应用名比显示原始进程名更糟。
_DISPLAY_NAMES = {
    "Code": "VS Code",
    "chrome": "Chrome",
    "msedge": "Edge",
    "firefox": "Firefox",
    "WeChat": "微信",
    "Weixin": "微信",
    "DingTalk": "钉钉",
    "Feishu": "飞书",
    "Lark": "飞书",
    "winword": "Word",
    "excel": "Excel",
    "powerpnt": "PowerPoint",
    "wps": "WPS",
    "et": "WPS 表格",
    "wpp": "WPS 演示",
    "notepad": "记事本",
    "explorer": "文件资源管理器",
    "WindowsTerminal": "Windows 终端",
    "cmd": "命令提示符",
    "powershell": "PowerShell",
    "pwsh": "PowerShell",
    "pycharm64": "PyCharm",
    "idea64": "IntelliJ IDEA",
    "obsidian": "Obsidian",
    "Telegram": "Telegram",
    "Discord": "Discord",
    "Spotify": "Spotify",
    "mstsc": "远程桌面",
}


def _friendly_app(process_name: str) -> str:
    """进程名转显示名；没命中映射就原样返回。"""
    return _DISPLAY_NAMES.get(process_name, process_name)


def _dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)
