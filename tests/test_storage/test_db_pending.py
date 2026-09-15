"""pending_report 读写测试（M5 欠账本）。"""

from __future__ import annotations

from storage import db


def test_add_and_list_pending() -> None:
    db.init_db()
    pid = db.add_pending_report("2026-09-15", "daily", "APIConnectionError: 断网")

    rows = db.get_pending_reports()
    assert len(rows) == 1
    assert rows[0]["id"] == pid
    assert rows[0]["date"] == "2026-09-15"
    assert rows[0]["type"] == "daily"
    assert "断网" in rows[0]["reason"]
    assert rows[0]["created_at"]  # 写入时间自动生成


def test_delete_pending_removes_row() -> None:
    db.init_db()
    pid = db.add_pending_report("2026-09-15", "daily", "x")
    db.delete_pending_report(pid)
    assert db.get_pending_reports() == []


def test_delete_missing_id_is_silent() -> None:
    db.init_db()
    db.delete_pending_report(9999)  # 接口约定：id 不存在时静默返回，不抛异常
    assert db.get_pending_reports() == []


def test_pending_listed_in_creation_order() -> None:
    """接口约定按创建时间升序；同一秒写入的两条靠 id 兜底，先记的在前。"""
    db.init_db()
    db.add_pending_report("2026-09-15", "weekly", "先记的")
    db.add_pending_report("2026-09-14", "daily", "后记的")

    reasons = [row["reason"] for row in db.get_pending_reports()]
    assert reasons == ["先记的", "后记的"]


def test_pending_empty_initially() -> None:
    db.init_db()
    assert db.get_pending_reports() == []
