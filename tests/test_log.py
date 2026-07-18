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


def test_configure_adds_rotating_error_file_handler(tmp_path) -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_root_level = root.level

    try:
        root.handlers = []
        error_log = tmp_path / "logs" / "errors.log"
        log.configure("INFO", error_log_path=error_log)

        logging.getLogger("manhwa_bot.test").warning("something went wrong")
        logging.getLogger("manhwa_bot.test").info("routine info line")
        for handler in root.handlers:
            handler.flush()

        content = error_log.read_text(encoding="utf-8")
        assert "something went wrong" in content
        assert "routine info line" not in content
    finally:
        for handler in list(root.handlers):
            if handler not in original_handlers:
                handler.close()
        root.handlers = original_handlers
        root.setLevel(original_root_level)
