"""M0 骨架验收：包结构完整、模块可导入、入口可跑通。"""

from __future__ import annotations

import importlib

import pytest

import config
import main

EXPECTED_PACKAGES = ["collector", "ai", "storage", "report", "scheduler", "ui"]


@pytest.mark.parametrize("package", EXPECTED_PACKAGES)
def test_package_importable(package: str) -> None:
    assert importlib.import_module(package) is not None


@pytest.mark.parametrize("module", ["config", "logger", "storage.db", "storage.cleanup"])
def test_module_importable(module: str) -> None:
    assert importlib.import_module(module) is not None


def test_entry_point_runs() -> None:
    assert main.main() == 0


def test_entry_point_prepares_data_dirs() -> None:
    main.main()
    assert config.get_config_path().is_file()
    assert config.get_db_path().parent.is_dir()
