"""config.py 行为契约测试。

重点：数据目录必须落在 %APPDATA% 下、缺键自动补齐、非法截图间隔被拒。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import config


def test_data_dir_sits_under_appdata(tmp_path: Path) -> None:
    assert config.get_data_dir() == tmp_path / "DailyLog"


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
