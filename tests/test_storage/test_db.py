"""storage/db.py 接口契约测试 —— M0 验收的核心。

M0 阶段函数体一律 NotImplementedError，所以这里只校验
「接口签名与表结构与技术方案 v2.0 第四节一致」。
等 M1/M2 补齐实现后，在本目录追加真实读写测试，本文件不用改。
"""

from __future__ import annotations

import inspect

import pytest

from storage import db

# 冻结的签名，参数名与顺序都在契约内。
# 前 8 个来自技术方案「接口约定」，中间 5 个是 M0 补齐的，末 3 个是 M9（应用使用统计）补齐的
# ——历次变更都记在 storage/db.py 的接口变更记录里。
# 2026-09-22 显式变更一处：save_screenshot_analysis 增加 app / category 两个可选参数，
# 为的是让日报的「时间分布」按分类本地统计，而不是让模型估（见 docs/开发状态.md 同节）。
FROZEN_SIGNATURES: dict[str, list[str]] = {
    # 截图素材
    "init_db": [],
    "save_screenshot_analysis": ["timestamp", "analysis", "app", "category"],
    "get_today_analyses": ["date"],
    "cleanup_old_data": ["days"],
    # 日报
    "save_daily_report": ["date", "content_md", "content_json", "is_overwritten"],
    "get_daily_report": ["date"],
    "list_daily_reports": ["limit"],
    # 周报
    "save_weekly_report": ["week_start", "content_md"],
    "get_weekly_report": ["week_start"],
    "list_weekly_reports": ["limit"],
    # 失败重试
    "add_pending_report": ["date", "type", "reason"],
    "get_pending_reports": [],
    "delete_pending_report": ["pending_id"],
    # 应用使用（M9）
    "save_app_usage": ["timestamp", "app", "duration_s"],
    "get_app_usage_summary": ["date"],
    "cleanup_old_app_usage": ["days"],
}


@pytest.mark.parametrize("name,params", sorted(FROZEN_SIGNATURES.items()))
def test_signature_is_frozen(name: str, params: list[str]) -> None:
    assert hasattr(db, name), f"接口缺失: {name}"
    actual = list(inspect.signature(getattr(db, name)).parameters)
    assert actual == params, f"{name} 形参已变更: {actual} != {params}"


def test_public_interface_set_is_frozen() -> None:
    """多一个或少一个公开函数都要显式改契约表，避免接口被悄悄改。"""
    public = sorted(
        name
        for name, value in vars(db).items()
        if not name.startswith("_") and inspect.isfunction(value)
    )
    assert public == sorted(FROZEN_SIGNATURES)


@pytest.mark.parametrize("name", sorted(FROZEN_SIGNATURES))
def test_interface_is_documented(name: str) -> None:
    assert (getattr(db, name).__doc__ or "").strip(), f"{name} 缺 docstring"


@pytest.mark.parametrize(
    "table",
    ["screenshot_analysis", "daily_report", "weekly_report", "pending_report", "app_usage"],
)
def test_schema_declares_table(table: str) -> None:
    joined = " ".join(" ".join(sql.split()) for sql in db.ALL_SCHEMAS)
    assert f"CREATE TABLE IF NOT EXISTS {table}" in joined


def test_daily_report_schema_keeps_unique_date_and_status_columns() -> None:
    sql = " ".join(db.SCHEMA_DAILY_REPORT.split())
    assert "date TEXT UNIQUE NOT NULL" in sql
    assert "is_overwritten" in sql
    assert "ai_status" in sql


def test_weekly_report_schema_is_keyed_by_week_start() -> None:
    assert "week_start TEXT UNIQUE NOT NULL" in " ".join(db.SCHEMA_WEEKLY_REPORT.split())
