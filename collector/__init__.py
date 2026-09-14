"""截图采集（A 负责）。

M1 实现：mss 定时截全屏 → 内存 PNG bytes → Base64 送 AI 分析 →
结果调 storage.db.save_screenshot_analysis 落库 → 立即释放图片引用。

硬性约束：图片绝不写盘（含系统 temp），见需求文档 D5 / F1.1。
"""
