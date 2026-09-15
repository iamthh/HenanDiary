"""过期数据清理（B 负责）。

需求文档 D13 / F4.4：截图分析文字保留 3 天，自动清理；日报与周报永久保留。
M6 实现，由 scheduler 每日调用。
"""

from __future__ import annotations

import sqlite3

import config
from logger import get_logger
from storage import db

log = get_logger(__name__)


def _count_analyses() -> int:
    """统计当前素材条数。

    db 的 13 个接口已冻结且没有计数接口（加公开函数要动契约测试表），
    这里用一条只读连接自查，不写库。
    """
    conn = sqlite3.connect(config.get_db_path())
    try:
        return conn.execute("SELECT COUNT(*) FROM screenshot_analysis").fetchone()[0]
    finally:
        conn.close()


def cleanup_expired(retention_days: int | None = None) -> int:
    """清理超过保留期的截图分析记录，返回删除条数。

    参数：
        retention_days: 保留天数；为 None 时读 config 的 storage.raw_retention_days
    依赖：storage.db.init_db 已调用。
    """
    days = (
        retention_days
        if retention_days is not None
        else config.load_settings()["storage"]["raw_retention_days"]
    )
    before = _count_analyses()
    db.cleanup_old_data(days)
    deleted = before - _count_analyses()
    log.info("素材清理完成 保留=%s 天，删除 %s 条", days, deleted)
    return deleted
