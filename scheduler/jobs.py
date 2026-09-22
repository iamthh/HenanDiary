"""定时任务：采集、日报、覆盖生成、周报、清理（M5）。

技术方案六.4 的三条约定都在这里落地：
- misfire_grace_time 6 小时：机器休眠/关机导致的错过，6 小时内恢复就自动补跑；
  超过 6 小时的由启动补跑兜底（retry_pending / catch_up_missed_reports）
- 启动时检查 pending_report 欠账并补生成（需求 D14）
- 幂等靠日期/周起始日：重复生成直接覆盖，不产生重复行

AI 失败不吞（开发规范 1.3）：记一笔 pending_report 欠账 + 回调通知界面（需求 D14 托盘变红）。

调度层不 import PySide6、不 import mss：只依赖 config / db / generator / cleanup，
界面通知通过 on_ai_failure 回调出去，采集器通过鸭子类型传进来（只要它有 run_once_safe）。
"""

from __future__ import annotations

from datetime import date as _date, timedelta
from functools import partial
from typing import Any, Callable

import config
from logger import get_logger
from report.generator import generate_daily_report, generate_weekly_report
from storage import db
from storage.cleanup import cleanup_expired

log = get_logger(__name__)

# 需求 D11：周报固定周日 22:30（配置里只有 weekly_enabled 开关，没有时间项）
WEEKLY_DAY_OF_WEEK, WEEKLY_HOUR, WEEKLY_MINUTE = "sun", 22, 30
# 清理排在 00:30 覆盖生成之后：那一步还要读前一天的素材，不能提前删
CLEANUP_HOUR, CLEANUP_MINUTE = 3, 0

MISFIRE_GRACE_SECONDS = 6 * 3600
CAPTURE_MISFIRE_GRACE_SECONDS = 300

OnFailure = Callable[[str], None]
"""AI 失败回调，参数是失败原因（给托盘提示用）。"""


def _parse_hhmm(text: str) -> tuple[int, int]:
    """解析 HH:MM（口径统一在 config.parse_hhmm）。格式非法时抛 ValueError。"""
    return config.parse_hhmm(text, "调度时间")


def _parse_hhmm_or_default(text: str, default: str, field: str) -> tuple[int, int]:
    """启动/重排路径专用：历史坏配置不能让整个调度器起不来。

    校验上线前写入的配置可能已经是坏的（如 daily_time='abc'）。这里记 error 后回落到
    默认值继续跑——"任务照常执行 + 日志留痕"远好过"调度器直接不启动且无人察觉"。
    """
    try:
        return _parse_hhmm(text)
    except (ValueError, TypeError, AttributeError):
        log.error("配置项 %s 非法 %r，本次回落默认值 %s", field, text, default)
        return _parse_hhmm(default)


def _clear_pending(target: str, kind: str) -> int:
    """销掉该目标上全部同类型欠账，返回销掉条数。

    调用时机：本次生成成功（含"无素材所以跳过"）之后。跳过也算销账——
    没素材是客观事实，不是 AI 失败，留着欠账只会每天白重试一次。
    """
    cleared = 0
    for row in db.get_pending_reports():
        if row["date"] == target and row["type"] == kind:
            db.delete_pending_report(row["id"])
            cleared += 1
    return cleared


def current_week_start() -> str:
    """本周周一，与 db.save_weekly_report 的 week_start 口径一致。"""
    today = _date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


def run_daily_report(
    date: str | None = None,
    is_overwritten: bool = False,
    on_ai_failure: OnFailure | None = None,
) -> dict[str, Any]:
    """日报调度入口。成功（或跳过）返回生成结果，失败返回 {"error": ...}，不抛异常。

    失败时登记 pending_report 欠账并回调通知界面；成功时销掉该日期的旧欠账。
    """
    target = date or _date.today().isoformat()
    try:
        result = generate_daily_report(target, is_overwritten=is_overwritten)
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
        log.exception("日报生成失败 date=%s 覆盖版=%s，登记欠账", target, is_overwritten)
        _clear_pending(target, "daily")  # 先清旧账再记新账，同一日期只留最新一条原因
        db.add_pending_report(target, "daily", reason)
        if on_ai_failure:
            on_ai_failure(reason)
        return {"error": reason}
    cleared = _clear_pending(target, "daily")
    if cleared:
        log.info("欠账已销 date=%s 条数=%s", target, cleared)
    return result


