"""Subscriptions cog — /subscribe new|delete|list."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import autocomplete
from ..checks import has_premium
from ..db.guild_settings import GuildSettingsStore
from ..db.subscriptions import SubscriptionStore
from ..db.tracked import TrackedStore
from ..ui import emojis
from ..ui.components.confirm import ConfirmLayoutView
from ..ui.components.error import build_error_view
from ..ui.components.paginator import LayoutPaginator
from ..ui.components.tracking import (
    build_bulk_subscribe_result_view,
    build_grouped_list_views,
    build_simple_status_view,
    build_subscribe_success_view,
    build_unsubscribe_view,
)

_log = logging.getLogger(__name__)

_LIST_PAGE_SIZE = 15


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

        if manga_id == "*":
            await self._handle_subscribe_all(interaction, guild_id)
            return

        parsed = _parse_manga_id(manga_id)
        if parsed is None:
            await interaction.followup.send(
                view=build_error_view(
                    "Invalid manga ID format. Use autocomplete to select.", bot=self.bot
                ),
                ephemeral=True,
            )
            return

        website_key, url_name = parsed

        tracked_list = await self._tracked.list_for_guild(guild_id, limit=500)
        series_match = None
        for series in tracked_list:
            if series.website_key == website_key and series.url_name == url_name:
                series_match = series
                break

        if series_match is None:
            await interaction.followup.send(
                view=build_error_view("That series is not tracked in this guild.", bot=self.bot),
                ephemeral=True,
            )
            return

        is_sub = await self._subs.is_subscribed(
            interaction.user.id, guild_id, website_key, url_name
        )
        if is_sub:
            await interaction.followup.send(
                view=build_error_view("You're already subscribed to that manga.", bot=self.bot),
                ephemeral=True,
            )
            return

        try:
            await self._subs.subscribe(interaction.user.id, guild_id, website_key, url_name)
        except Exception as exc:
            _log.exception("subscribe failed")
            await interaction.followup.send(
                view=build_error_view(f"Failed to subscribe: {exc}", bot=self.bot),
                ephemeral=True,
            )
            return

        gs = await self._guild_settings.get(guild_id) if guild_id else None
        notif_channel = None
        if gs and gs.notifications_channel_id and interaction.guild:
            notif_channel = interaction.guild.get_channel(gs.notifications_channel_id)
        view = build_subscribe_success_view(
            title=series_match.title,
            series_url=series_match.series_url,
            ping_role=None,
            notif_channel=notif_channel,
            cover_url=series_match.cover_url,
            is_dm=interaction.guild_id is None,
            bot=self.bot,
        )
        await interaction.followup.send(view=view, ephemeral=True)

    async def _handle_subscribe_all(self, interaction: discord.Interaction, guild_id: int) -> None:
        """Handle /subscribe new manga_id=*."""
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
                    view=build_simple_status_view(
                        title=f"{emojis.CHECK}  Already subscribed",
                        description="You're already subscribed to every tracked series here.",
                        accent=discord.Colour.green(),
                        bot=self.bot,
                    ),
                    ephemeral=True,
                )
                return

            confirm = ConfirmLayoutView(
                author_id=interaction.user.id,
                prompt=(
                    f"You are about to subscribe to an additional **{len(to_subscribe)}** "
                    "tracked series from this server.\n\n**Do you wish to continue?**"
                ),
                prompt_title="Subscribe to all?",
                bot=self.bot,
            )
            confirm_msg = await interaction.followup.send(view=confirm, ephemeral=True, wait=True)
            confirm.bind_message(confirm_msg)
            await confirm.wait()

            if confirm.value is not True:
                await interaction.edit_original_response(
                    view=build_simple_status_view(
                        title="Operation cancelled",
                        description="No subscriptions were created.",
                        accent=discord.Colour.greyple(),
                        bot=self.bot,
                    ),
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

            await interaction.edit_original_response(
                view=build_bulk_subscribe_result_view(
                    successes=successes, fails=fails, action="subscribe", bot=self.bot
                ),
            )
        except Exception as exc:
            _log.exception("batch subscribe failed")
            await interaction.followup.send(
                view=build_error_view(f"Batch subscribe failed: {exc}", bot=self.bot),
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

        if manga_id == "*":
            await self._handle_unsubscribe_all(interaction, guild_id)
            return

        parsed = _parse_manga_id(manga_id)
        if parsed is None:
            await interaction.followup.send(
                view=build_error_view("Invalid manga ID format.", bot=self.bot),
                ephemeral=True,
            )
            return

        website_key, url_name = parsed

        is_sub = await self._subs.is_subscribed(
            interaction.user.id, guild_id, website_key, url_name
        )
        if not is_sub:
            await interaction.followup.send(
                view=build_error_view("You're not subscribed to that manga.", bot=self.bot),
                ephemeral=True,
            )
            return

        try:
            await self._subs.unsubscribe(interaction.user.id, guild_id, website_key, url_name)
        except Exception as exc:
            _log.exception("unsubscribe failed")
            await interaction.followup.send(
                view=build_error_view(f"Failed to unsubscribe: {exc}", bot=self.bot),
                ephemeral=True,
            )
            return

        tracked_list = await self._tracked.list_for_guild(guild_id, limit=500)
        series_match = next(
            (s for s in tracked_list if s.website_key == website_key and s.url_name == url_name),
            None,
        )
        title = series_match.title if series_match else f"{website_key}:{url_name}"
        url = series_match.series_url if series_match else None
        view = build_unsubscribe_view(title=title, series_url=url, bot=self.bot)
        await interaction.followup.send(view=view, ephemeral=True)

    async def _handle_unsubscribe_all(
        self, interaction: discord.Interaction, guild_id: int
    ) -> None:
        """Handle /subscribe delete manga_id=*."""
        try:
            subs = await self._subs.list_for_user(interaction.user.id, guild_id=guild_id, limit=500)
            if not subs:
                await interaction.followup.send(
                    view=build_simple_status_view(
                        title=f"{emojis.CHECK}  Nothing to unsubscribe from",
                        description="You have no subscriptions in this server.",
                        accent=discord.Colour.green(),
                        bot=self.bot,
                    ),
                    ephemeral=True,
                )
                return

            confirm = ConfirmLayoutView(
                author_id=interaction.user.id,
                prompt=(
                    f"You are about to unsubscribe from **{len(subs)}** subscribed series "
                    "from this server.\n\n**Do you wish to continue?**"
                ),
                prompt_title="Unsubscribe from all?",
                bot=self.bot,
            )
            confirm_msg = await interaction.followup.send(view=confirm, ephemeral=True, wait=True)
            confirm.bind_message(confirm_msg)
            await confirm.wait()

            if confirm.value is not True:
                await interaction.edit_original_response(
                    view=build_simple_status_view(
                        title="Operation cancelled",
                        description="No subscriptions were removed.",
                        accent=discord.Colour.greyple(),
                        bot=self.bot,
                    ),
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

            await interaction.edit_original_response(
                view=build_bulk_subscribe_result_view(
                    successes=successes, fails=fails, action="unsubscribe", bot=self.bot
                ),
            )
        except Exception as exc:
            _log.exception("batch unsubscribe failed")
            await interaction.followup.send(
                view=build_error_view(f"Batch unsubscribe failed: {exc}", bot=self.bot),
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
            pages = build_grouped_list_views(
                items,
                title=f"{title_prefix} ({count})",
                bot=self.bot,
                empty_title="No Subscriptions",
                empty_description="You have no subscriptions.",
                invoker_id=interaction.user.id,
            )

            if len(pages) == 1:
                await interaction.followup.send(view=pages[0], ephemeral=True)
                return

            paginator = LayoutPaginator(pages, invoker_id=interaction.user.id)
            msg = await interaction.followup.send(
                view=paginator.current_view, ephemeral=True, wait=True
            )
            paginator.bind_message(msg)
        except Exception as exc:
            _log.exception("list subscriptions failed")
            await interaction.followup.send(
                view=build_error_view(f"Failed to list subscriptions: {exc}", bot=self.bot),
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SubscriptionsCog(bot))
