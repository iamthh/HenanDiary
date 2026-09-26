"""前台应用采样（M9 / 需求 F1.3）：取前台窗口进程名 + 空闲剔除 → 写 app_usage 表。

隐私边界（需求 F7.2）：**只取进程名**，不调 GetWindowText、不读 URL、不碰键盘与剪贴板。
进程名只写本地库，不经 AI、不出本机。

调度在 scheduler/jobs.py::run_app_usage（负责工作时间门控），本模块只管采一轮。
与截图采集各自独立：AI 调用失败、截图失败都不影响应用时长记录——用户在用哪个程序是客观事实。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import config
from logger import get_logger
from storage import db

log = get_logger(__name__)

# 需求 F1.3：无键鼠输入超过 5 分钟视为挂机，本轮不计入（暂不做成配置项）
IDLE_THRESHOLD_S = 300

# 取进程路径一律用最低权限句柄。换成 PROCESS_QUERY_INFORMATION(0x400) 时，
# 对以管理员运行的程序（任务管理器、高权限 IDE）会直接失败拿不到名字。
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 排除自身：用户打开本应用看日报时前台就是自己，计入会污染统计
_EXCLUDED_APPS = frozenset({"HenanDiary"})

_MAX_PATH = 260

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def _elapsed_seconds(now_tick: int, last_tick: int) -> float:
    """两个 32 位 tick 计数的差值（秒）。

    GetTickCount 与 GetLastInputInfo 的 dwTime 都是 32 位、约 49.7 天回绕一次，
    相减必须 & 0xFFFFFFFF：否则每隔一个多月会冒出一条"空闲 40 亿秒"，当天统计全废。
    单独抽出来是为了能直接测回绕，不必去伪造 Win32 调用的内存写入。
    """
    return ((now_tick - last_tick) & 0xFFFFFFFF) / 1000.0


def idle_seconds() -> float:
    """系统空闲秒数（最近一次键盘/鼠标输入至今）。

    取不到时返回 0（当作不空闲）——宁可多记，不要因为一次调用失败丢掉整段时长。
    """
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return _elapsed_seconds(_kernel32.GetTickCount(), info.dwTime)


def foreground_process_name() -> str | None:
    """前台窗口所属进程的可执行文件名（不含 .exe）。取不到返回 None。"""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None

    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        log.debug("OpenProcess 失败 pid=%s，本轮跳过", pid.value)
        return None
    try:
        size = wintypes.DWORD(_MAX_PATH)
        buf = ctypes.create_unicode_buffer(_MAX_PATH)
        ok = _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        if not ok:
            log.debug("QueryFullProcessImageNameW 失败 pid=%s，本轮跳过", pid.value)
            return None
        name = Path(buf.value).stem
    finally:
        _kernel32.CloseHandle(handle)
    return name or None


class AppUsageCollector:
    """一轮 = 判开关 → 判空闲 → 取进程名 → 写一条采样记录。"""

    def run_once(self) -> None:
        """执行一轮采样。失败抛异常，由 run_once_safe 兜住。"""
        capture = config.load_settings()["capture"]
        if not capture["enabled"]:
            log.debug("采集已关闭，跳过应用采样")
            return
        if idle_seconds() > IDLE_THRESHOLD_S:
            log.debug("空闲超过 %s 秒，本轮不计入", IDLE_THRESHOLD_S)
            return

        app = foreground_process_name()
        if not app or app in _EXCLUDED_APPS:
            return
        # duration_s 写入时算死，不留给查询侧乘间隔：间隔可配（2/5/10 分钟），
        # 用户改一次设置就会让全部历史时长跟着变，趋势图直接失真（需求 F7.1）
        db.save_app_usage(
            datetime.now().isoformat(timespec="seconds"),
            app,
            capture["screenshot_interval_min"] * 60,
        )

    def run_once_safe(self) -> None:
        """调度入口：吞掉单轮异常但必须落日志，保住后面的每一轮。"""
        try:
            self.run_once()
        except Exception:
            log.exception("本轮应用采样失败，等待下一轮重试")
