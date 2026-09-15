"""SQLite 数据层。

接口与表结构在 M0 冻结，实现已按里程碑全部落地（M1/M2/M5/M6，见 docs/开发状态.md）。
接口先行（开发规范 3.1）：本模块所有签名与数据表结构在 M0 冻结，
A/B 双方基于此并行开发，任何变更必须先通知对方。

时间戳统一 ISO8601 字符串（2026-09-14T22:00:00），日期统一 YYYY-MM-DD（开发规范 3.2）。

实现约定（给 M1 的提示，不是接口）：
- APScheduler 在后台线程调用本模块，sqlite3 连接需按线程独立创建并启用 WAL，
  不要用单个跨线程共享连接。
- 所有写操作必须留日志，禁止静默吞异常（开发规范 1.3）。

状态约定（2026-09-14 补充，回答"失败态与覆盖态存哪里"）：
- daily_report 里有行 == 该天日报已生成成功。生成失败的日期，daily_report 里根本不存在这一行，
  硬塞 ai_status='failed' 也无处可塞，所以失败态只能记在 pending_report。
- pending_report 是待重试队列（欠账本）：AI 调用失败时记一笔 {date, type, reason}，
  补生成成功、日报写入 daily_report 之后，删掉这笔欠账。
- 结论：pending_report 表达"还没生成成功"，daily_report.ai_status / is_overwritten 表达
  "已生成的那一行处于什么状态"，两处不要表达同一件事。
- is_overwritten 由 save_daily_report 的参数直接写入，不另开回写接口。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import config
import logger as _logger

log = _logger.get_logger(__name__)


def _connect() -> sqlite3.Connection:
    """按调用开一条独立连接（APScheduler 在后台线程调用，不做跨线程共享连接）。

    ponytail: 每操作一连接；5 分钟一次的写入量，连接池没有意义。
    """
    path: Path = config.get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

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
    conn = _connect()
    try:
        with conn:
            for sql in ALL_SCHEMAS:
                conn.execute(sql)
    finally:
        conn.close()
    log.info("数据库就绪: %s", config.get_db_path())


def save_screenshot_analysis(timestamp: str, analysis: str) -> int:
    """写入一条截图分析结果，返回自增主键 id。

    参数：
        timestamp: ISO8601 时间戳，如 2026-09-14T10:05:00
        analysis: AI 对该截图的文字描述（不含图片，图片绝不落盘）
    依赖：init_db 已调用。负责方：M1。
    """
    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO screenshot_analysis (timestamp, analysis) VALUES (?, ?)",
                (timestamp, analysis),
            )
    finally:
        conn.close()
    new_id = cur.lastrowid
    log.info("截图分析入库 id=%s timestamp=%s", new_id, timestamp)
    return new_id


def get_today_analyses(date: str) -> list[dict[str, Any]]:
    """取某天全部截图分析结果，按时间升序，供日报生成使用。

    参数：
        date: YYYY-MM-DD
    返回：
        [{"id": int, "timestamp": str, "analysis": str}, ...]；无数据返回空列表。
    依赖：init_db 已调用。负责方：M1。
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, timestamp, analysis FROM screenshot_analysis"
            " WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp",
            (f"{date}T00:00:00", f"{date}T24:00:00"),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def save_daily_report(
    date: str,
    content_md: str,
    content_json: str,
    is_overwritten: bool = False,
) -> None:
    """保存日报，按 date 幂等覆盖（同一天重复生成直接替换，见技术方案六.4）。

    参数：
        date: YYYY-MM-DD
        content_md: Markdown 正文
        content_json: 结构化 JSON 字符串，供周报汇总
        is_overwritten: 是否为次日 00:30 的覆盖版本。22:00 首次生成传 False（默认），
            00:30 重新生成传 True，供界面标注这份日报含补生成内容
    依赖：init_db 已调用。负责方：M2。
    """
    conn = _connect()
    try:
        with conn:
            # 显式列 id 复用 UNIQUE date 冲突行的主键，让 REPLACE 原地更新而非删旧插新导致 id 跳号
            conn.execute(
                "INSERT OR REPLACE INTO daily_report"
                " (id, date, content_md, content_json, generated_at, is_overwritten)"
                " VALUES ((SELECT id FROM daily_report WHERE date = ?), ?, ?, ?, ?, ?)",
                (date, date, content_md, content_json,
                 datetime.now().isoformat(timespec="seconds"), int(is_overwritten)),
            )
    finally:
        conn.close()
    log.info("日报已保存 date=%s overwritten=%s", date, is_overwritten)


def get_daily_report(date: str) -> dict[str, Any] | None:
    """取某天日报，不存在返回 None。

    返回结构：{"date","content_md","content_json","generated_at",
              "is_overwritten","ai_status"}
    依赖：init_db 已调用。负责方：M2。
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT date, content_md, content_json, generated_at, is_overwritten, ai_status"
            " FROM daily_report WHERE date = ?",
            (date,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_daily_reports(limit: int = 60) -> list[dict[str, Any]]:
    """取日报目录，按日期倒序，不含正文。

    列表页只需要标题行，正文另有 get_daily_report 按需拉，避免一次加载几十份 Markdown。
    参数：
        limit: 最多返回条数
    返回：
        [{"date","generated_at","is_overwritten","ai_status"}, ...]
    依赖：init_db 已调用。负责方：M2。
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT date, generated_at, is_overwritten, ai_status"
            " FROM daily_report ORDER BY date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def save_weekly_report(week_start: str, content_md: str) -> None:
    """保存周报，按 week_start 幂等覆盖。

    参数：
        week_start: 该周周一的日期 YYYY-MM-DD
    依赖：init_db 已调用。负责方：M6。
    """
    conn = _connect()
    try:
        with conn:
            # 与日报同样显式列 id，让覆盖写原地更新而不跳号
            conn.execute(
                "INSERT OR REPLACE INTO weekly_report"
                " (id, week_start, content_md, generated_at)"
                " VALUES ((SELECT id FROM weekly_report WHERE week_start = ?), ?, ?, ?)",
                (week_start, week_start, content_md,
                 datetime.now().isoformat(timespec="seconds")),
            )
    finally:
        conn.close()
    log.info("周报已保存 week_start=%s", week_start)


