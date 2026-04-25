"""ManhwaBot — the discord.py Bot subclass.

Owns the service container (DB pool, crawler client) and wires up the ordered
startup/shutdown sequence.  No cogs are loaded in Phase 4; later phases append
their module paths to ``manhwa_bot.cogs.COGS``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from .cogs import COGS
from .config import AppConfig
from .crawler.client import CrawlerClient
from .db.migrate import apply_pending
from .db.pool import DbPool

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)


class ManhwaBot(commands.Bot):
    config: AppConfig
    db: DbPool
    crawler: CrawlerClient
    started_at: datetime

    def __init__(self, config: AppConfig, db: DbPool, crawler: CrawlerClient) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = False
        intents.presences = False

        allowed_mentions = discord.AllowedMentions(
            everyone=False,
            roles=True,
            users=True,
        )

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            case_insensitive=True,
            owner_ids=set(config.bot.owner_ids),
            allowed_mentions=allowed_mentions,
        )

        self.config = config
        self.db = db
        self.crawler = crawler

    async def setup_hook(self) -> None:
        self.started_at = datetime.now(tz=UTC)

        granted = self._connection._intents  # type: ignore[attr-defined]
        _log.info("Resolved intents: %s", granted)
        if not self.intents.members:
            _log.warning(
                "MEMBERS INTENT IS MISSING — ping-role assignment and member resolution will fail"
            )

        await apply_pending(self.db)
        _log.info("DB migrations applied")

        await self.crawler.start()
        _log.info("Crawler client started")

        for cog_path in COGS:
            await self.load_extension(cog_path)
            _log.info("Loaded cog: %s", cog_path)

    async def close(self) -> None:
        _log.info("Shutting down…")
        await self.crawler.stop()
        await self.db.close()
        await super().close()

    async def process_commands(self, message: discord.Message) -> None:
        if message.guild is None or self.user in message.mentions:
            await super().process_commands(message)
