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
    assert rows == [{
        "id": new_id,
        "timestamp": "2026-09-15T10:05:00",
        "analysis": "在写代码",
        "app": None,
        "category": None,
    }]


def test_save_keeps_structured_fields() -> None:
    """app / category 是日报「时间分布」的事实来源，必须原样存取。"""
    db.init_db()
    db.save_screenshot_analysis("2026-09-15T10:05:00", "在改调度", app="PyCharm", category="编码")

    row = db.get_today_analyses("2026-09-15")[0]
    assert (row["app"], row["category"]) == ("PyCharm", "编码")


def test_init_db_migrates_old_table_without_new_columns(tmp_path) -> None:
    """老库没有 app/category 列，init_db 要能补上，否则升级后一写入就报 no such column。"""
    import sqlite3

    import config

    path = config.get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "CREATE TABLE screenshot_analysis ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, analysis TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO screenshot_analysis (timestamp, analysis) VALUES (?, ?)",
            ("2026-09-15T09:00:00", "迁移前的旧记录"),
        )
    conn.close()

    db.init_db()  # 应完成补列，不抛异常

    rows = db.get_today_analyses("2026-09-15")
    assert rows[0]["analysis"] == "迁移前的旧记录"
    assert rows[0]["app"] is None and rows[0]["category"] is None  # 老数据按「其他」归类
    db.save_screenshot_analysis("2026-09-15T10:00:00", "迁移后写入", app="Code", category="编码")
    assert db.get_today_analyses("2026-09-15")[1]["category"] == "编码"


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
