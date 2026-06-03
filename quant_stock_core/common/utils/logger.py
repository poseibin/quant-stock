"""统一日志配置（基于 loguru）"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from common.config import LOG_DIR

_INITIALIZED = False


def setup_logger(level: str = "INFO") -> None:
    """初始化全局 logger，幂等。"""
    global _INITIALIZED
    if _INITIALIZED:
        return

    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )
    logger.add(
        Path(LOG_DIR) / "app_{time:YYYYMMDD}.log",
        rotation="00:00",
        retention="30 days",
        level=level,
        encoding="utf-8",
    )
    _INITIALIZED = True


def get_logger(name: str | None = None):
    setup_logger()
    return logger.bind(name=name) if name else logger
