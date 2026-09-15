"""AI 客户端：OpenAI 兼容 API 封装 + DPAPI 解密 Key。

开发规范 1.4：base_url / model 从 config.py 读，Key 以 DPAPI 密文存 settings.json，
明文只在内存里存在一次调用。调用失败抛异常，由调用方记日志（采集循环不能崩）。
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

    def test_connection(self) -> str:
        """发一条最短对话验证 Key/BaseURL/模型可用，返回 'OK'。失败抛异常。"""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": "回复 OK 两个字母即可"}],
            max_tokens=1024,
        )
        return (response.choices[0].message.content or "").strip()

    def analyze_text(self, prompt: str) -> str:
        """纯文本对话（日报生成用），返回完整输出。失败抛异常。

        max_tokens=4096：推理模型的思维链同样计入输出预算，
        M1 实测 100 会被 reasoning 吃光导致正文为空。
        """
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
        )
        text = response.choices[0].message.content or ""
        return text.strip()

    def analyze_image(self, base64_png: str) -> str:
        """送截图给 AI，返回一句话文字描述。失败抛异常。"""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
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
        text = response.choices[0].message.content or ""
        return text.strip()
