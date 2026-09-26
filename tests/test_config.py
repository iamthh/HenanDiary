"""config.py 行为契约测试。

重点：数据目录必须落在 %APPDATA% 下、缺键自动补齐、非法截图间隔被拒。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import config


def test_data_dir_sits_under_appdata(tmp_path: Path) -> None:
    assert config.get_data_dir() == tmp_path / "HenanDiary"


def test_data_dir_is_outside_repo() -> None:
    """D12：数据路径必须与代码/安装路径分离，否则打包会连数据一起清掉。"""
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = config.get_data_dir().resolve()
    assert repo_root not in data_dir.parents


def test_ensure_dirs_creates_expected_layout() -> None:
    config.ensure_dirs()
    for path in (
        config.get_data_dir() / "config",
        config.get_reports_dir("daily"),
        config.get_reports_dir("weekly"),
        config.get_logs_dir(),
        config.get_exports_dir(),
    ):
        assert path.is_dir(), f"目录未创建: {path}"


def test_first_run_writes_default_settings_file() -> None:
    settings = config.load_settings()
    assert config.get_config_path().is_file()
    assert settings == config.DEFAULT_SETTINGS


def test_missing_keys_are_filled_from_defaults() -> None:
    path = config.get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ai": {"model": "custom-model"}}), encoding="utf-8")

    settings = config.load_settings()

    assert settings["ai"]["model"] == "custom-model"
    assert settings["ai"]["base_url"] == config.DEFAULT_SETTINGS["ai"]["base_url"]
    assert settings["capture"]["screenshot_interval_min"] == 5


def test_update_settings_merges_and_persists() -> None:
    config.update_settings({"ai": {"api_key_encrypted": "ciphertext"}})

    reloaded = config.load_settings()
    assert reloaded["ai"]["api_key_encrypted"] == "ciphertext"
    assert reloaded["ai"]["model"] == config.DEFAULT_SETTINGS["ai"]["model"]


def test_update_settings_rejects_interval_outside_allowed_values() -> None:
    """D9：截图间隔只允许 10 / 5 / 2 分钟。"""
    with pytest.raises(ValueError):
        config.update_settings({"capture": {"screenshot_interval_min": 7}})


@pytest.mark.parametrize("interval", [10, 5, 2])
def test_allowed_intervals_are_accepted(interval: int) -> None:
    settings = config.update_settings({"capture": {"screenshot_interval_min": interval}})
    assert settings["capture"]["screenshot_interval_min"] == interval


def test_unknown_report_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        config.get_reports_dir("monthly")


# ---------------------------------------------------------------- 时间字段校验


@pytest.mark.parametrize("text,expected", [
    ("9:00", (9, 0)), ("09:00", (9, 0)), ("23:59", (23, 59)), ("00:00", (0, 0)),
])
def test_parse_hhmm_accepts_valid_text(text: str, expected: tuple[int, int]) -> None:
    assert config.parse_hhmm(text) == expected


@pytest.mark.parametrize("text", ["abc", "25:00", "09:60", "0900", "09-00", "", None, 900])
def test_parse_hhmm_rejects_invalid_text(text) -> None:
    with pytest.raises(ValueError):
        config.parse_hhmm(text)


@pytest.mark.parametrize("field,value", [
    ("daily_time", "abc"),
    ("overwrite_time", "25:99"),
])
def test_update_settings_rejects_bad_report_time(field: str, value: str) -> None:
    """坏时间一旦落盘，调度器下次启动就起不来（静默失效），必须在写入时拦下。"""
    with pytest.raises(ValueError):
        config.update_settings({"report": {field: value}})


@pytest.mark.parametrize("start,end", [("abc", "19:00"), ("09:00", "25:00"), ("19:00", "09:00")])
def test_update_settings_rejects_bad_work_hours(start: str, end: str) -> None:
    with pytest.raises(ValueError):
        config.update_settings({"capture": {"work_hours": {"start": start, "end": end}}})


def test_bad_time_is_not_persisted() -> None:
    """拦下来还不够——原文件必须保持上次的合法值，不能写坏。"""
    config.update_settings({"report": {"daily_time": "21:30"}})
    with pytest.raises(ValueError):
        config.update_settings({"report": {"daily_time": "not-a-time"}})

    assert config.load_settings()["report"]["daily_time"] == "21:30"


# ---------------------------------------------------------------- 界面皮肤（F8.1）


def test_default_theme_is_dark() -> None:
    """默认沿用原本的暗色，老用户升级后界面不该变。"""
    assert config.ALLOWED_THEMES == ("dark", "light")
    assert config.load_settings()["ui"]["theme"] == "dark"


def test_missing_ui_key_is_filled_from_defaults() -> None:
    """老的 settings.json 没有 ui 键时靠 deep_merge 补齐，不需要做数据迁移。"""
    path = config.get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"capture": {"screenshot_interval_min": 10}}), encoding="utf-8")

    settings = config.load_settings()

    assert settings["ui"]["theme"] == "dark"
    assert settings["capture"]["screenshot_interval_min"] == 10


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_allowed_themes_are_accepted(theme: str) -> None:
    assert config.update_settings({"ui": {"theme": theme}})["ui"]["theme"] == theme


def test_update_settings_rejects_unknown_theme() -> None:
    with pytest.raises(ValueError):
        config.update_settings({"ui": {"theme": "solarized"}})


def test_bad_theme_is_not_persisted() -> None:
    """同坏时间：拦下来之后原文件必须还是上次的合法值。"""
    config.update_settings({"ui": {"theme": "light"}})
    with pytest.raises(ValueError):
        config.update_settings({"ui": {"theme": "solarized"}})

    assert config.load_settings()["ui"]["theme"] == "light"
