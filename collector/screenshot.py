"""截图采集器：mss 纯内存截图 → AI 分析 → 存 SQLite。

M1 验收目标：程序常驻期间按配置间隔自动采集，工作时间外跳过。
开发规范 1.3：单轮失败只记 error 不抛出，采集循环不能因一次 AI 调用失败而停摆。
调度（采集间隔/日报/周报/清理）统一收在 scheduler/jobs.py，本模块只管采集一轮。
"""

from __future__ import annotations

import base64
from datetime import datetime

import mss
import mss.tools

import config
from ai.client import AIClient
from logger import get_logger
from storage import db

log = get_logger(__name__)


def capture_to_memory() -> bytes:
    """截主显示器 → PNG bytes，全程不落盘（技术方案六.1）。"""
    with mss.MSS() as sct:
        img = sct.grab(sct.monitors[1])
        return mss.tools.to_png(img.rgb, img.size)


def to_base64(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("utf-8")


class ScreenshotCollector:
    """一轮 = 截图 → AI 分析 → 入库。"""

    def __init__(self) -> None:
        self._ai = AIClient()

    @staticmethod
    def in_work_hours(now: datetime, work_hours: dict) -> bool:
        start = datetime.strptime(work_hours["start"], "%H:%M").time()
        end = datetime.strptime(work_hours["end"], "%H:%M").time()
        return start <= now.time() < end  # ponytail: 不跨天，09-19 这种够用

    def run_once(self) -> None:
        """执行一轮采集。非工作时间直接跳过；失败抛异常由调度层记日志。"""
        settings = config.load_settings()
        capture = settings["capture"]
        now = datetime.now()
        if not capture["enabled"]:
            log.debug("采集已关闭，跳过")
            return
        if not self.in_work_hours(now, capture["work_hours"]):
            log.debug("不在工作时间 %s-%s，跳过",
                      capture["work_hours"]["start"], capture["work_hours"]["end"])
            return

        png = capture_to_memory()
        try:
            analysis = self._ai.analyze_image(to_base64(png))
        finally:
            del png  # 用完立即释放（技术方案六.1）
        if not analysis.strip():
            raise ValueError("AI 返回空描述，视为失败")
        db.save_screenshot_analysis(now.isoformat(timespec="seconds"), analysis.strip())

    def run_once_safe(self) -> None:
        """调度入口：吞掉单轮异常但必须落日志，保住后面的每一轮。"""
        try:
            self.run_once()
        except Exception:
            log.exception("本轮截图采集失败，等待下一轮重试")
