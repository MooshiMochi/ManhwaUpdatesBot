"""Structured logging setup."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"
_DEFAULT_LOGGER_LEVELS = (("aiohttp", "WARNING"), ("discord", "WARNING"))

# Persistent WARNING+ log so failures (dropped notification sends, g_update
# skips, crawler disconnects) survive process restarts and pm2 log rotation
# and can be inspected after the fact. Same path `?dev logs` reads.
_DEFAULT_ERROR_LOG = Path("logs") / "error.log"


def configure(
    level: str = "INFO",
    *,
    logger_levels: Iterable[tuple[str, str]] = _DEFAULT_LOGGER_LEVELS,
    error_log_path: str | Path | None = _DEFAULT_ERROR_LOG,
) -> None:
    """Initialize root logging. Idempotent — safe to call from each entrypoint."""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level.upper())
        _configure_library_loggers(logger_levels)
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    root.addHandler(handler)
    if error_log_path:
        try:
            path = Path(error_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            file_handler.setLevel(logging.WARNING)
            file_handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
            root.addHandler(file_handler)
        except OSError as exc:  # never let logging setup take the bot down
            handler.handle(
                logging.LogRecord(
                    "manhwa_bot.log",
                    logging.WARNING,
                    __file__,
                    0,
                    f"could not open error log {error_log_path}: {exc}",
                    None,
                    None,
                )
            )
    root.setLevel(level.upper())
    _configure_library_loggers(logger_levels)


def _configure_library_loggers(logger_levels: Iterable[tuple[str, str]]) -> None:
    """Apply configured thresholds for noisy third-party loggers."""
    for logger_name, level in logger_levels:
        logging.getLogger(logger_name).setLevel(level.upper())


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
