"""日报/周报生成器：读素材 → 构造 Prompt → 调 AI → 存库。

M2 验收目标：手动触发能生成一份带三个板块（今日概览/主要工作块/时间分布）的 Markdown 日报。
M6 追加周报：汇总该周已生成的日报正文，周日 22:30 由调度层触发。
失败态不在本模块处理：AI 调用失败直接抛异常，pending_report 欠账由 M5 调度层补。
"""

from __future__ import annotations

import json
from datetime import date as _date, timedelta
from typing import Any

import config
from ai.client import AIClient, IMAGE_ANALYSIS_CATEGORIES, OTHER_CATEGORY
from logger import get_logger
from storage import db

log = get_logger(__name__)

PROMPT_TEMPLATE = """以下是用户 {date} 一天的电脑使用截图分析记录，共 {count} 条，每条带活动分类。
请据此生成一份中文日报，严格包含以下三个 Markdown 二级标题板块：

## 今日概览
一句话总结今天主要做了什么。

## 主要工作块
按项目/任务聚类，列出每块在什么时间段做了什么。

## 时间分布
直接采用下面给出的「本地统计」，它是按分类逐条计数算出来的，不要自己重新估算。
逐项列出即可。

正文最后另起一段，输出一个 ```json 代码块，字段如下（供程序汇总，不含多余文字）：
{{"overview": "概览一句话",
 "blocks": [{{"topic": "任务名", "start": "HH:MM", "end": "HH:MM"}}],
 "distribution": [{{"category": "类别", "percent": 数字}}]}}

本地统计（按分类计数，共 {count} 条）：
{distribution}

记录：
{records}
"""


def _distribution_lines(analyses: list[dict[str, Any]]) -> str:
    """按 category 逐条统计占比，作为日报「时间分布」的事实依据。

    截图是离散采样（5 分钟一张），但分类是逐条标出来的，计数比让模型再估一遍可靠得多。
    迁移前入库的老数据没有 category，统一归「其他」。
    """
    counts: dict[str, int] = {}
    for item in analyses:
        category = item.get("category") or OTHER_CATEGORY
        counts[category] = counts.get(category, 0) + 1
    total = sum(counts.values())
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return "\n".join(
        f"- {name}：{count} 条（{round(count / total * 100)}%）" for name, count in ordered
    )


def _build_prompt(date: str, analyses: list[dict[str, Any]]) -> str:
    records = "\n".join(
        f"- [{item['timestamp']}]"
        + (f"（{item['category']}）" if item.get("category") else "")
        + f" {item['analysis']}"
        for item in analyses
    )
    return PROMPT_TEMPLATE.format(
        date=date,
        count=len(analyses),
        distribution=_distribution_lines(analyses),
        records=records,
    )


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


def generate_daily_report(
    date: str,
    ai: AIClient | None = None,
    is_overwritten: bool = False,
) -> dict[str, Any]:
    """生成指定日期的日报并落库，返回 db.get_daily_report(date)。

    当日无素材时跳过生成、不落库，返回 {"skipped": True, "reason": ...}。
    幂等：同一天重复生成覆盖旧行（db 层按 date 唯一）。
    is_overwritten: 次日 00:30 的覆盖版传 True，界面据此标注这份日报含补生成内容（需求 D7）。
    """
    analyses = db.get_today_analyses(date)
    if not analyses:
        log.info("date=%s 无截图分析素材，跳过日报生成", date)
        return {"skipped": True, "reason": "当日无采集素材"}

    client = ai or AIClient()
    output = client.analyze_text(_build_prompt(date, analyses))
    content_md, content_json = _split_md_and_json(output)
    db.save_daily_report(date, content_md, content_json, is_overwritten=is_overwritten)
    log.info("日报生成完成 date=%s 素材=%d条 覆盖版=%s", date, len(analyses), is_overwritten)
    result = db.get_daily_report(date)
    assert result is not None  # 刚落库，必存在
    return result


