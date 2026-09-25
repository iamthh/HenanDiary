"""截图采集器：mss 纯内存截图 → 压缩 → AI 分析 → 解析结构化字段 → 存 SQLite。

M1 验收目标：程序常驻期间按配置间隔自动采集，工作时间外跳过。
开发规范 1.3：单轮失败只记 error 不抛出，采集循环不能因一次 AI 调用失败而停摆。
调度（采集间隔/日报/周报/清理）统一收在 scheduler/jobs.py，本模块只管采集一轮。

压缩与解析都是本模块的职责而非 AI 层的：技术方案六.1 要求"截图只在内存里处理"，
缩图与转码同样全程在内存完成，落盘的依然只有 AI 产出的文字。
AI 返回的 JSON 由 parse_analysis 解析并容错——模型多说了半句话不该让这一轮素材作废。
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import mss
import mss.tools
from PIL import Image

import config
from ai.client import AIClient, IMAGE_ANALYSIS_CATEGORIES, OTHER_CATEGORY
from logger import get_logger
from storage import db

log = get_logger(__name__)

# 送 AI 前的压缩目标。视觉模型的输入成本随像素量走：1920x1080 原图 PNG base64 后约 1.22MB，
# 缩到宽 1024 转 JPEG(q80) 只要约 0.11MB（实测降约 91%），屏幕文字依然清晰可辨。
MAX_AI_IMAGE_WIDTH = 1024
AI_IMAGE_JPEG_QUALITY = 80
AI_IMAGE_MIME = "image/jpeg"


def capture_to_memory() -> bytes:
    """截主显示器 → PNG bytes，全程不落盘（技术方案六.1）。"""
    with mss.MSS() as sct:
        img = sct.grab(sct.monitors[1])
        return mss.tools.to_png(img.rgb, img.size)


def shrink_for_ai(png_bytes: bytes) -> bytes:
    """把截图缩到 AI 友好尺寸并转 JPEG，返回新字节流（同样只在内存里）。

    为什么不直传原图：按 96 张/天、原图 base64 1.22MB 算，一天上传约 117MB，
    而缩到宽 1024 后约 0.11MB。省的是带宽与 token，不是清晰度——
    本工具的用途是"让模型看出你在干什么"，不需要 1:1 像素。
    """
    with Image.open(io.BytesIO(png_bytes)) as image:
        rgb = image.convert("RGB")
        if rgb.width > MAX_AI_IMAGE_WIDTH:
            height = max(1, round(rgb.height * MAX_AI_IMAGE_WIDTH / rgb.width))
            rgb = rgb.resize((MAX_AI_IMAGE_WIDTH, height), Image.LANCZOS)
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=AI_IMAGE_JPEG_QUALITY, optimize=True)
        return buffer.getvalue()


def to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


@dataclass(frozen=True)
class ScreenAnalysis:
    """一轮截图分析的解析结果。app / category 允许缺失，desc 必须有内容。"""

    desc: str
    app: str | None = None
    category: str | None = None


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """捞出输出里的第一个 JSON 对象。

    允许两种真实形态：前面夹着客套话（`好的，这张图…{"..."}`）、裹在 ```json 代码块里。
    用 raw_decode 而不是先剥代码块再 loads，是因为它对"JSON 后面还有文字"同样能解析。
    """
    start = text.find("{")
    if start == -1:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_analysis(raw: str) -> ScreenAnalysis:
    """解析 AI 返回的结构化描述；解析不出来就整段当描述用。

    为什么必须容错：采集每 5 分钟一轮、没有人工兜底，宁可存一条没结构但可读的记录，
    也不能因为模型多说半句就丢掉这一轮素材（`run_once` 会把空 desc 判为失败）。
    category 不在封闭集合内的一律归「其他」，否则本地统计会冒出野生类别名。
    """
    text = raw.strip()
    data = _extract_json_object(text)
    if data is None:
        return ScreenAnalysis(desc=text)

    desc = str(data.get("desc") or "").strip()
    app = str(data.get("app") or "").strip() or None
    category = str(data.get("category") or "").strip()
    if category and category not in IMAGE_ANALYSIS_CATEGORIES:
        category = OTHER_CATEGORY

    if not desc:
        # 结构对了但描述空着：拿 app 兜一句，照样是一条可用素材
        desc = f"正在使用 {app}" if app else text
    return ScreenAnalysis(desc=desc, app=app, category=category or None)


class ScreenshotCollector:
    """一轮 = 截图 → AI 分析 → 入库。"""

    def __init__(self) -> None:
        self._ai = AIClient()

    @staticmethod
    def in_work_hours(now: datetime, work_hours: dict) -> bool:
        """是否落在工作时段内（不支持跨天，09:00-19:00 这种够用）。

        配置非法时回落默认时段并记 error：校验上线前写入的坏值不能让采集长期瘫掉，
        而"永远不采集"正是最难被发现的失效形态。
        """
        try:
            start = config.parse_hhmm(work_hours["start"], "capture.work_hours.start")
            end = config.parse_hhmm(work_hours["end"], "capture.work_hours.end")
        except (ValueError, KeyError, TypeError):
            fallback = config.DEFAULT_SETTINGS["capture"]["work_hours"]
            log.error(
                "工作时间配置非法 %r，本轮回落默认 %s-%s", work_hours, fallback["start"], fallback["end"]
            )
            start = config.parse_hhmm(fallback["start"])
            end = config.parse_hhmm(fallback["end"])
        return start <= (now.hour, now.minute) < end

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
            jpeg = shrink_for_ai(png)
        finally:
            del png  # 原图用完立即释放（技术方案六.1）
        raw = self._ai.analyze_image(to_base64(jpeg), mime=AI_IMAGE_MIME)
        del jpeg
        parsed = parse_analysis(raw)
        if not parsed.desc:
            raise ValueError("AI 返回空描述，视为失败")
        db.save_screenshot_analysis(
            now.isoformat(timespec="seconds"),
            parsed.desc,
            app=parsed.app,
            category=parsed.category,
        )

    def run_once_safe(self) -> None:
        """调度入口：吞掉单轮异常但必须落日志，保住后面的每一轮。"""
        try:
            self.run_once()
        except Exception:
            log.exception("本轮截图采集失败，等待下一轮重试")
