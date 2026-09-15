"""M4 冒烟测试：test_connection 调用形态 + 设置窗口读写回路（假 AI，不联网）。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

import config


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


from types import SimpleNamespace


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))])


class _FakeOpenAI:
    def __init__(self, **kwargs) -> None:
        self.chat = type("C", (), {"completions": _FakeCompletions()})()


@pytest.fixture()
def fake_ai(monkeypatch) -> _FakeOpenAI:
    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    import ai.client as client_mod

    monkeypatch.setattr(client_mod, "decrypt_key", lambda enc: "sk-test")
    return _FakeOpenAI


def test_test_connection_round_trip(fake_ai) -> None:
    from ai.client import AIClient

    config.update_settings({"ai": {"api_key_encrypted": "x", "model": "m1"}})
    client = AIClient()
    assert client.test_connection() == "OK"
    assert client._client.chat.completions.calls[0]["model"] == "m1"


def test_settings_dialog_load_and_save(qapp, fake_ai) -> None:
    from ui.settings import SettingsDialog

    config.update_settings({
        "ai": {"api_key_encrypted": "x", "base_url": "https://x.test/v1", "model": "old-model"},
        "capture": {"work_hours": {"start": "08:00", "end": "18:00"}},
    })
    dialog = SettingsDialog()
    assert dialog._url.text() == "https://x.test/v1"
    assert dialog._work_start.time().hour() == 8

    dialog._model.setText("new-model")
    dialog._interval.setCurrentIndex(dialog._interval.findData(10))
    dialog.save()

    settings = config.load_settings()
    assert settings["ai"]["model"] == "new-model"
    assert settings["ai"]["base_url"] == "https://x.test/v1"
    assert settings["capture"]["screenshot_interval_min"] == 10
    assert settings["ai"]["api_key_encrypted"] == "x"  # Key 留空不覆盖


def test_onboarding_key_page_validates(fake_ai, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    import ui.onboarding as ob

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(ob, "AIClient", lambda: _ClientWithTest())

    page = ob._KeyPage()
    assert page.validatePage() is False  # 空 Key 不放行

    page._url.setText("https://x.test/v1")
    page._model.setText("m")
    page._key.setText("sk-secret")
    assert page.validatePage() is True
    settings = config.load_settings()
    assert settings["onboarding"]["done"] is True
    assert settings["ai"]["api_key_encrypted"]  # 已加密落盘


class _ClientWithTest:
    def test_connection(self) -> str:
        return "OK"
