"""storage/db.py 接口契约测试 —— M0 验收的核心。

M0 阶段函数体一律 NotImplementedError，所以这里只校验
「接口签名与表结构与技术方案 v2.0 第四节一致」。
等 M1/M2 补齐实现后，在本目录追加真实读写测试，本文件不用改。
"""

from __future__ import annotations

import inspect

import pytest

from storage import db

# 技术方案「接口约定」里冻结的签名，参数顺序也在契约内
FROZEN_SIGNATURES: dict[str, list[str]] = {
    "init_db": [],
    "save_screenshot_analysis": ["timestamp", "analysis"],
    "get_today_analyses": ["date"],
    "save_daily_report": ["date", "content_md", "content_json"],
    "get_daily_report": ["date"],
    "save_weekly_report": ["week_start", "content_md"],
    "get_pending_reports": [],
    "cleanup_old_data": ["days"],
}


@pytest.mark.parametrize("name,params", sorted(FROZEN_SIGNATURES.items()))
def test_signature_is_frozen(name: str, params: list[str]) -> None:
    assert hasattr(db, name), f"接口缺失: {name}"
    actual = list(inspect.signature(getattr(db, name)).parameters)
    assert actual == params, f"{name} 形参已变更: {actual} != {params}"


@pytest.mark.parametrize("name", sorted(FROZEN_SIGNATURES))
def test_interface_is_documented(name: str) -> None:
    assert (getattr(db, name).__doc__ or "").strip(), f"{name} 缺 docstring"


@pytest.mark.parametrize(
    "table",
    ["screenshot_analysis", "daily_report", "weekly_report", "pending_report"],
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


def test_interfaces_are_not_implemented_yet() -> None:
    """M1 开始时这个测试会失败 —— 那是预期信号，届时把实现补上并删掉本测试。"""
    with pytest.raises(NotImplementedError):
        db.init_db()
