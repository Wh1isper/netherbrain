"""Logging configuration using loguru.

Intercepts stdlib logging so that uvicorn, httpx, sqlalchemy, etc. all
flow through loguru with a unified format.
"""

from __future__ import annotations

import logging
import sys

from loguru import logger


class _InterceptHandler(logging.Handler):
    """Bridge stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        # Map stdlib level name -> loguru level
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk the call stack so loguru reports the real call-site
        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(level: str = "INFO") -> None:
    """Configure loguru as the sole logging sink.

    Call this once at process startup (before uvicorn starts).
    """
    level = level.upper()

    # Remove default loguru handler and add ours
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    # Intercept all stdlib logging
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    # Quiet down noisy libraries
    for name in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logger.info("Logging initialised (level={})", level)
