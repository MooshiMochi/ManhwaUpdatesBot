"""Structured logging setup."""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"


def configure(level: str = "INFO") -> None:
    """Initialize root logging. Idempotent — safe to call from each entrypoint."""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    root.addHandler(handler)
    root.setLevel(level.upper())
    # discord.py is chatty at INFO; bump it to WARNING unless DEBUG is requested.
    if level.upper() != "DEBUG":
        logging.getLogger("discord").setLevel(logging.WARNING)
        logging.getLogger("aiohttp").setLevel(logging.WARNING)


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
