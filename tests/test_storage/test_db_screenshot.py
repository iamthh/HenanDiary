"""M1 归属的 3 个 db 函数的真实读写测试（init_db / save / get_today_analyses）。"""

from __future__ import annotations

from storage import db


def test_init_db_is_idempotent() -> None:
    db.init_db()
    db.init_db()  # 第二次不应抛异常


def test_save_and_get_screenshot_analysis() -> None:
    db.init_db()
    new_id = db.save_screenshot_analysis("2026-09-15T10:05:00", "在写代码")
    assert isinstance(new_id, int) and new_id > 0

    rows = db.get_today_analyses("2026-09-15")
    assert rows == [{"id": new_id, "timestamp": "2026-09-15T10:05:00", "analysis": "在写代码"}]


def test_get_today_analyses_sorts_and_excludes_other_days() -> None:
    db.init_db()
    db.save_screenshot_analysis("2026-09-15T18:00:00", "晚")
    db.save_screenshot_analysis("2026-09-15T09:00:00", "早")
    db.save_screenshot_analysis("2026-09-14T09:00:00", "昨天")

    rows = db.get_today_analyses("2026-09-15")
    assert [r["analysis"] for r in rows] == ["早", "晚"]
    assert all(r["timestamp"].startswith("2026-09-15") for r in rows)


def test_get_today_analyses_returns_empty_list_when_no_data() -> None:
    db.init_db()
    assert db.get_today_analyses("2026-01-01") == []
