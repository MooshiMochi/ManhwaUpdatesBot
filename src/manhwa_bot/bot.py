"""ManhwaBot — the discord.py Bot subclass.

Owns the service container (DB pool, crawler client, premium subsystem) and
wires up the ordered startup/shutdown sequence.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from .checks import PREMIUM_REQUIRED
from .cogs import COGS
from .config import AppConfig
from .crawler.client import CrawlerClient
from .db.migrate import apply_pending
from .db.patreon_links import PatreonLinkStore
from .db.pool import DbPool
from .db.premium_grants import PremiumGrantStore
from .premium import (
    DiscordEntitlementsService,
    GrantsService,
    PatreonClient,
    PremiumService,
)
from .ui.upgrade_embed import build_upgrade_embed, build_upgrade_view

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)


class ManhwaBot(commands.Bot):
    config: AppConfig
    db: DbPool
    crawler: CrawlerClient
    started_at: datetime
    grants: GrantsService
    patreon: PatreonClient
    discord_ents: DiscordEntitlementsService
    premium: PremiumService

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
        self._discord_ents_warmed = False

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

        self.grants = GrantsService(PremiumGrantStore(self.db))
        self.patreon = PatreonClient(self.config.premium.patreon, PatreonLinkStore(self.db))
        self.discord_ents = DiscordEntitlementsService(self.config.premium.discord)
        self.premium = PremiumService(
            self,
            self.config.premium,
            self.grants,
            self.patreon,
            self.discord_ents,
        )
        await self.grants.start()
        await self.patreon.start()
        self.add_listener(self.discord_ents.on_entitlement_create, "on_entitlement_create")
        self.add_listener(self.discord_ents.on_entitlement_update, "on_entitlement_update")
        self.add_listener(self.discord_ents.on_entitlement_delete, "on_entitlement_delete")

        self.tree.on_error = self._on_app_command_error  # type: ignore[assignment]
        self.add_listener(self._on_command_error, "on_command_error")
        _log.info("Premium subsystem initialized")

        await self.crawler.start()
        _log.info("Crawler client started")

        for cog_path in COGS:
            await self.load_extension(cog_path)
            _log.info("Loaded cog: %s", cog_path)

    async def on_ready(self) -> None:
        if not self._discord_ents_warmed:
            self._discord_ents_warmed = True
            try:
                await self.discord_ents.warm(self)
            except Exception:
                _log.exception("Failed to warm Discord entitlements cache")

    async def close(self) -> None:
        _log.info("Shutting down…")
        await self.patreon.stop()
        await self.grants.stop()
        await self.crawler.stop()
        await self.db.close()
        await super().close()

    async def process_commands(self, message: discord.Message) -> None:
        if message.guild is None or self.user in message.mentions:
            await super().process_commands(message)

    async def _on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CheckFailure) and str(error) == PREMIUM_REQUIRED:
            embed = build_upgrade_embed(self.config.premium)
            view = build_upgrade_view(self.config.premium)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            except discord.HTTPException:
                _log.exception("Failed to send premium upgrade embed")
            return
        _log.exception("Unhandled app command error", exc_info=error)

    async def _on_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if isinstance(error, commands.CheckFailure) and str(error) == PREMIUM_REQUIRED:
            embed = build_upgrade_embed(self.config.premium)
            view = build_upgrade_view(self.config.premium)
            try:
                await ctx.reply(embed=embed, view=view, mention_author=False)
            except discord.HTTPException:
                _log.exception("Failed to send premium upgrade embed")
