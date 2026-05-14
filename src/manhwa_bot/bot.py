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

from .cache import TtlCache
from .checks import PREMIUM_REQUIRED
from .cogs import COGS
from .config import AppConfig
from .crawler.client import CrawlerClient
from .crawler.errors import CrawlerError, Disconnected, RequestTimeout
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
from .ui.components.error import (
    SOURCE_BOT,
    SOURCE_COOLDOWN,
    SOURCE_CRAWLER,
    SOURCE_PERMISSION,
    build_error_view,
)
from .ui.components.upgrade import build_upgrade_view

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
    websites_cache: TtlCache[list]

    def __init__(self, config: AppConfig, db: DbPool, crawler: CrawlerClient) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = False

        allowed_mentions = discord.AllowedMentions(
            everyone=False,
            roles=True,
            users=True,
        )

        super().__init__(
            command_prefix=commands.when_mentioned_or(config.bot.command_prefix),
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

        self.websites_cache: TtlCache[list] = TtlCache()

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

    async def _on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CheckFailure) and str(error) == PREMIUM_REQUIRED:
            view = build_upgrade_view(self.config.premium, bot=self)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(view=view, ephemeral=True)
                else:
                    await interaction.response.send_message(view=view, ephemeral=True)
            except discord.HTTPException:
                _log.exception("Failed to send premium upgrade view")
            return

        original = getattr(error, "original", None) or error
        source, message = _user_message_for_error(original)

        cmd_name = interaction.command.qualified_name if interaction.command is not None else "?"
        _log.exception("App command error in /%s", cmd_name, exc_info=original)

        try:
            view = build_error_view(message, source=source, bot=self)
            if interaction.response.is_done():
                await interaction.followup.send(view=view, ephemeral=True)
            else:
                await interaction.response.send_message(view=view, ephemeral=True)
        except discord.HTTPException:
            _log.exception("Failed to send error view for /%s", cmd_name)

    async def _on_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if isinstance(error, commands.CheckFailure) and str(error) == PREMIUM_REQUIRED:
            view = build_upgrade_view(self.config.premium, bot=self)
            try:
                await ctx.reply(view=view, mention_author=False)
            except discord.HTTPException:
                _log.exception("Failed to send premium upgrade view")


_CRAWLER_ERROR_MESSAGES: dict[str, str] = {
    "rate_limited": "You're going too fast — please wait a few seconds and try again.",
    "website_blocked": "That website is currently blocking us. We'll try again shortly.",
    "page_blocked": "The crawler was blocked while trying to reach that page.",
    "website_disabled": "That website is temporarily disabled.",
    "not_found": "That series could not be found.",
    "tracking_seed_failed": "Couldn't fetch this series right now — try again later.",
    "unavailable": "The crawler service is temporarily unavailable.",
    "unknown_type": "This action isn't supported right now.",
}


def _user_message_for_error(exc: BaseException) -> tuple[str, str]:
    """Map an exception to (source_label, user_facing_message)."""
    if isinstance(exc, RequestTimeout):
        return SOURCE_CRAWLER, (
            "The crawler took too long to respond. Please try again in a moment."
        )
    if isinstance(exc, Disconnected):
        return SOURCE_CRAWLER, ("The connection to the crawler was interrupted. Please try again.")
    if isinstance(exc, CrawlerError):
        msg = (exc.message or "").lower()
        if exc.code == "invalid_request" and ("url template" in msg or "url rebuild failed" in msg):
            return SOURCE_CRAWLER, (
                "That URL is not in a valid format for this website. "
                "Use the autocomplete or paste a full series URL."
            )
        mapped = _CRAWLER_ERROR_MESSAGES.get(exc.code)
        if mapped:
            return SOURCE_CRAWLER, mapped
        if exc.code == "invalid_request":
            return SOURCE_CRAWLER, exc.message or "Invalid request."
        return SOURCE_CRAWLER, f"[{exc.code}] {exc.message}"

    if isinstance(exc, app_commands.CommandOnCooldown):
        retry = getattr(exc, "retry_after", 0.0) or 0.0
        return SOURCE_COOLDOWN, f"Slow down — try again in {retry:.0f}s."
    if isinstance(exc, app_commands.MissingPermissions):
        perms = ", ".join(getattr(exc, "missing_permissions", []) or []) or "permissions"
        return SOURCE_PERMISSION, (f"You're missing the required {perms} to use this command.")
    if isinstance(exc, app_commands.BotMissingPermissions):
        perms = ", ".join(getattr(exc, "missing_permissions", []) or []) or "permissions"
        return SOURCE_PERMISSION, (f"I'm missing the required {perms} to run this command here.")
    if isinstance(exc, app_commands.CheckFailure):
        return SOURCE_PERMISSION, "You don't have permission to use this command here."

    rid = getattr(exc, "request_id", None) or "n/a"
    return SOURCE_BOT, (f"Something went wrong. Please try again later. (request_id: {rid})")
