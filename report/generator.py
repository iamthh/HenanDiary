"""日报生成器：读当日截图分析 → 构造 Prompt → 调 AI → 存库。

M2 验收目标：手动触发能生成一份带三个板块（今日概览/主要工作块/时间分布）的 Markdown 日报。
失败态不在本模块处理：AI 调用失败直接抛异常，pending_report 欠账由 M5 调度层补。
"""

from __future__ import annotations

import json
from typing import Any

import config
from ai.client import AIClient
from logger import get_logger
from storage import db

log = get_logger(__name__)

PROMPT_TEMPLATE = """以下是用户 {date} 一天的电脑使用截图分析记录，共 {count} 条。
请据此生成一份中文日报，严格包含以下三个 Markdown 二级标题板块：

## 今日概览
一句话总结今天主要做了什么。

## 主要工作块
按项目/任务聚类，列出每块在什么时间段做了什么。

## 时间分布
估算各类活动（如编码、沟通、浏览、文档等）的占比，合计约 100%。

正文最后另起一段，输出一个 ```json 代码块，字段如下（供程序汇总，不含多余文字）：
{{"overview": "概览一句话",
 "blocks": [{{"topic": "任务名", "start": "HH:MM", "end": "HH:MM"}}],
 "distribution": [{{"category": "类别", "percent": 数字}}]}}

记录：
{records}
"""


def _build_prompt(date: str, analyses: list[dict[str, Any]]) -> str:
    records = "\n".join(f"- [{a['timestamp']}] {a['analysis']}" for a in analyses)
    return PROMPT_TEMPLATE.format(date=date, count=len(analyses), records=records)


def _split_md_and_json(text: str) -> tuple[str, str]:
    """从 AI 输出里分离 Markdown 正文与 JSON 代码块。

    解析不到合法 JSON 时，content_json 退回 "{}" 并记 warning，不阻塞日报落库。
    """
    marker = "```json"
    idx = text.find(marker)
    if idx == -1:
        log.warning("AI 未输出 json 代码块，content_json 置空")
        return text.strip(), "{}"
    content_md = text[:idx].strip()
    tail = text[idx + len(marker):]
    end = tail.find("```")
    raw = tail[:end] if end != -1 else tail
    try:
        json.loads(raw)  # 只做合法性校验，原样存字符串交给周报侧解析
        return content_md, raw.strip()
    except json.JSONDecodeError:
        log.warning("AI 的 json 代码块不合法，content_json 置空")
        return content_md, "{}"


def generate_daily_report(date: str, ai: AIClient | None = None) -> dict[str, Any]:
    """生成指定日期的日报并落库，返回 db.get_daily_report(date)。

    当日无素材时跳过生成、不落库，返回 {"skipped": True, "reason": ...}。
    幂等：同一天重复生成覆盖旧行（db 层按 date 唯一）。
    """
    analyses = db.get_today_analyses(date)
    if not analyses:
        log.info("date=%s 无截图分析素材，跳过日报生成", date)
        return {"skipped": True, "reason": "当日无采集素材"}

    client = ai or AIClient()
    output = client.analyze_text(_build_prompt(date, analyses))
    content_md, content_json = _split_md_and_json(output)
    db.save_daily_report(date, content_md, content_json)
    log.info("日报生成完成 date=%s 素材=%d条", date, len(analyses))
    result = db.get_daily_report(date)
    assert result is not None  # 刚落库，必存在
    return result