# ------------------------------------------------------------------ 周报（M6）

WEEKLY_PROMPT_TEMPLATE = """以下是用户 {start} ~ {end} 这一周已生成的 {count} 份日报正文。
请据此生成一份中文周报，严格包含以下三个 Markdown 二级标题板块：

## 本周概览
两到三句话总结这一周主要做了什么、节奏如何。

## 主要进展
按项目/任务聚类，说明每项在本周推进到什么程度。

## 时间分布
{distribution_block}

只输出 Markdown 正文，不要输出 JSON 代码块。

日报正文：
{reports}
"""

# 有结构化分布可用时的「时间分布」段：与日报同一思路，本地算好让模型照抄。
_WEEKLY_LOCAL_BLOCK = (
    "直接采用下面给出的「本地统计」，它是 {days} 天日报的结构化分布按天平均的结果，"
    "不要自己重新估算，逐项列出即可。\n\n本地统计（周占比）：\n{lines}"
)
# 一天可用分布都没有时退回原话术，让模型估——有引用行兜着，仍比凭空猜强。
_WEEKLY_ESTIMATE_BLOCK = (
    "估算各类活动（如编码、沟通、浏览、文档等）在本周的占比，合计约 100%。"
    "每份日报标题下的引用行（概览/时间分布）来自当天的结构化记录，汇总时优先采用，"
    "比从正文里重新猜更准。"
)


def _load_daily_json(content_json: str) -> dict[str, Any] | None:
    """解析日报的结构化 JSON；坏 JSON 或非对象一律返回 None。digest 与周分布共用。"""
    try:
        data = json.loads(content_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _daily_digest(content_json: str) -> str:
    """把日报的结构化 JSON 压成一行摘要，附在当日正文之前。

    content_json 的读取方（需求 F4.2 要求日报同时存一份结构化 JSON 供周报汇总；
    在此之前它只写不读，是份死数据）。"时间分布"本来就该靠这些数字聚合，
    让模型再从 Markdown 正文里猜一遍既费 token 又失真。
    解析不出来就返回空串——周报退回只看正文，不影响生成。
    """
    data = _load_daily_json(content_json)
    if data is None:
        return ""

    parts: list[str] = []
    overview = str(data.get("overview") or "").strip()
    if overview:
        parts.append(f"概览：{overview}")
    distribution = data.get("distribution")
    if isinstance(distribution, list):
        pairs = [
            f"{item.get('category')} {item.get('percent')}%"
            for item in distribution
            if isinstance(item, dict)
            and item.get("category")
            and item.get("percent") is not None
        ]
        if pairs:
            parts.append("时间分布：" + "、".join(pairs))
    return " ｜ ".join(parts)


def _monday_of(day: _date) -> _date:
    """取该日期所在周的周一，与 db.save_weekly_report 的 week_start 口径一致。"""
    return day - timedelta(days=day.weekday())


def _normalize_day_distribution(raw: Any) -> dict[str, float]:
    """把一份日报 JSON 里的 distribution 洗成 {分类: 占比}。

    野生类别名归「其他」（与 collector.parse_analysis 同一规则，否则同一个类会以
    两个名字各算一份）；同一天里同类重复出现按求和处理；percent 缺失或非数字的条目丢弃。
    """
    day: dict[str, float] = {}
    if not isinstance(raw, list):
        return day
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("category") or "").strip()
        percent = item.get("percent")
        if not name or isinstance(percent, bool) or not isinstance(percent, (int, float)):
            continue
        if name not in IMAGE_ANALYSIS_CATEGORIES:
            name = OTHER_CATEGORY
        day[name] = day.get(name, 0.0) + percent
    return day


