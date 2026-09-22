"""AI 客户端：OpenAI 兼容 API 封装 + DPAPI 解密 Key。

开发规范 1.4：base_url / model 从 config.py 读，Key 以 DPAPI 密文存 settings.json，
明文只在内存里存在一次调用。调用失败抛异常，由调用方记日志（采集循环不能崩）。

三个调用统一走**流式**（见 _stream_text）：千问 Qwen-Omni 系列官方要求 stream=True、
QVQ 系列仅支持流式输出；而 VL 系列与 OpenAI 官方模型同样兼容流式，所以不必维护两套。

网络参数必须显式设置：openai SDK 默认 600 秒超时 + 2 次重试。采集是每 5 分钟一轮的
后台任务，一次请求挂满 600 秒会把采集线程整轮拖死（调度器 max_instances=1 会静默跳过
后续轮次，等于漏采）。所以超时压到 60 秒，重试放到 5 次——宁可快速失败让 APScheduler
下一轮重来，也不要长时间占着线程。
"""

from __future__ import annotations

import base64

import win32crypt

import config

# 单次请求超时（秒）与 SDK 层重试次数（总尝试 = 1 + MAX_RETRIES）
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

# 截图分析的分类枚举：日报的「时间分布」按这一列本地计数，所以必须是封闭集合，
# 不能让模型自由发挥——否则每天的类别名都不一样，统计出来是一盘散沙。
OTHER_CATEGORY = "其他"
IMAGE_ANALYSIS_CATEGORIES = (
    "编码", "终端", "文档", "沟通", "会议", "浏览", "设计", "影音", "游戏", OTHER_CATEGORY,
)

# 截图分析 Prompt：要求结构化输出（采集侧 collector.parse_analysis 负责解析与容错）
IMAGE_ANALYSIS_PROMPT = (
    "看这张屏幕截图，描述用户正在做什么。只输出一个 JSON 对象，"
    "不要解释、不要 Markdown 代码块：\n"
    '{"app": "前台应用或网站名", "category": "分类", "desc": "一句话描述，不超过30字"}\n'
    f"category 必须从这些里选一个：{' / '.join(IMAGE_ANALYSIS_CATEGORIES)}。"
    "识别不出应用名或分类时，app/category 给空字符串，但 desc 必须写。"
)

# DPAPI 加解密（CryptProtectData / CryptUnprotectData）绑定当前 Windows 用户，
# 密文换机器或换用户解不开——单人使用场景正好。


def encrypt_key(plain: str) -> str:
    """把明文 API Key 加密成可存进 settings.json 的字符串。"""
    blob = win32crypt.CryptProtectData(plain.encode("utf-8"), "HenanDiary", None, None, None, 0)
    return base64.b64encode(blob).decode("ascii")


def decrypt_key(encrypted: str) -> str:
    """解密 settings.json 里的 API Key。"""
    blob = base64.b64decode(encrypted)
    return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode("utf-8")


class AIClient:
    """截图分析调用入口。"""

    def __init__(self) -> None:
        settings = config.load_settings()
        ai = settings["ai"]
        if not ai["api_key_encrypted"]:
            raise RuntimeError("未配置 API Key，请完成首次引导或在设置窗口填写")
        from openai import OpenAI  # 延迟导入，没装 openai 时加密脚本仍可运行

        self._client = OpenAI(
            api_key=decrypt_key(ai["api_key_encrypted"]),
            base_url=ai["base_url"],
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=MAX_RETRIES,
        )
        self._model = ai["model"]

    def _stream_text(self, messages: list[dict], max_tokens: int) -> str:
        """流式调用并拼接正文，返回完整文本。失败抛异常。

        为什么统一走流式：千问 Qwen-Omni 系列官方要求 stream=True（否则直接报错），
        QVQ 系列「仅支持流式输出」；VL 系列与 OpenAI 官方模型同样兼容流式。

        两个必须处理的边界：收尾那个 chunk 只带 usage、choices 为空；delta.content 也可能是 None。
        """
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
        )
        parts: list[str] = []
        for chunk in stream:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content
            if content:
                parts.append(content)
        return "".join(parts).strip()

    def test_connection(self) -> str:
        """发一条最短对话验证 Key/BaseURL/模型可用，返回模型的回复。失败抛异常。"""
        return self._stream_text(
            [{"role": "user", "content": "回复 OK 两个字母即可"}], max_tokens=1024
        )

    def analyze_text(self, prompt: str) -> str:
        """纯文本对话（日报/周报生成用），返回完整输出。失败抛异常。

        max_tokens=4096：推理模型的思维链同样计入输出预算，
        M1 实测 100 会被 reasoning 吃光导致正文为空。
        """
        return self._stream_text([{"role": "user", "content": prompt}], max_tokens=4096)

    def analyze_image(self, base64_image: str, mime: str = "image/jpeg") -> str:
        """送截图给 AI，返回结构化描述（JSON 原文）。失败抛异常。

        返回的是**原文**，不在这里解析：模型可能夹带解释或代码块，
        解析与容错统一交给 collector.parse_analysis，这一层只负责把请求发出去。

        mime 默认 image/jpeg：采集侧送的是压缩后的 JPEG（见 collector.shrink_for_ai），
        参数留出来是为了将来换回 PNG 或其它格式时不必改这里。
        """
        return self._stream_text(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": IMAGE_ANALYSIS_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{base64_image}"},
                        },
                    ],
                }
            ],
            # 推理模型的思维链也算进预算，太小会只出 reasoning 不出 content
            max_tokens=1024,
        )
