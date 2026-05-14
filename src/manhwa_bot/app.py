"""Application entry point.

Loads config, configures logging, wires up the DB pool and crawler client,
then runs the bot until stopped.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import log
from .bot import ManhwaBot
from .config import ConfigError, load_config, load_dotenv
from .crawler.client import CrawlerClient
from .db.pool import DbPool

_log = logging.getLogger(__name__)

_CONFIG_PATH = Path("config.toml")
_DOTENV_PATH = Path(".env")


async def run() -> None:
    load_dotenv(_DOTENV_PATH)

    try:
        config = load_config(_CONFIG_PATH)
    except (ConfigError, FileNotFoundError) as exc:
        # Logging may not be configured yet; write directly so the message is visible.
        print(f"[FATAL] Failed to load config: {exc}", file=sys.stderr)
        sys.exit(1)

    log.configure(config.bot.log_level, logger_levels=config.bot.logger_levels)
    _log.info("Config loaded, log level=%s", config.bot.log_level)

    db = await DbPool.open(config.db.path)
    crawler = CrawlerClient(config.crawler)
    bot = ManhwaBot(config, db, crawler)

    try:
        await bot.start(config.discord_bot_token)
    except KeyboardInterrupt:
        _log.info("Interrupted by user")
    finally:
        if not bot.is_closed():
            await bot.close()
