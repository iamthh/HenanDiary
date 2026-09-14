"""AI 客户端（A 负责）。

M2 实现：openai SDK 封装（OpenAI 兼容格式）+ API Key 的 DPAPI 加解密
（win32crypt，Key 不落明文）。调用失败需区分 Key 无效 / 余额不足 / 网络不通，
见需求文档 F2.4。
"""
