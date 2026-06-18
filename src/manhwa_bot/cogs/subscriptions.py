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


async def _add_role_safe(
    interaction: discord.Interaction, role: discord.Role
) -> discord.Role | None:
    """Add *role* to the invoker. Returns the role on success, ``None`` on failure.

    Treats "user already has the role" as success.
    """
    member = interaction.user
    if not isinstance(member, discord.Member):
        return None
    if role in member.roles:
        return role
    try:
        await member.add_roles(role, reason="ManhwaUpdatesBot: /subscribe")
    except discord.Forbidden, discord.HTTPException:
        _log.exception("failed to assign role %s to user %s", role.id, member.id)
        return None
    return role


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

    async def _guild_tracked_pairs(self, guild_id: int) -> list[tuple[str, str]]:
        rows = await self._tracked.list_for_guild(guild_id, limit=2000)
        return [(row.website_key, row.url_name) for row in rows]

    async def _user_subscription_pairs(self, user_id: int, guild_id: int) -> list[tuple[str, str]]:
        rows = await self._subs.list_for_user(user_id, guild_id=guild_id, limit=2000)
        return [(row["website_key"], row["url_name"]) for row in rows]

    # -- /subscribe new ---------------------------------------------------------

    @subscribe.command(
        name="new",
        description="Subscribe to a tracked manga to get new release notifications.",
    )
    @app_commands.describe(
        manga_id="The name of the tracked manga you want to subscribe to.",
    )
    @app_commands.autocomplete(manga_id=autocomplete.tracked_manga_in_guild_with_all)
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
            await self._handle_assign_default_role(interaction, guild_id)
            return

        parsed = await autocomplete.resolve_series_value_async(
            manga_id, lambda: self._guild_tracked_pairs(guild_id)
        )
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

        ping_role = await self._assign_series_ping_role(
            interaction, guild_id, website_key, url_name
        )

        view = build_subscribe_success_view(
            title=series_match.title,
            series_url=series_match.series_url,
            ping_role=ping_role,
            notif_channel=notif_channel,
            cover_url=series_match.cover_url,
            is_dm=interaction.guild_id is None,
            bot=self.bot,
        )
        await interaction.followup.send(view=view, ephemeral=True)

    async def _assign_series_ping_role(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        website_key: str,
        url_name: str,
    ) -> discord.Role | None:
        """Assign the per-series ping role to the invoker, if one is configured."""
        if guild_id == 0 or interaction.guild is None:
            return None
        guild_list = await self._tracked.list_for_guild(guild_id, limit=500)
        row = next(
            (s for s in guild_list if s.website_key == website_key and s.url_name == url_name),
            None,
        )
        if row is None or row.ping_role_id is None:
            return None
        role = interaction.guild.get_role(row.ping_role_id)
        if role is None:
            return None
        return await _add_role_safe(interaction, role)

    async def _handle_assign_default_role(
        self, interaction: discord.Interaction, guild_id: int
    ) -> None:
        """Handle /subscribe new manga=All — assign the guild's default ping role."""
        if guild_id == 0 or interaction.guild is None:
            await interaction.followup.send(
                view=build_error_view("The 'All' option only works inside a server.", bot=self.bot),
                ephemeral=True,
            )
            return

        gs = await self._guild_settings.get(guild_id)
        if gs is None or gs.default_ping_role_id is None:
            await interaction.followup.send(
                view=build_error_view(
                    "This server has no default ping role configured.", bot=self.bot
                ),
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(gs.default_ping_role_id)
        if role is None:
            await interaction.followup.send(
                view=build_error_view(
                    "The configured default ping role no longer exists.", bot=self.bot
                ),
                ephemeral=True,
            )
            return

        assigned = await _add_role_safe(interaction, role)
        if assigned is None:
            await interaction.followup.send(
                view=build_error_view(
                    f"I couldn't assign {role.mention} — check my permissions and role order.",
                    bot=self.bot,
                ),
                ephemeral=True,
            )
            return

        member = interaction.user
        already_had = isinstance(member, discord.Member) and role in member.roles
        title = (
            f"{emojis.CHECK}  Already have the role"
            if already_had
            else f"{emojis.CHECK}  Role assigned"
        )
        description = (
            f"You already have {role.mention} — you'll keep getting all update pings."
            if already_had
            else f"You've been given {role.mention} and will receive all update pings."
        )
        await interaction.followup.send(
            view=build_simple_status_view(
                title=title,
                description=description,
                accent=discord.Colour.green(),
                bot=self.bot,
            ),
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

        parsed = await autocomplete.resolve_series_value_async(
            manga_id, lambda: self._user_subscription_pairs(interaction.user.id, guild_id)
        )
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

            # build_grouped_list_views groups by scanlator and sorts by title.
            items = [
                {
                    "title": s.get("title") or s.get("url_name") or "Unknown",
                    "url": s.get("series_url") or "",
                    "website_key": s.get("website_key") or "",
                    "last_chapter": (
                        f"Last read: {s['last_read_chapter']}"
                        if s.get("last_read_chapter")
                        else None
                    ),
                }
                for s in subs
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
