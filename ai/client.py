"""AI 客户端：OpenAI 兼容 API 封装 + DPAPI 解密 Key。

开发规范 1.4：base_url / model 从 config.py 读，Key 以 DPAPI 密文存 settings.json，
明文只在内存里存在一次调用。调用失败抛异常，由调用方记日志（采集循环不能崩）。

三个调用统一走**流式**（见 _stream_text）：千问 Qwen-Omni 系列官方要求 stream=True、
QVQ 系列仅支持流式输出；而 VL 系列与 OpenAI 官方模型同样兼容流式，所以不必维护两套。
"""

from __future__ import annotations

import base64

import win32crypt

import config

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

    def analyze_image(self, base64_png: str) -> str:
        """送截图给 AI，返回一句话文字描述。失败抛异常。"""
        return self._stream_text(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "描述这张屏幕截图中用户正在做什么，用一句话概括，不超过30字。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{base64_png}"},
                        },
                    ],
                }
            ],
            # 推理模型的思维链也算进预算，太小会只出 reasoning 不出 content
            max_tokens=1024,
        )