def get_weekly_report(week_start: str) -> dict[str, Any] | None:
    """取某周周报，不存在返回 None。

    返回结构：{"week_start","content_md","generated_at"}
    依赖：init_db 已调用。负责方：M6。
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT week_start, content_md, generated_at FROM weekly_report"
            " WHERE week_start = ?",
            (week_start,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_weekly_reports(limit: int = 52) -> list[dict[str, Any]]:
    """取周报目录，按周起始日倒序，不含正文。

    返回：[{"week_start","generated_at"}, ...]
    依赖：init_db 已调用。负责方：M6。
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT week_start, generated_at FROM weekly_report"
            " ORDER BY week_start DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def add_pending_report(date: str, type: str, reason: str) -> int:
    """登记一笔欠账（该日期的日报/周报没生成成功），返回自增主键 id。

    AI 调用失败时调用（需求 D14）：素材已入库，下次调用成功后再补生成。
    参数：
        date: YYYY-MM-DD
        type: daily 或 weekly
        reason: 失败原因，用于区分 Key 无效 / 余额不足 / 网络不通（托盘变红提示）
    依赖：init_db 已调用。负责方：M5。
    """
    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO pending_report (date, type, reason, created_at) VALUES (?, ?, ?, ?)",
                (date, type, reason, datetime.now().isoformat(timespec="seconds")),
            )
    finally:
        conn.close()
    new_id = cur.lastrowid
    log.warning("登记待重试任务 id=%s date=%s type=%s reason=%s", new_id, date, type, reason)
    return new_id


def get_pending_reports() -> list[dict[str, Any]]:
    """取全部待重试的 AI 任务，按创建时间升序。

    用途：启动时检查并补生成（需求文档 D14 / 技术方案六.4）。
    返回：
        [{"id","date","type","reason","created_at"}, ...]
    依赖：init_db 已调用。负责方：M5。
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, date, type, reason, created_at FROM pending_report"
            " ORDER BY created_at, id"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def delete_pending_report(pending_id: int) -> None:
    """销掉一笔欠账（补生成成功后调用），id 不存在时静默返回。

    依赖：init_db 已调用。负责方：M5。
    """
    conn = _connect()
    try:
        with conn:
            cur = conn.execute("DELETE FROM pending_report WHERE id = ?", (pending_id,))
    finally:
        conn.close()
    # rowcount=0 表示这笔欠账已被别的路径销掉，按接口约定不属于错误，不抛异常
    log.info("销账 pending id=%s 删除行数=%s", pending_id, cur.rowcount)


def cleanup_old_data(days: int) -> None:
    """删除超过保留期的截图分析记录，日报/周报永久保留（需求文档 D13）。

    参数：
        days: 保留天数，通常取 config 的 storage.raw_retention_days
    依赖：init_db 已调用。负责方：M6。
    """
    # 保留「含当天在内最近 days 个自然日」：days=3、9-15 跑，只删 9-13 零点之前的记录，
    # 9-13/14/15 三天仍在库里，00:30 覆盖生成要用的前一天素材不会被误删
    cutoff = (datetime.now().date() - timedelta(days=max(days - 1, 0))).isoformat()
    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM screenshot_analysis WHERE timestamp < ?",
                (f"{cutoff}T00:00:00",),
            )
    finally:
        conn.close()
    log.info("素材清理 days=%s cutoff=%s 删除行数=%s", days, cutoff, cur.rowcount)


# ------------------------------------------------- 接口变更记录（M0 发现并补齐）

# 2026-09-14 补充 4 组接口。原因：技术方案第四节的接口清单按需求跑不通，具体如下。
# 这 4 组都还在 M0 阶段、没有任何调用方，此时改动成本最低。
#
# 1) pending_report 只读不能写 —— D14 要求 AI 失败时保留素材、下次自动补生成，
#    但原清单没有写入入口。
#    补：add_pending_report / delete_pending_report
# 2) is_overwritten 无回写入口 —— 00:30 覆盖生成（D7）必须标出这一版是补生成的。
#    补法：不新增接口，给 save_daily_report 加 is_overwritten 参数，调用处一眼可见。
#    注：daily_report.ai_status 保留但不再扩展接口，失败态统一由 pending_report 表达，
#    避免"没生成的行"和"生成失败"两种状态各说一套（见模块 docstring 状态约定）。
# 3) F4.3 要按日期翻历史日报/周报 —— 原清单没有列表接口。
#    补：list_daily_reports / list_weekly_reports（只返回元信息，正文按需再取）
# 4) weekly_report 只有写没有读 —— 历史周报取不到内容。
#    补：get_weekly_report
#
# 至此接口共 13 个，M1 开工前不再变动。后续如需改签名，按开发规范 3.1 先通知对方。
