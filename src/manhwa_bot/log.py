"""Structured logging setup."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"
_DEFAULT_LOGGER_LEVELS = (("aiohttp", "WARNING"), ("discord", "WARNING"))


def configure(
    level: str = "INFO",
    *,
    logger_levels: Iterable[tuple[str, str]] = _DEFAULT_LOGGER_LEVELS,
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
    root.setLevel(level.upper())
    _configure_library_loggers(logger_levels)


def _configure_library_loggers(logger_levels: Iterable[tuple[str, str]]) -> None:
    """Apply configured thresholds for noisy third-party loggers."""
    for logger_name, level in logger_levels:
        logging.getLogger(logger_name).setLevel(level.upper())


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
