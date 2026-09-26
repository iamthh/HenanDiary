"""app_usage 读写测试（M9）：按天按应用聚合、降序、保留期清理。"""

from __future__ import annotations

from datetime import date, timedelta

from storage import db


def _iso(days_ago: int, hhmm: str = "10:00:00") -> str:
    return f"{(date.today() - timedelta(days=days_ago)).isoformat()}T{hhmm}"


def _day(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def test_save_returns_incrementing_id() -> None:
    db.init_db()
    first = db.save_app_usage(_iso(0), "Code", 300)
    second = db.save_app_usage(_iso(0), "Code", 300)

    assert second > first


def test_summary_aggregates_by_app_and_sorts_desc() -> None:
    db.init_db()
    db.save_app_usage(_iso(0, "09:00:00"), "Code", 300)
    db.save_app_usage(_iso(0, "09:05:00"), "Code", 300)
    db.save_app_usage(_iso(0, "09:10:00"), "chrome", 300)
    db.save_app_usage(_iso(0, "09:15:00"), "WeChat", 120)

    rows = db.get_app_usage_summary(date.today().isoformat())

    assert [(r["app"], r["seconds"], r["samples"]) for r in rows] == [
        ("Code", 600, 2),
        ("chrome", 300, 1),
        ("WeChat", 120, 1),
    ]


def test_summary_is_scoped_to_one_day() -> None:
    db.init_db()
    db.save_app_usage(_iso(0, "10:00:00"), "Code", 300)
    db.save_app_usage(_iso(1, "10:00:00"), "Code", 300)

    rows = db.get_app_usage_summary(_day(0))

    assert len(rows) == 1 and rows[0]["seconds"] == 300


def test_summary_empty_when_no_data() -> None:
    db.init_db()
    assert db.get_app_usage_summary("2026-01-01") == []


def test_cleanup_keeps_recent_and_drops_expired() -> None:
    """保留期口径与素材清理一致：保留「含当天在内最近 days 个自然日」。"""
    db.init_db()
    db.save_app_usage(_iso(0), "Code", 300)      # 今天
    db.save_app_usage(_iso(89), "chrome", 300)   # 保留期内（边界）
    db.save_app_usage(_iso(200), "WeChat", 300)  # 超期

    deleted = db.cleanup_old_app_usage(90)

    assert deleted == 1
    assert db.get_app_usage_summary(_day(200)) == []
    assert db.get_app_usage_summary(_day(0))[0]["samples"] == 1
    assert db.get_app_usage_summary(_day(89))[0]["samples"] == 1
