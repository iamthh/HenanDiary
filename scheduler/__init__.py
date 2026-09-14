"""定时任务（B 负责）。

M5 实现：每天 22:00 生成日报、次日 00:30 覆盖重新生成、周日 22:30 生成周报；
APScheduler misfire_grace_time 设 6 小时以支持关机后补跑，启动时清空 pending_report。
见需求文档 D7 / D11 / F2.1。
"""
