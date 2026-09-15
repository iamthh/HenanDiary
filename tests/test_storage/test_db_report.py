"""M2 归属的 3 个 db 函数的真实读写测试（save/get/list_daily_report）。"""

from __future__ import annotations

import config
import sqlite3

from storage import db


def _row_id(date: str) -> int:
    conn = sqlite3.connect(config.get_db_path())
    try:
        return conn.execute(
            "SELECT id FROM daily_report WHERE date = ?", (date,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_save_and_get_daily_report() -> None:
    db.init_db()
    db.save_daily_report("2026-09-15", "# 日报正文", '{"overview": "x"}')

    row = db.get_daily_report("2026-09-15")
    assert row["content_md"] == "# 日报正文"
    assert row["content_json"] == '{"overview": "x"}'
    assert row["is_overwritten"] == 0
    assert row["ai_status"] == "success"
    assert row["generated_at"].startswith("2026-")


def test_get_daily_report_returns_none_when_absent() -> None:
    db.init_db()
    assert db.get_daily_report("2026-01-01") is None


def test_save_daily_report_is_idempotent_by_date() -> None:
    db.init_db()
    db.save_daily_report("2026-09-15", "第一版", "{}")
    first_id = _row_id("2026-09-15")
    db.save_daily_report("2026-09-15", "覆盖版", "{}", is_overwritten=True)

    row = db.get_daily_report("2026-09-15")
    assert row["content_md"] == "覆盖版"
    assert row["is_overwritten"] == 1
    assert _row_id("2026-09-15") == first_id  # 覆盖复用同一行，id 不跳号
    assert len(db.list_daily_reports()) == 1  # 同一天只有一行


def test_list_daily_reports_sorted_desc_without_body() -> None:
    db.init_db()
    db.save_daily_report("2026-09-14", "昨天", "{}")
    db.save_daily_report("2026-09-15", "今天", "{}")
    db.save_daily_report("2026-09-13", "前天", "{}")

    rows = db.list_daily_reports()
    assert [r["date"] for r in rows] == ["2026-09-15", "2026-09-14", "2026-09-13"]
    assert "content_md" not in rows[0]


def test_list_daily_reports_respects_limit() -> None:
    db.init_db()
    for d in ("2026-09-13", "2026-09-14", "2026-09-15"):
        db.save_daily_report(d, "x", "{}")
    assert len(db.list_daily_reports(limit=2)) == 2
