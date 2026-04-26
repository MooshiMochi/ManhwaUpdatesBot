"""Subscriptions cog — /subscribe new|delete|list."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .. import autocomplete
from ..checks import has_premium
from ..db.guild_settings import GuildSettingsStore
from ..db.subscriptions import SubscriptionStore
from ..db.tracked import TrackedStore
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
        description="Manage manga subscriptions for DM notifications",
        guild_only=False,
    )

    # -- /subscribe new ---------------------------------------------------------

    @subscribe.command(name="new", description="Subscribe to a manga for DM notifications")
    @app_commands.describe(
        manga_id="The manga to subscribe to (or * for all guild tracked)",
    )
    @app_commands.autocomplete(manga_id=autocomplete.tracked_manga_in_guild)
    @has_premium(dm_only=True)
    async def subscribe_new(
        self,
        interaction: discord.Interaction,
        manga_id: str,
    ) -> None:
        await interaction.response.defer(ephemeral=False)

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

        # Build confirmation embed
        embed = await self._build_subscription_embed(
            title="✓ Subscribed",
            series=series_match,
            guild_id=guild_id,
            color=discord.Colour.green(),
        )
        await interaction.followup.send(embed=embed, ephemeral=False)

    async def _handle_subscribe_all(self, interaction: discord.Interaction, guild_id: int) -> None:
        """Handle /subscribe new manga_id:*."""
        try:
            # Fetch all tracked series in guild
            tracked_list = await self._tracked.list_for_guild(guild_id, limit=500)

            # Fetch user's existing subs in guild
            existing_subs = await self._subs.list_for_user(
                interaction.user.id, guild_id=guild_id, limit=500
            )
            existing_set = {(sub["website_key"], sub["url_name"]) for sub in existing_subs}

            # Compute diff
            to_subscribe = [
                s for s in tracked_list if (s.website_key, s.url_name) not in existing_set
            ]

            # Subscribe to all
            for series in to_subscribe:
                await self._subs.subscribe(
                    interaction.user.id, guild_id, series.website_key, series.url_name
                )

            # Build batch confirmation embed
            total = len(tracked_list)
            added = len(to_subscribe)
            skipped = len(existing_subs)

            embed = discord.Embed(
                title="Batch Subscribe",
                description=f"Subscribed to {added} manga",
                colour=discord.Colour.blue(),
            )
            if interaction.guild:
                embed.add_field(name="Guild", value=interaction.guild.name, inline=False)
            embed.add_field(name="Added", value=str(added), inline=True)
            embed.add_field(name="Already subscribed", value=str(skipped), inline=True)
            embed.add_field(name="Total tracked", value=str(total), inline=True)

            await interaction.followup.send(embed=embed, ephemeral=False)
        except Exception as exc:
            _log.exception("batch subscribe failed")
            await interaction.followup.send(
                embed=_error_embed(f"Batch subscribe failed: {exc}"),
                ephemeral=True,
            )

    # -- /subscribe delete ---------------------------------------------------------

    @subscribe.command(name="delete", description="Unsubscribe from a manga")
    @app_commands.describe(
        manga_id="The manga to unsubscribe from (or * for all)",
    )
    @app_commands.autocomplete(manga_id=autocomplete.user_subscribed_manga)
    @has_premium(dm_only=True)
    async def subscribe_delete(
        self,
        interaction: discord.Interaction,
        manga_id: str,
    ) -> None:
        await interaction.response.defer(ephemeral=False)

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

        # Build confirmation embed (fetch series info if possible)
        tracked_list = await self._tracked.list_for_guild(guild_id, limit=500)
        series_match = None
        for series in tracked_list:
            if series.website_key == website_key and series.url_name == url_name:
                series_match = series
                break

        if series_match:
            embed = await self._build_subscription_embed(
                title="✗ Unsubscribed",
                series=series_match,
                guild_id=guild_id,
                color=discord.Colour.red(),
            )
        else:
            embed = discord.Embed(
                title="✗ Unsubscribed",
                description=f"{website_key}:{url_name}",
                colour=discord.Colour.red(),
            )

        await interaction.followup.send(embed=embed, ephemeral=False)

    async def _handle_unsubscribe_all(
        self, interaction: discord.Interaction, guild_id: int
    ) -> None:
        """Handle /subscribe delete manga_id:*."""
        try:
            # Fetch user's subs in guild
            subs = await self._subs.list_for_user(interaction.user.id, guild_id=guild_id, limit=500)

            # Unsubscribe from all
            for sub in subs:
                await self._subs.unsubscribe(
                    interaction.user.id, guild_id, sub["website_key"], sub["url_name"]
                )

            # Build confirmation embed
            count = len(subs)
            embed = discord.Embed(
                title="Batch Unsubscribe",
                description=f"Unsubscribed from {count} manga",
                colour=discord.Colour.orange(),
            )
            if interaction.guild:
                embed.add_field(name="Guild", value=interaction.guild.name, inline=False)
            embed.add_field(name="Removed", value=str(count), inline=True)

            await interaction.followup.send(embed=embed, ephemeral=False)
        except Exception as exc:
            _log.exception("batch unsubscribe failed")
            await interaction.followup.send(
                embed=_error_embed(f"Batch unsubscribe failed: {exc}"),
                ephemeral=True,
            )

    # -- /subscribe list ---------------------------------------------------------

    @subscribe.command(name="list", description="View your manga subscriptions")
    @app_commands.describe(
        _global="Show subscriptions across all guilds (default: current guild only)",
    )
    @has_premium(dm_only=True)
    async def subscribe_list(
        self,
        interaction: discord.Interaction,
        _global: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=False)

        guild_id = interaction.guild_id if not _global else None

        try:
            # Fetch subscriptions
            subs = await self._subs.list_for_user(interaction.user.id, guild_id=guild_id, limit=500)

            if not subs:
                embed = discord.Embed(
                    title="No Subscriptions",
                    description="You don't have any subscriptions yet.",
                    colour=discord.Colour.greyple(),
                )
                await interaction.followup.send(embed=embed, ephemeral=False)
                return

            # Build paginated embeds
            embeds = await self._build_list_embeds(subs, global_view=_global)

            # Send with paginator if needed
            if len(embeds) == 1:
                await interaction.followup.send(embed=embeds[0], ephemeral=False)
            else:
                paginator = Paginator(embeds, invoker_id=interaction.user.id)
                await interaction.followup.send(embed=embeds[0], view=paginator, ephemeral=False)
        except Exception as exc:
            _log.exception("list subscriptions failed")
            await interaction.followup.send(
                embed=_error_embed(f"Failed to list subscriptions: {exc}"),
                ephemeral=True,
            )

    # -- Helper methods ---------------------------------------------------------

    async def _build_subscription_embed(
        self,
        title: str,
        series: Any,
        guild_id: int,
        color: discord.Colour,
    ) -> discord.Embed:
        """Build a confirmation embed for subscribe/unsubscribe action."""
        embed = discord.Embed(
            title=title,
            description=f"**{series.title}**",
            colour=color,
            url=series.series_url,
        )

        # Add field for website
        embed.add_field(name="Website", value=series.website_key, inline=True)

        # Add field for notifications channel
        try:
            guild_settings = await self._guild_settings.get(guild_id)
            if guild_settings and guild_settings.notifications_channel_id:
                channel = self.bot.get_channel(guild_settings.notifications_channel_id)  # type: ignore[union-attr]
                if channel:
                    embed.add_field(name="Notifications", value=f"{channel.mention}", inline=True)
        except Exception:
            pass

        # Add status if available
        if series.status:
            embed.add_field(name="Status", value=series.status, inline=True)

        return embed

    async def _build_list_embeds(
        self, subs: list[dict], *, global_view: bool
    ) -> list[discord.Embed]:
        """Build paginated embeds for subscription list."""
        if not subs:
            return [
                discord.Embed(
                    title="No Subscriptions",
                    description="You don't have any subscriptions.",
                    colour=discord.Colour.greyple(),
                )
            ]

        # Group by guild (if global) or by website_key
        if global_view:
            # Group by guild_id, then by website_key
            grouped: dict[int, dict[str, list[dict]]] = {}
            for sub in subs:
                guild_id = sub["guild_id"]
                website_key = sub["website_key"]
                if guild_id not in grouped:
                    grouped[guild_id] = {}
                if website_key not in grouped[guild_id]:
                    grouped[guild_id][website_key] = []
                grouped[guild_id][website_key].append(sub)

            # Build embeds per guild
            embeds: list[discord.Embed] = []
            for guild_id in grouped:
                guild = self.bot.get_guild(guild_id)  # type: ignore[union-attr]
                guild_name = guild.name if guild else f"Guild {guild_id}"

                for website_key in grouped[guild_id]:
                    entries = grouped[guild_id][website_key]
                    # Split into pages
                    for i in range(0, len(entries), _LIST_PAGE_SIZE):
                        chunk = entries[i : i + _LIST_PAGE_SIZE]
                        lines = []
                        for sub in chunk:
                            title = sub.get("title", "Unknown")
                            url = sub.get("series_url", "")
                            subscribed_at = sub.get("subscribed_at", "N/A")
                            # Format date to short form (YYYY-MM-DD)
                            if isinstance(subscribed_at, str):
                                date_part = (
                                    subscribed_at.split()[0]
                                    if " " in subscribed_at
                                    else subscribed_at
                                )
                            else:
                                date_part = "N/A"
                            lines.append(f"[{title}]({url}) — {date_part}")

                        page_num = (i // _LIST_PAGE_SIZE) + 1
                        page_label = f"{guild_name} • {website_key} (page {page_num})"

                        embed = discord.Embed(
                            title="Your Subscriptions",
                            description="\n".join(lines) if lines else "No entries",
                            colour=discord.Colour.blurple(),
                        )
                        embed.set_footer(text=page_label)
                        embeds.append(embed)
        else:
            # Group by website_key only (single guild)
            grouped_by_site: dict[str, list[dict]] = {}
            for sub in subs:
                website_key = sub["website_key"]
                if website_key not in grouped_by_site:
                    grouped_by_site[website_key] = []
                grouped_by_site[website_key].append(sub)

            # Build embeds per website
            embeds = []
            for website_key in grouped_by_site:
                entries = grouped_by_site[website_key]
                # Split into pages
                for i in range(0, len(entries), _LIST_PAGE_SIZE):
                    chunk = entries[i : i + _LIST_PAGE_SIZE]
                    lines = []
                    for sub in chunk:
                        title = sub.get("title", "Unknown")
                        url = sub.get("series_url", "")
                        subscribed_at = sub.get("subscribed_at", "N/A")
                        if isinstance(subscribed_at, str):
                            date_part = (
                                subscribed_at.split()[0] if " " in subscribed_at else subscribed_at
                            )
                        else:
                            date_part = "N/A"
                        lines.append(f"[{title}]({url}) — {date_part}")

                    page_num = (i // _LIST_PAGE_SIZE) + 1
                    page_label = f"{website_key} (page {page_num})"

                    embed = discord.Embed(
                        title="Your Subscriptions",
                        description="\n".join(lines) if lines else "No entries",
                        colour=discord.Colour.blurple(),
                    )
                    embed.set_footer(text=page_label)
                    embeds.append(embed)

        return (
            embeds
            if embeds
            else [
                discord.Embed(
                    title="No Subscriptions",
                    description="You don't have any subscriptions.",
                    colour=discord.Colour.greyple(),
                )
            ]
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SubscriptionsCog(bot))
