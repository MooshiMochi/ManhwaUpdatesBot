"""Tests for logging configuration."""

from __future__ import annotations

import logging

from manhwa_bot import log


def test_configure_applies_configured_logger_levels_when_root_is_debug() -> None:
    root = logging.getLogger()
    discord_logger = logging.getLogger("discord")
    aiohttp_logger = logging.getLogger("aiohttp")
    sqlite_logger = logging.getLogger("aiosqlite")

    original_handlers = list(root.handlers)
    original_root_level = root.level
    original_discord_level = discord_logger.level
    original_aiohttp_level = aiohttp_logger.level
    original_sqlite_level = sqlite_logger.level

    try:
        root.handlers = [logging.NullHandler()]
        root.setLevel(logging.INFO)
        discord_logger.setLevel(logging.NOTSET)
        aiohttp_logger.setLevel(logging.NOTSET)
        sqlite_logger.setLevel(logging.NOTSET)

        log.configure(
            "DEBUG",
            logger_levels=(
                ("discord", "WARNING"),
                ("aiohttp", "ERROR"),
                ("aiosqlite", "INFO"),
            ),
        )

        assert root.level == logging.DEBUG
        assert discord_logger.level == logging.WARNING
        assert aiohttp_logger.level == logging.ERROR
        assert sqlite_logger.level == logging.INFO
    finally:
        root.handlers = original_handlers
        root.setLevel(original_root_level)
        discord_logger.setLevel(original_discord_level)
        aiohttp_logger.setLevel(original_aiohttp_level)
        sqlite_logger.setLevel(original_sqlite_level)
