"""Subscriptions cog — /subscribe new|delete|list."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import autocomplete, formatting
from ..checks import has_premium
from ..db.guild_settings import GuildSettingsStore
from ..db.subscriptions import SubscriptionStore
from ..db.tracked import TrackedStore
from ..ui.confirm_view import ConfirmView
from ..ui.paginator import Paginator

_log = logging.getLogger(__name__)

_LIST_PAGE_SIZE = 15


def _error_embed(description: str) -> discord.Embed:
    """Build a red error embed."""
    return discord.Embed(
        title="Error",
        description=description,
        colour=discord.Colour.red(),
    )


def _parse_manga_id(manga_id: str) -> tuple[str, str] | None:
    """Parse manga_id from 'website_key:url_name' format.

    Returns (website_key, url_name) or None if invalid.
    """
    if ":" not in manga_id:
        return None
    parts = manga_id.split(":", 1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else None


class SubscriptionsCog(commands.Cog, name="Subscriptions"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._subs = SubscriptionStore(bot.db)  # type: ignore[attr-defined]
        self._tracked = TrackedStore(bot.db)  # type: ignore[attr-defined]
        self._guild_settings = GuildSettingsStore(bot.db)  # type: ignore[attr-defined]

    subscribe = app_commands.Group(
        name="subscribe",
        description="Subscribe to a manga to get notifications.",
        guild_only=False,
    )

    # -- /subscribe new ---------------------------------------------------------

    @subscribe.command(
        name="new",
        description="Subscribe to a tracked manga to get new release notifications.",
    )
    @app_commands.describe(
        manga_id="The name of the tracked manga you want to subscribe to.",
    )
    @app_commands.autocomplete(manga_id=autocomplete.tracked_manga_in_guild)
    @app_commands.rename(manga_id="manga")
    @has_premium(dm_only=True)
    async def subscribe_new(
        self,
        interaction: discord.Interaction,
        manga_id: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild_id or 0

        # Handle wildcard: subscribe to all tracked series
        if manga_id == "*":
            await self._handle_subscribe_all(interaction, guild_id)
            return

        # Parse manga_id
        parsed = _parse_manga_id(manga_id)
        if parsed is None:
            await interaction.followup.send(
                embed=_error_embed("Invalid manga ID format. Use autocomplete to select."),
                ephemeral=True,
            )
            return

        website_key, url_name = parsed

        # Verify series is tracked in guild (defensive check)
        tracked_list = await self._tracked.list_for_guild(guild_id, limit=500)
        series_match = None
        for series in tracked_list:
            if series.website_key == website_key and series.url_name == url_name:
                series_match = series
                break

        if series_match is None:
            await interaction.followup.send(
                embed=_error_embed("That series is not tracked in this guild."),
                ephemeral=True,
            )
            return

        # Check if already subscribed
        is_sub = await self._subs.is_subscribed(
            interaction.user.id, guild_id, website_key, url_name
        )
        if is_sub:
            await interaction.followup.send(
                embed=_error_embed("You're already subscribed to that manga."),
                ephemeral=True,
            )
            return

        # Subscribe
        try:
            await self._subs.subscribe(interaction.user.id, guild_id, website_key, url_name)
        except Exception as exc:
            _log.exception("subscribe failed")
            await interaction.followup.send(
                embed=_error_embed(f"Failed to subscribe: {exc}"),
                ephemeral=True,
            )
            return

        # V1-style success embed
        gs = await self._guild_settings.get(guild_id) if guild_id else None
        notif_channel = None
        if gs and gs.notifications_channel_id and interaction.guild:
            notif_channel = interaction.guild.get_channel(gs.notifications_channel_id)
        embed = formatting.subscribe_success_embed(
            title=series_match.title,
            series_url=series_match.series_url,
            ping_role=None,  # ping_role lookup is part of /track update; v1 also resolves via guild
            notif_channel=notif_channel,
            cover_url=series_match.cover_url,
            is_dm=interaction.guild_id is None,
            bot=self.bot,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_subscribe_all(self, interaction: discord.Interaction, guild_id: int) -> None:
        """Handle /subscribe new manga_id=*. Prompts via ConfirmView like v1."""
        try:
            tracked_list = await self._tracked.list_for_guild(guild_id, limit=500)
            existing_subs = await self._subs.list_for_user(
                interaction.user.id, guild_id=guild_id, limit=500
            )
            existing_set = {(s["website_key"], s["url_name"]) for s in existing_subs}
            to_subscribe = [
                s for s in tracked_list if (s.website_key, s.url_name) not in existing_set
            ]

            if not to_subscribe:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="Already subscribed",
                        description="You're already subscribed to every tracked series here.",
                        colour=discord.Colour.green(),
                    ),
                    ephemeral=True,
                )
                return

            prompt = discord.Embed(
                description=(
                    f"You are about to subscribe to an additional **{len(to_subscribe)}** "
                    f"tracked series from this server.\n\n**Do you wish to continue?**"
                ),
                colour=discord.Colour.blurple(),
            )
            confirm = ConfirmView(author_id=interaction.user.id)
            confirm.message = await interaction.followup.send(
                embed=prompt, view=confirm, ephemeral=True, wait=True
            )
            await confirm.wait()

            if confirm.value is not True:
                await interaction.edit_original_response(
                    embed=discord.Embed(
                        title="Operation cancelled!", colour=discord.Colour.green()
                    ),
                    view=None,
                )
                return

            successes = 0
            fails = 0
            for series in to_subscribe:
                try:
                    await self._subs.subscribe(
                        interaction.user.id, guild_id, series.website_key, series.url_name
                    )
                    successes += 1
                except Exception:
                    _log.exception(
                        "batch subscribe failed for %s:%s", series.website_key, series.url_name
                    )
                    fails += 1

            description = f"You have successfully subscribed to {successes} series!"
            if fails:
                description += (
                    f"\n\n**Note:** I was unable to subscribe to {fails} series. "
                    "Double check my permissions and try again!"
                )
            colour = discord.Colour.orange() if fails else discord.Colour.green()
            await interaction.edit_original_response(
                embed=discord.Embed(title="Subscribed", description=description, colour=colour),
                view=None,
            )
        except Exception as exc:
            _log.exception("batch subscribe failed")
            await interaction.followup.send(
                embed=_error_embed(f"Batch subscribe failed: {exc}"),
                ephemeral=True,
            )

    # -- /subscribe delete ---------------------------------------------------------

    @subscribe.command(name="delete", description="Unsubscribe from a currently subscribed manga.")
    @app_commands.describe(
        manga_id="The name of the manga.",
    )
    @app_commands.autocomplete(manga_id=autocomplete.user_subscribed_manga)
    @app_commands.rename(manga_id="manga")
    @has_premium(dm_only=True)
    async def subscribe_delete(
        self,
        interaction: discord.Interaction,
        manga_id: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild_id or 0

        # Handle wildcard: unsubscribe from all
        if manga_id == "*":
            await self._handle_unsubscribe_all(interaction, guild_id)
            return

        # Parse manga_id
        parsed = _parse_manga_id(manga_id)
        if parsed is None:
            await interaction.followup.send(
                embed=_error_embed("Invalid manga ID format."),
                ephemeral=True,
            )
            return

        website_key, url_name = parsed

        # Check if subscribed
        is_sub = await self._subs.is_subscribed(
            interaction.user.id, guild_id, website_key, url_name
        )
        if not is_sub:
            await interaction.followup.send(
                embed=_error_embed("You're not subscribed to that manga."),
                ephemeral=True,
            )
            return

        # Unsubscribe
        try:
            await self._subs.unsubscribe(interaction.user.id, guild_id, website_key, url_name)
        except Exception as exc:
            _log.exception("unsubscribe failed")
            await interaction.followup.send(
                embed=_error_embed(f"Failed to unsubscribe: {exc}"),
                ephemeral=True,
            )
            return

        # V1-style "Unsubscribed" embed.
        tracked_list = await self._tracked.list_for_guild(guild_id, limit=500)
        series_match = next(
            (s for s in tracked_list if s.website_key == website_key and s.url_name == url_name),
            None,
        )
        title = series_match.title if series_match else f"{website_key}:{url_name}"
        url = series_match.series_url if series_match else None
        if url:
            description = f"Successfully unsubscribed from **[{title}]({url})**."
        else:
            description = f"Successfully unsubscribed from **{title}**."

        embed = discord.Embed(
            title="Unsubscribed",
            description=description,
            colour=discord.Colour.green(),
        )
        formatting._set_mu_footer(embed, self.bot)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_unsubscribe_all(
        self, interaction: discord.Interaction, guild_id: int
    ) -> None:
        """Handle /subscribe delete manga_id=*. Prompts via ConfirmView like v1."""
        try:
            subs = await self._subs.list_for_user(interaction.user.id, guild_id=guild_id, limit=500)
            if not subs:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="Nothing to unsubscribe from",
                        description="You have no subscriptions in this server.",
                        colour=discord.Colour.green(),
                    ),
                    ephemeral=True,
                )
                return

            prompt = discord.Embed(
                description=(
                    f"You are about to unsubscribe from **{len(subs)}** subbed series "
                    f"from this server.\n\n**Do you wish to continue?**"
                ),
                colour=discord.Colour.blurple(),
            )
            confirm = ConfirmView(author_id=interaction.user.id)
            confirm.message = await interaction.followup.send(
                embed=prompt, view=confirm, ephemeral=True, wait=True
            )
            await confirm.wait()

            if confirm.value is not True:
                await interaction.edit_original_response(
                    embed=discord.Embed(
                        title="Operation cancelled!", colour=discord.Colour.green()
                    ),
                    view=None,
                )
                return

            successes = 0
            fails = 0
            for sub in subs:
                try:
                    await self._subs.unsubscribe(
                        interaction.user.id, guild_id, sub["website_key"], sub["url_name"]
                    )
                    successes += 1
                except Exception:
                    _log.exception(
                        "batch unsubscribe failed for %s:%s",
                        sub.get("website_key"),
                        sub.get("url_name"),
                    )
                    fails += 1

            description = f"You have successfully unsubscribed from {successes} series!"
            if fails:
                description += (
                    f"\n\n**Note:** I was unable to unsubscribe you from {fails} series. "
                    "Double check my permissions and try again!"
                )
            colour = discord.Colour.orange() if fails else discord.Colour.green()
            await interaction.edit_original_response(
                embed=discord.Embed(title="Unsubscribed", description=description, colour=colour),
                view=None,
            )
        except Exception as exc:
            _log.exception("batch unsubscribe failed")
            await interaction.followup.send(
                embed=_error_embed(f"Batch unsubscribe failed: {exc}"),
                ephemeral=True,
            )

    # -- /subscribe list ---------------------------------------------------------

    @subscribe.command(name="list", description="List all the manga you're subscribed to.")
    @app_commands.describe(
        _global="Whether to show your subscriptions in all servers.",
    )
    @app_commands.rename(_global="global")
    @has_premium(dm_only=True)
    async def subscribe_list(
        self,
        interaction: discord.Interaction,
        _global: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild_id if not _global else None

        try:
            subs = await self._subs.list_for_user(interaction.user.id, guild_id=guild_id, limit=500)

            sorted_subs = sorted(subs, key=lambda s: str(s.get("title") or "").lower())
            items = [
                {
                    "title": s.get("title") or s.get("url_name") or "Unknown",
                    "url": s.get("series_url") or "",
                    "website_key": s.get("website_key") or "",
                    "last_chapter": None,
                }
                for s in sorted_subs
            ]
            count = len(items)
            title_prefix = "Your (Global) Subscriptions" if _global else "Your Subscriptions"
            embeds = formatting.grouped_list_embeds(
                items,
                title=f"{title_prefix} ({count})",
                bot=self.bot,
                empty_title="No Subscriptions",
                empty_description="You have no subscriptions.",
            )

            if len(embeds) == 1:
                await interaction.followup.send(embed=embeds[0], ephemeral=True)
            else:
                paginator = Paginator(embeds, invoker_id=interaction.user.id)
                await interaction.followup.send(embed=embeds[0], view=paginator, ephemeral=True)
        except Exception as exc:
            _log.exception("list subscriptions failed")
            await interaction.followup.send(
                embed=_error_embed(f"Failed to list subscriptions: {exc}"),
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SubscriptionsCog(bot))