def _weekly_distribution_lines(day_maps: list[dict[str, float]]) -> str:
    """把多天的时间分布按天平均成周占比，输出与日报「本地统计」同款的行。

    每天的分布本来就是按分类逐条计数得来的；某天缺某类 = 那天该类为 0 条，
    按 0 计入平均（分类是封闭集合，缺项是真 0，不是没数据）。
    用落库的整数占比做平均而不是原始计数：素材只保留 3 天，上周的计数已不可考。
    """
    categories = {name for day in day_maps for name in day}
    averages = {
        name: round(sum(day.get(name, 0.0) for day in day_maps) / len(day_maps))
        for name in categories
    }
    ordered = sorted(averages.items(), key=lambda pair: (-pair[1], pair[0]))
    return "\n".join(f"- {name}：{p}%" for name, p in ordered)


def _build_weekly_prompt(
    week_start: str, reports: list[tuple[str, str, str]], distribution_block: str
) -> str:
    """拼周报 Prompt。reports 每项是 (日期, 日报正文, 结构化摘要行)，摘要为空则不附。"""
    end = (_date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
    chunks: list[str] = []
    for day, content_md, digest in reports:
        head = f"### {day}"
        if digest:
            head += f"\n> {digest}"
        chunks.append(f"{head}\n\n{content_md}")
    return WEEKLY_PROMPT_TEMPLATE.format(
        start=week_start, end=end, count=len(reports), reports="\n\n".join(chunks),
        distribution_block=distribution_block,
    )


def _strip_json_block(text: str) -> str:
    """周报不需要结构化 JSON；模型若仍吐出 json 代码块，只保留前面的 Markdown 正文。"""
    idx = text.find("```json")
    return text[:idx].strip() if idx != -1 else text.strip()


def generate_weekly_report(
    week_start: str | None = None,
    ai: AIClient | None = None,
) -> dict[str, Any]:
    """生成指定周的周报并落库，返回 db.get_weekly_report(week_start)。

    week_start 缺省为本周周一。    周报输入 = 该周周一到周日**已生成**的日报正文 + 其结构化摘要（content_json 的消费点），
    一份日报都没有时跳过、不落库，返回 {"skipped": True, "reason": ...}。
    「时间分布」优先用各天 content_json 里的分布按天平均（本地统计，模型照抄）；
    一天可用分布都没有才退回让模型估算。
    幂等：同一周重复生成覆盖旧行（db 层按 week_start 唯一）。
    """
    week_start = week_start or _monday_of(_date.today()).isoformat()
    monday = _date.fromisoformat(week_start)
    reports: list[tuple[str, str, str]] = []
    day_maps: list[dict[str, float]] = []
    for offset in range(7):
        row = db.get_daily_report((monday + timedelta(days=offset)).isoformat())
        if row:
            reports.append(
                (row["date"], row["content_md"], _daily_digest(row["content_json"]))
            )
            day_map = _normalize_day_distribution(
                (_load_daily_json(row["content_json"]) or {}).get("distribution")
            )
            if day_map:
                day_maps.append(day_map)
    if not reports:
        log.info("周 %s 没有已生成的日报，跳过周报生成", week_start)
        return {"skipped": True, "reason": "本周没有已生成的日报"}

    if day_maps:
        distribution_block = _WEEKLY_LOCAL_BLOCK.format(
            days=len(day_maps), lines=_weekly_distribution_lines(day_maps)
        )
        log.info("周报时间分布走本地统计：%d 天有结构化分布", len(day_maps))
    else:
        distribution_block = _WEEKLY_ESTIMATE_BLOCK

    client = ai or AIClient()
    content_md = _strip_json_block(
        client.analyze_text(_build_weekly_prompt(week_start, reports, distribution_block))
    )
    if not content_md:
        raise ValueError("AI 返回空周报正文")
    db.save_weekly_report(week_start, content_md)
    log.info("周报生成完成 week_start=%s 日报=%d份", week_start, len(reports))
    result = db.get_weekly_report(week_start)
    assert result is not None  # 刚落库，必存在
    return result
