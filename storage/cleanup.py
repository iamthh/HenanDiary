"""过期数据清理（B 负责）。

需求文档 D13 / F4.4：截图分析文字保留 3 天，自动清理；日报与周报永久保留。
M6 实现，由 scheduler 每日调用。
"""

from __future__ import annotations


def cleanup_expired(retention_days: int | None = None) -> int:
    """清理超过保留期的截图分析记录，返回删除条数。

    参数：
        retention_days: 保留天数；为 None 时读 config 的 storage.raw_retention_days
    依赖：storage.db.init_db 已调用。
    """
    raise NotImplementedError("M0 仅冻结接口，实现在 M6（B 负责）")
