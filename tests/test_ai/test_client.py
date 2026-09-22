"""AI 客户端测试：流式拼接、DPAPI 加解密、未配 Key 的报错。

流式是本项目唯一支持的模式（Qwen-Omni 要求 stream=True），拼接逻辑里
「收尾 chunk 的 choices 为空」和「delta.content 为 None」都是真实会遇到的情况，逐条钉住。

这里用 __new__ 绕开 __init__——真构造要读 settings 里的 DPAPI 密文，与本文件要测的东西无关。
"""

from __future__ import annotations

import pytest

import config
from ai.client import AIClient, decrypt_key, encrypt_key


class _FakeDelta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.delta = _FakeDelta(content)


class _FakeChunk:
    """一个流式分片；usage_only 模拟只带用量、choices 为空的收尾分片。"""

    def __init__(self, content: str | None = None, *, usage_only: bool = False) -> None:
        self.choices = [] if usage_only else [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, chunks: list[_FakeChunk]) -> None:
        self._chunks = chunks
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self._chunks)


class _FakeSDK:
    def __init__(self, chunks: list[_FakeChunk]) -> None:
        self.completions = _FakeCompletions(chunks)

        class _Chat:
            pass

        chat = _Chat()
        chat.completions = self.completions
        self.chat = chat


def _client_with(chunks: list[_FakeChunk]) -> tuple[AIClient, _FakeCompletions]:
    client = AIClient.__new__(AIClient)
    sdk = _FakeSDK(chunks)
    client._client = sdk
    client._model = "qwen3-vl-plus"
    return client, sdk.completions


# ---------------------------------------------------------------- 流式拼接


def test_analyze_text_joins_stream_chunks() -> None:
    client, calls = _client_with([_FakeChunk("你"), _FakeChunk("好"), _FakeChunk("世界")])

    assert client.analyze_text("打个招呼") == "你好世界"
    assert calls.calls[0]["stream"] is True
    assert calls.calls[0]["model"] == "qwen3-vl-plus"
    assert calls.calls[0]["max_tokens"] == 4096


def test_stream_skips_usage_only_chunk_and_none_content() -> None:
    client, _ = _client_with(
        [_FakeChunk("在写代码"), _FakeChunk(None), _FakeChunk(usage_only=True)]
    )
    assert client.analyze_text("x") == "在写代码"


def test_stream_strips_surrounding_blank() -> None:
    client, _ = _client_with([_FakeChunk("  正文  ")])
    assert client.analyze_text("x") == "正文"


def test_empty_stream_returns_empty_string() -> None:
    client, _ = _client_with([])
    assert client.analyze_text("x") == ""


def test_test_connection_uses_stream() -> None:
    client, calls = _client_with([_FakeChunk("OK")])

    assert client.test_connection() == "OK"
    assert calls.calls[0]["stream"] is True
    assert calls.calls[0]["max_tokens"] == 1024


def test_analyze_image_sends_base64_png_as_stream() -> None:
    client, calls = _client_with([_FakeChunk("在看文档")])

    assert client.analyze_image("QUJD") == "在看文档"

    kwargs = calls.calls[0]
    assert kwargs["stream"] is True
    assert kwargs["max_tokens"] == 1024
    content = kwargs["messages"][0]["content"]
    assert content[1]["image_url"]["url"] == "data:image/png;base64,QUJD"


# ---------------------------------------------------------------- Key 处理


def test_dpapi_key_roundtrip() -> None:
    secret = "sk-test-1234567890abcdef"
    encrypted = encrypt_key(secret)

    assert encrypted != secret
    assert "sk-test" not in encrypted  # 不能存明文
    assert decrypt_key(encrypted) == secret


def test_missing_api_key_raises_runtime_error() -> None:
    config.update_settings({"ai": {"api_key_encrypted": ""}})
    with pytest.raises(RuntimeError):
        AIClient()


def test_client_sets_timeout_and_retries(monkeypatch) -> None:
    """不显式设置就是 SDK 默认的 600 秒超时：一次卡住会拖死整轮采集。"""
    captured: dict = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    config.update_settings({"ai": {"api_key_encrypted": encrypt_key("sk-test")}})
    AIClient()

    assert captured["timeout"] == 60
    assert captured["max_retries"] == 5
    assert captured["base_url"] == config.DEFAULT_SETTINGS["ai"]["base_url"]
