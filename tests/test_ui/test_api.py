"""js_api 桥接层测试：状态、设置回路、引导放行、数据管理（全部假 AI 不联网）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import config
from storage import db
from ui.api import Api


@pytest.fixture()
def api() -> Api:
    db.init_db()
    config.load_settings()
    return Api()


class _FakeClient:
    def test_connection(self) -> str:
        return "OK"


def _seed_day(date: str, count: int) -> None:
    for i in range(count):
        db.save_screenshot_analysis(f"{date}T09:{i:02d}:00", f"动作{i}")


# ---------------------------------------------------------------- 总览状态

def test_get_state_counts_today_and_pending(api) -> None:
    from datetime import date

    _seed_day(date.today().isoformat(), 3)
    db.add_pending_report("2026-01-01", "daily", "网络超时")
    state = api.get_state()
    assert state["capture"]["count_today"] == 3
    assert state["report"]["today_generated"] is False
    assert state["report"]["pending"] == [
        {"date": "2026-01-01", "type": "daily", "reason": "网络超时"}
    ]


def test_toggle_capture_flips_setting(api) -> None:
    assert api.toggle_capture() == {"enabled": False}
    assert config.load_settings()["capture"]["enabled"] is False
    assert api.toggle_capture() == {"enabled": True}


# ---------------------------------------------------------------- 时间线

def test_timeline_dates_only_within_retention(api) -> None:
    from datetime import date, timedelta

    today = date.today().isoformat()
    _seed_day(today, 2)
    _seed_day("2020-01-01", 1)  # 保留期外，不该出现
    days = [d["date"] for d in api.list_timeline_dates()]
    assert today in days and "2020-01-01" not in days


def test_timeline_returns_newest_first(api) -> None:
    from datetime import date

    _seed_day(date.today().isoformat(), 3)
    events = api.get_timeline(date.today().isoformat())
    assert [e["time"] for e in events] == ["09:02", "09:01", "09:00"]


# ---------------------------------------------------------------- 设置

def test_save_settings_blank_key_keeps_old(api, monkeypatch) -> None:
    config.update_settings({"ai": {"api_key_encrypted": "old-cipher"}})
    result = api.save_settings({"model": "new-m", "api_key": ""})
    assert result == {"ok": True}
    settings = config.load_settings()
    assert settings["ai"]["model"] == "new-m"
    assert settings["ai"]["api_key_encrypted"] == "old-cipher"  # 留空不覆盖


def test_save_settings_rejects_bad_interval(api) -> None:
    result = api.save_settings({"screenshot_interval_min": 7})
    assert "error" in result  # _guard 捕获 ValueError，不抛穿


def test_save_settings_triggers_reschedule(api) -> None:
    hits = []
    api.attach(on_settings_saved=lambda: hits.append(1))
    api.save_settings({"daily_time": "21:00"})
    assert hits == [1]


# ---------------------------------------------------------------- 报表

def test_generate_marks_pending_on_failure(api, monkeypatch) -> None:
    import datetime as _dt

    _seed_day(_dt.date.today().isoformat(), 1)

    class _Boom:
        def analyze_text(self, prompt: str) -> str:
            raise RuntimeError("余额不足")

    monkeypatch.setattr("report.generator.AIClient", _Boom)
    result = api.generate("daily")
    assert "error" in result
    assert len(db.get_pending_reports()) == 1


# ---------------------------------------------------------------- 引导

def test_finish_onboarding_requires_working_key(api, monkeypatch) -> None:
    monkeypatch.setattr("ai.client.AIClient", _FakeClient)
    # 无任何 Key 时不放行
    assert "error" in api.finish_onboarding("https://x/v1", "m", "")
    assert config.load_settings()["onboarding"]["done"] is False
    # 填 Key + 测通 = 放行
    assert api.finish_onboarding("https://x/v1", "m", "sk-secret") == {"ok": True}
    settings = config.load_settings()
    assert settings["onboarding"]["done"] is True
    assert settings["ai"]["api_key_encrypted"] != "sk-secret"  # DPAPI 密文


def test_finish_onboarding_blocked_when_test_fails(api, monkeypatch) -> None:
    class _Dead:
        def test_connection(self) -> str:
            raise RuntimeError("网络不通")

    monkeypatch.setattr("ai.client.AIClient", _Dead)
    result = api.finish_onboarding("https://x/v1", "m", "sk-x")
    assert "error" in result and "网络不通" in result["error"]
    assert config.load_settings()["onboarding"]["done"] is False


# ---------------------------------------------------------------- 数据管理

def test_export_writes_zip_without_key(api, tmp_path) -> None:
    config.update_settings({"ai": {"api_key_encrypted": "cipher-text"}})
    db.save_daily_report("2026-09-14", "# 日报正文", "{}")
    result = api.export_data()
    assert "error" not in result
    import zipfile

    with zipfile.ZipFile(result["path"]) as archive:
        names = archive.namelist()
        assert "daily/2026-09-14.md" in names
        settings_text = archive.read("settings.json").decode("utf-8")
        assert "cipher-text" not in settings_text  # Key 绝不随包导出


def test_clear_data_keeps_settings_and_exports(api) -> None:
    _seed_day("2026-09-01", 2)
    db.save_daily_report("2026-09-14", "x", "{}")
    db.save_weekly_report("2026-09-07", "w")
    assert api.clear_data() == {"ok": True}
    assert db.list_daily_reports() == [] and db.list_weekly_reports() == []
    assert db.get_today_analyses("2026-09-01") == []
    assert config.load_settings()["onboarding"] is not None  # 设置保留