def run_overwrite_report(on_ai_failure: OnFailure | None = None) -> dict[str, Any]:
    """次日 00:30 的覆盖生成：重新生成**前一天**的日报并标覆盖版（需求 D7）。"""
    target = (_date.today() - timedelta(days=1)).isoformat()
    log.info("执行覆盖生成 date=%s", target)
    return run_daily_report(target, is_overwritten=True, on_ai_failure=on_ai_failure)


def run_weekly_report(
    week_start: str | None = None,
    on_ai_failure: OnFailure | None = None,
) -> dict[str, Any]:
    """周报调度入口。失败登记 weekly 欠账，成功销账。"""
    target = week_start or current_week_start()
    try:
        result = generate_weekly_report(target)
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
        log.exception("周报生成失败 week_start=%s，登记欠账", target)
        _clear_pending(target, "weekly")
        db.add_pending_report(target, "weekly", reason)
        if on_ai_failure:
            on_ai_failure(reason)
        return {"error": reason}
    cleared = _clear_pending(target, "weekly")
    if cleared:
        log.info("周报欠账已销 week_start=%s 条数=%s", target, cleared)
    return result


def run_cleanup() -> int:
    """每日清理过期素材，返回删除条数。失败只记日志，不影响其他任务。"""
    try:
        return cleanup_expired()
    except Exception:
        log.exception("素材清理失败")
        return 0


def retry_pending(on_ai_failure: OnFailure | None = None) -> dict[str, int]:
    """启动时补跑全部欠账（需求 D14 / 技术方案六.4）。

    先给待办清单拍快照再逐条跑：补跑失败的会重新记账，边遍历边改表会漏项或死循环。
    """
    snapshot = db.get_pending_reports()
    if not snapshot:
        return {"retried": 0, "succeeded": 0}
    log.info("发现 %d 笔待重试任务，开始补生成", len(snapshot))

    retried = succeeded = 0
    for row in snapshot:
        kind, target = row["type"], row["date"]
        if kind == "daily":
            result = run_daily_report(target, on_ai_failure=on_ai_failure)
        elif kind == "weekly":
            result = run_weekly_report(target, on_ai_failure=on_ai_failure)
        else:
            log.warning("未知的待重试类型 %s（id=%s），跳过", kind, row["id"])
            continue
        retried += 1
        if "error" not in result:
            succeeded += 1
    log.info("补生成结束：尝试 %d 笔，成功 %d 笔", retried, succeeded)
    return {"retried": retried, "succeeded": succeeded}


def catch_up_missed_reports(on_ai_failure: OnFailure | None = None) -> list[str]:
    """补上错过 22:00 而根本没跑的历史日报，返回补生成的日期列表。

    覆盖"22:00 时机器关机/休眠"（需求 F2.1）：开机时把漏掉的补出来，标覆盖版。
    扫描范围 = 素材保留期（默认 3 天）内的自然日，不含今天——今天的等当天 22:00 正常跑。
    上限取保留期而非无限回溯，是因为超期素材已被清理，没有素材的日期本来就该跳过，
    不能凭空造日报；关机多天回来时，保留期内的每一天都补得回来。
    与 retry_pending 互补：那边处理"跑了但 AI 失败"的欠账，这边处理"压根没跑"。
    """
    retention_days = config.load_settings()["storage"]["raw_retention_days"]
    generated: list[str] = []
    for offset in range(1, retention_days + 1):
        target = (_date.today() - timedelta(days=offset)).isoformat()
        if db.get_daily_report(target) is not None:
            continue  # 已有日报，漏的只可能是"根本没生成"的日子
        if not db.get_today_analyses(target):
            continue
        log.info("发现漏生成的日报 date=%s，补生成并标覆盖版", target)
        run_daily_report(target, is_overwritten=True, on_ai_failure=on_ai_failure)
        generated.append(target)
    return generated


