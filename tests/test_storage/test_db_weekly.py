"""M6 归属的 3 个周报 db 函数的真实读写测试。"""

from __future__ import annotations

import sqlite3

import config
from storage import db


def _row_id(week_start: str) -> int:
    conn = sqlite3.connect(config.get_db_path())
    try:
        return conn.execute(
            "SELECT id FROM weekly_report WHERE week_start = ?", (week_start,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_save_and_get_weekly_report() -> None:
    db.init_db()
    db.save_weekly_report("2026-09-14", "## 本周概览\n推进了 M5")

    row = db.get_weekly_report("2026-09-14")
    assert row["week_start"] == "2026-09-14"
    assert "本周概览" in row["content_md"]
    assert row["generated_at"].startswith("2026-")


def test_get_weekly_report_returns_none_when_absent() -> None:
    db.init_db()
    assert db.get_weekly_report("2026-09-07") is None


def test_save_weekly_report_is_idempotent_by_week_start() -> None:
    db.init_db()
    db.save_weekly_report("2026-09-14", "第一版")
    first_id = _row_id("2026-09-14")
    db.save_weekly_report("2026-09-14", "第二版")

    assert db.get_weekly_report("2026-09-14")["content_md"] == "第二版"
    assert _row_id("2026-09-14") == first_id  # 覆盖复用同一行，id 不跳号
    assert len(db.list_weekly_reports()) == 1


def test_list_weekly_reports_sorted_desc_without_body() -> None:
    db.init_db()
    db.save_weekly_report("2026-09-07", "上周")
    db.save_weekly_report("2026-09-14", "本周")

    rows = db.list_weekly_reports()
    assert [r["week_start"] for r in rows] == ["2026-09-14", "2026-09-07"]
    assert "content_md" not in rows[0]


def test_list_weekly_reports_respects_limit() -> None:
    db.init_db()
    for week in ("2026-08-31", "2026-09-07", "2026-09-14"):
        db.save_weekly_report(week, "正文")
    assert len(db.list_weekly_reports(limit=2)) == 2
