r"""统一日志入口。

开发规范 1.3：所有模块必须通过本模块取 logger，禁止 print，禁止静默吞异常。
日志落 %APPDATA%\HenanDiary\logs\app.log，按 1MB 轮转、保留 5 份。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import config

_ROOT_LOGGER_NAME = "henandiary"
_FILE_HANDLER_NAME = "henandiary-file"
_CONSOLE_HANDLER_NAME = "henandiary-console"

_MAX_BYTES = 1 * 1024 * 1024
_BACKUP_COUNT = 5
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO, console: bool = True) -> None:
    """初始化日志（幂等，可重复调用刷新配置）。

    同名 handler 已存在时不会重复添加，因此改级别只需再调一次本函数。
    """
    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    existing = {handler.get_name() for handler in logger.handlers}
    formatter = logging.Formatter(_FORMAT)

    if _FILE_HANDLER_NAME not in existing:
        config.ensure_dirs()
        file_handler = RotatingFileHandler(
            config.get_logs_dir() / "app.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.set_name(_FILE_HANDLER_NAME)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if console and _CONSOLE_HANDLER_NAME not in existing:
        console_handler = logging.StreamHandler()
        console_handler.set_name(_CONSOLE_HANDLER_NAME)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """取模块级 logger，返回的名字统一带 henandiary 前缀，便于整体控制级别。"""
    if not logging.getLogger(_ROOT_LOGGER_NAME).handlers:
        setup_logging()
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