def build_scheduler(collector: Any, on_ai_failure: OnFailure | None = None) -> Any:
    """建统一调度器：采集 interval + 日报 + 覆盖 + 周报 + 清理，返回 BackgroundScheduler。

    collector 只要求有 run_once_safe()（鸭子类型，避免调度层依赖 mss）。
    调用方负责 shutdown。
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    settings = config.load_settings()
    report_defaults = config.DEFAULT_SETTINGS["report"]
    hour, minute = _parse_hhmm_or_default(
        settings["report"]["daily_time"], report_defaults["daily_time"], "report.daily_time"
    )
    ow_hour, ow_minute = _parse_hhmm_or_default(
        settings["report"]["overwrite_time"],
        report_defaults["overwrite_time"],
        "report.overwrite_time",
    )
    interval_min = settings["capture"]["screenshot_interval_min"]

    scheduler = BackgroundScheduler(
        job_defaults={"coalesce": True, "max_instances": 1},  # 关机多天只补跑一次，不并发堆叠
    )
    scheduler.add_job(
        collector.run_once_safe, "interval", minutes=interval_min,
        misfire_grace_time=CAPTURE_MISFIRE_GRACE_SECONDS, id="capture",
    )
    scheduler.add_job(
        partial(run_daily_report, on_ai_failure=on_ai_failure),
        "cron", hour=hour, minute=minute,
        misfire_grace_time=MISFIRE_GRACE_SECONDS, id="daily_report",
    )
    scheduler.add_job(
        partial(run_overwrite_report, on_ai_failure=on_ai_failure),
        "cron", hour=ow_hour, minute=ow_minute,
        misfire_grace_time=MISFIRE_GRACE_SECONDS, id="daily_overwrite",
    )
    if settings["report"]["weekly_enabled"]:
        scheduler.add_job(
            partial(run_weekly_report, on_ai_failure=on_ai_failure),
            "cron", day_of_week=WEEKLY_DAY_OF_WEEK, hour=WEEKLY_HOUR, minute=WEEKLY_MINUTE,
            misfire_grace_time=MISFIRE_GRACE_SECONDS, id="weekly_report",
        )
    scheduler.add_job(
        run_cleanup, "cron", hour=CLEANUP_HOUR, minute=CLEANUP_MINUTE,
        misfire_grace_time=MISFIRE_GRACE_SECONDS, id="cleanup",
    )
    scheduler.start()
    log.info(
        "调度已启动：采集每 %s 分钟，日报 %02d:%02d，覆盖 %02d:%02d，周报 %s %02d:%02d，清理 %02d:%02d",
        interval_min, hour, minute, ow_hour, ow_minute,
        WEEKLY_DAY_OF_WEEK, WEEKLY_HOUR, WEEKLY_MINUTE, CLEANUP_HOUR, CLEANUP_MINUTE,
    )
    return scheduler


def reschedule_report_jobs(scheduler: Any, settings: dict[str, Any] | None = None) -> None:
    """设置窗口改了日报/覆盖时间后重排，不重启即生效。"""
    settings = settings or config.load_settings()
    report_defaults = config.DEFAULT_SETTINGS["report"]
    hour, minute = _parse_hhmm_or_default(
        settings["report"]["daily_time"], report_defaults["daily_time"], "report.daily_time"
    )
    scheduler.reschedule_job("daily_report", trigger="cron", hour=hour, minute=minute)
    ow_hour, ow_minute = _parse_hhmm_or_default(
        settings["report"]["overwrite_time"],
        report_defaults["overwrite_time"],
        "report.overwrite_time",
    )
    scheduler.reschedule_job("daily_overwrite", trigger="cron", hour=ow_hour, minute=ow_minute)
    log.info("日报调度已重排：生成 %02d:%02d，覆盖 %02d:%02d", hour, minute, ow_hour, ow_minute)
