"""logger.py 行为契约测试。

重点：日志必须落文件（出问题能查）、handler 不重复、名字带统一前缀。
"""

from __future__ import annotations

import logging

import config
from logger import get_logger, setup_logging


def test_log_record_lands_in_log_file() -> None:
    setup_logging(console=False)
    get_logger("tests").info("hello-logger")

    log_file = config.get_logs_dir() / "app.log"
    assert log_file.is_file()
    assert "hello-logger" in log_file.read_text(encoding="utf-8")


def test_logger_name_carries_unified_prefix() -> None:
    assert get_logger("report.generator").name == "dailylog.report.generator"


def test_setup_logging_does_not_duplicate_handlers() -> None:
    setup_logging(console=False)
    setup_logging(console=False)

    names = [handler.get_name() for handler in logging.getLogger("dailylog").handlers]
    assert names.count("dailylog-file") == 1


def test_rotating_file_handler_configured() -> None:
    setup_logging(console=False)
    handler = next(
        h for h in logging.getLogger("dailylog").handlers if h.get_name() == "dailylog-file"
    )
    assert handler.maxBytes > 0
    assert handler.backupCount > 0
