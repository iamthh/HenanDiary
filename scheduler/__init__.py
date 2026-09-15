"""定时任务（B 负责）。

M5 已实现，全部在 jobs.py：采集 interval + 每天 22:00 生成日报 + 次日 00:30 覆盖前一天
+ 周日 22:30 周报 + 凌晨 03:00 清理素材；misfire_grace_time 6 小时支持关机后补跑。
启动时的两类补偿：retry_pending（AI 失败留的欠账）与 catch_up_missed_reports（压根没跑的）。
见需求文档 D7 / D11 / F2.1。
"""
