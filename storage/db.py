"""SQLite 数据层。

M0 只冻结接口与表结构，函数实现分别由 M1/M2/M5/M6 补齐（见 docs/开发状态.md）。
接口先行（开发规范 3.1）：本模块所有签名与数据表结构在 M0 冻结，
A/B 双方基于此并行开发，任何变更必须先通知对方。

时间戳统一 ISO8601 字符串（2026-09-14T22:00:00），日期统一 YYYY-MM-DD（开发规范 3.2）。

实现约定（给 M1 的提示，不是接口）：
- APScheduler 在后台线程调用本模块，sqlite3 连接需按线程独立创建并启用 WAL，
  不要用单个跨线程共享连接。
- 所有写操作必须留日志，禁止静默吞异常（开发规范 1.3）。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------- 表结构（M0 冻结）

SCHEMA_SCREENSHOT_ANALYSIS = """
CREATE TABLE IF NOT EXISTS screenshot_analysis (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    analysis    TEXT NOT NULL
)
"""

SCHEMA_DAILY_REPORT = """
CREATE TABLE IF NOT EXISTS daily_report (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT UNIQUE NOT NULL,
    content_md      TEXT NOT NULL,
    content_json    TEXT NOT NULL,
    generated_at    TEXT NOT NULL,
    is_overwritten  INTEGER DEFAULT 0,
    ai_status       TEXT DEFAULT 'success'
)
"""

SCHEMA_WEEKLY_REPORT = """
CREATE TABLE IF NOT EXISTS weekly_report (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start      TEXT UNIQUE NOT NULL,
    content_md      TEXT NOT NULL,
    generated_at    TEXT NOT NULL
)
"""

SCHEMA_PENDING_REPORT = """
CREATE TABLE IF NOT EXISTS pending_report (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,
    type        TEXT NOT NULL,
    reason      TEXT,
    created_at  TEXT NOT NULL
)
"""

ALL_SCHEMAS = (
    SCHEMA_SCREENSHOT_ANALYSIS,
    SCHEMA_DAILY_REPORT,
    SCHEMA_WEEKLY_REPORT,
    SCHEMA_PENDING_REPORT,
)


# ---------------------------------------------------------------- 接口（M0 冻结）


def init_db() -> None:
    """建库建表，幂等；程序启动时调用一次。

    依赖：无。负责方：M1。
    """
    raise NotImplementedError("M0 仅冻结接口，实现在 M1（A 负责）")


def save_screenshot_analysis(timestamp: str, analysis: str) -> int:
    """写入一条截图分析结果，返回自增主键 id。

    参数：
        timestamp: ISO8601 时间戳，如 2026-09-14T10:05:00
        analysis: AI 对该截图的文字描述（不含图片，图片绝不落盘）
    依赖：init_db 已调用。负责方：M1。
    """
    raise NotImplementedError("M0 仅冻结接口，实现在 M1（A 负责）")


def get_today_analyses(date: str) -> list[dict[str, Any]]:
    """取某天全部截图分析结果，按时间升序，供日报生成使用。

    参数：
        date: YYYY-MM-DD
    返回：
        [{"id": int, "timestamp": str, "analysis": str}, ...]；无数据返回空列表。
    依赖：init_db 已调用。负责方：M1。
    """
    raise NotImplementedError("M0 仅冻结接口，实现在 M1（A 负责）")


def save_daily_report(date: str, content_md: str, content_json: str) -> None:
    """保存日报，按 date 幂等覆盖（同一天重复生成直接替换，见技术方案六.4）。

    参数：
        date: YYYY-MM-DD
        content_md: Markdown 正文
        content_json: 结构化 JSON 字符串，供周报汇总
    依赖：init_db 已调用。负责方：M2。
    """
    raise NotImplementedError("M0 仅冻结接口，实现在 M2（B 负责）")


def get_daily_report(date: str) -> dict[str, Any] | None:
    """取某天日报，不存在返回 None。

    返回结构：{"date","content_md","content_json","generated_at",
              "is_overwritten","ai_status"}
    依赖：init_db 已调用。负责方：M2。
    """
    raise NotImplementedError("M0 仅冻结接口，实现在 M2（B 负责）")


def save_weekly_report(week_start: str, content_md: str) -> None:
    """保存周报，按 week_start 幂等覆盖。

    参数：
        week_start: 该周周一的日期 YYYY-MM-DD
    依赖：init_db 已调用。负责方：M6。
    """
    raise NotImplementedError("M0 仅冻结接口，实现在 M6（B 负责）")


def get_pending_reports() -> list[dict[str, Any]]:
    """取全部待重试的 AI 任务，按创建时间升序。

    用途：启动时检查并补生成（需求文档 D14 / 技术方案六.4）。
    返回：
        [{"id","date","type","reason","created_at"}, ...]
    依赖：init_db 已调用。负责方：M5。
    """
    raise NotImplementedError("M0 仅冻结接口，实现在 M5（B 负责）")


def cleanup_old_data(days: int) -> None:
    """删除超过保留期的截图分析记录，日报/周报永久保留（需求文档 D13）。

    参数：
        days: 保留天数，通常取 config 的 storage.raw_retention_days
    依赖：init_db 已调用。负责方：M6。
    """
    raise NotImplementedError("M0 仅冻结接口，实现在 M6（B 负责）")


# ------------------------------------------------------- 待确认的接口缺口（M0 发现）

# 以下接口在技术方案第四节里没有定义，但按需求跑不通，需要 A/B 双方在 M1 开工前拍板。
# 本文件不擅自实现，避免"私自改接口不通知"（开发规范七）。
#
# 1) pending_report 表只读不能写：D14 要求在 AI 调用失败时"保留素材、下次自动补生成"，
#    但接口清单里没有写入入口。
#    提案：add_pending_report(date: str, type: str, reason: str) -> int
#         delete_pending_report(pending_id: int) -> None
# 2) daily_report.ai_status / is_overwritten 无回写接口：00:30 覆盖生成（D7）与失败态
#    （D14）都需要把状态写回去。
#    提案：set_daily_report_status(date: str, ai_status: str, is_overwritten: int) -> None
# 3) F4.3 要求"按日期翻历史日报/周报"，但没有列表接口。
#    提案：list_daily_reports(limit: int = 60) -> list[dict]
#         list_weekly_reports(limit: int = 52) -> list[dict]
# 4) weekly_report 只有写没有读，查看历史周报取不到内容。
#    提案：get_weekly_report(week_start: str) -> dict | None
