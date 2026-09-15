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

    def create(self, **kwargs):
        """ai/client.py 统一走 stream=True，所以这里返回**分片序列**而不是整体响应。"""
        self.calls.append(kwargs)
        chunk = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="OK"))]
        )
        return iter([chunk])


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


def test_wizard_finishes_on_last_page(qapp, fake_ai) -> None:
    """回归：Key 页是末页，nextId 必须给 -1，且点 Finish 能真正结束引导。

    曾经写成 `return None`：QWizard 不认为它是末页，按钮仍显示「Next」，
    点下去既不翻页也不 accept——表现为「点 Finish 没反应」，人卡在引导里出不去
    （2026-09-15 实测踩到，日志里「首次引导完成」连着打了 14 次、settings 也落盘了）。

    注意必须 `show()`：没 show 的 QWizard 没有页面栈，`currentId()` 恒为 -1、
    `setCurrentId()` 无效，那样写出来的断言是假通过。
    """
    from PySide6.QtWidgets import QWizard

    from ui.onboarding import OnboardingWizard

    config.update_settings({"ai": {"api_key_encrypted": "x", "model": "m"}})
    wizard = OnboardingWizard()
    key_page = wizard.page(1)
    key_page._url.setText("https://x.test/v1")
    key_page._model.setText("m")
    key_page._key.setText("sk-secret")

    wizard.show()
    wizard.setCurrentId(1)

    assert wizard.nextId() == -1  # 末页：没有下一页
    assert wizard.button(QWizard.FinishButton).isVisible()  # 按钮该是 Finish，不是 Next

    wizard.button(QWizard.FinishButton).click()  # 等价于用户点 Finish

    assert wizard.isVisible() is False  # 向导真的关掉了
    assert config.load_settings()["onboarding"]["done"] is True


class _ClientWithTest:
    def test_connection(self) -> str:
        return "OK"
