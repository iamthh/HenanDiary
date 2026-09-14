"""测试公共夹具。

每个测试把 %APPDATA% 指向临时目录，避免污染真实数据目录；
并清空日志 handler，保证日志相关断言互不干扰。
"""

from __future__ import annotations

import logging

import pytest

_LOG_ROOT = "dailylog"


def _detach_handlers() -> None:
    root_logger = logging.getLogger(_LOG_ROOT)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """把数据目录重定向到临时目录，测试结束后清理日志句柄。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _detach_handlers()
    yield tmp_path
    _detach_handlers()
