"""Tracking cog — /track new|update|remove|list."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .. import autocomplete
from ..checks import has_premium
from ..crawler.errors import CrawlerError, Disconnected, RequestTimeout
from ..crawler.website_detect import detect_website_key
from ..db.guild_settings import GuildSettingsStore
from ..db.tracked import TrackedStore
from ..ui.components.error import SOURCE_CRAWLER, build_error_view
from ..ui.components.paginator import LayoutPaginator
from ..ui.components.progress import ProgressLayoutState, progress_event_message
from ..ui.components.tracking import (
    build_grouped_list_views,
    build_role_hierarchy_view,
    build_role_managed_view,
    build_track_remove_view,
    build_track_update_view,
    build_tracking_success_view,
)

_log = logging.getLogger(__name__)

_LIST_PAGE_SIZE = 25
_LIST_FETCH_LIMIT = 500

_FRIENDLY_ERRORS: dict[str, str] = {
    "website_disabled": "That website is currently disabled on the crawler.",
    "website_blocked": "The crawler was blocked by that website. Try again later.",
    "tracking_seed_failed": "Tracking failed: the crawler couldn't fetch series data.",
    "invalid_request": "Invalid series URL or website key.",
    "page_blocked": "The crawler was blocked while trying to reach that page.",
}


class TrackingCog(commands.Cog, name="Tracking"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._tracked = TrackedStore(bot.db)  # type: ignore[attr-defined]
        self._guild_settings = GuildSettingsStore(bot.db)  # type: ignore[attr-defined]

    track = app_commands.Group(
        name="track",
        description="(Mods) Start tracking a manga for the server to get notifications.",
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )

    # -- /track new ---------------------------------------------------------

    @track.command(
        name="new",
        description="Start tracking a manga for the server to get notifications.",
    )
    @app_commands.describe(
        manga_url="The URL of the manga you want to track.",
        ping_role="The role to ping when a notification is sent.",
    )
    @app_commands.autocomplete(manga_url=autocomplete.track_new_url_or_search)
    @has_premium(dm_only=True)
    async def track_new(
        self,
        interaction: discord.Interaction,
        manga_url: str,
        ping_role: discord.Role | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        parsed = await _resolve_track_input(self.bot, manga_url)
        if parsed is None:
            await interaction.followup.send(
                view=build_error_view(
                    "Couldn't resolve that URL.\n"
                    "Use the autocomplete to search by title, or paste a full series "
                    "URL from a supported website.",
                    bot=self.bot,
                ),
                ephemeral=True,
            )
            return

        website_key, series_url = parsed
        guild_id = interaction.guild_id  # type: ignore[union-attr]

        if interaction.guild is not None:
            channel = await self._resolve_notifications_channel(interaction.guild, website_key)
            if channel is None:
                await interaction.followup.send(
                    view=build_error_view(
                        "**No updates channel configured for this server.**\n\n"
                        "Set one with `/settings` → Notifications channel "
                        "(or per-scanlator override) before tracking series. "
                        "Without a channel I have nowhere to post chapter updates.",
                        bot=self.bot,
                    ),
                    ephemeral=True,
                )
                return
        else:
            channel = None

        request_id = uuid.uuid4().hex
        progress = ProgressLayoutState(
            command_name="/track new", request_id=request_id, bot=self.bot
        )
        progress.add("Sent request to crawler.")
        await interaction.edit_original_response(view=progress.to_view())
        terminal_started = False
        progress_edit_lock = asyncio.Lock()

        async def on_progress(event: object) -> None:
            async with progress_edit_lock:
                if terminal_started:
                    return
                message, severity = progress_event_message(event)
                progress.add(message, severity=severity)
                await interaction.edit_original_response(view=progress.to_view())

        async def try_terminal_edit(view: discord.ui.LayoutView) -> bool:
            async with progress_edit_lock:
                try:
                    await interaction.edit_original_response(view=view)
                except Exception:
                    _log.exception("track_new terminal response edit failed")
                    return False
            return True

        try:
            data = await self.bot.crawler.request_with_progress(  # type: ignore[attr-defined]
                "track_series",
                request_id=request_id,
                on_progress=on_progress,
                website_key=website_key,
                series_url=series_url,
            )
        except CrawlerError as exc:
            friendly = _FRIENDLY_ERRORS.get(exc.code, f"[{exc.code}] {exc.message}")
            terminal_started = True
            progress.add(friendly, severity="error")
            await try_terminal_edit(build_error_view(friendly, source=SOURCE_CRAWLER, bot=self.bot))
            return
        except (RequestTimeout, Disconnected) as exc:
            terminal_started = True
            progress.add(str(exc), severity="error")
            await try_terminal_edit(build_error_view(str(exc), source=SOURCE_CRAWLER, bot=self.bot))
            return

        try:
            website_key = data["website_key"]
            url_name = data["url_name"]
            series_url = data["series_url"]
            series_data: dict = data.get("series") or {}
            title: str = series_data.get("title") or url_name
            status: str | None = series_data.get("status")
            cover_url: str | None = series_data.get("cover_url")

            latest_chapters = series_data.get("latest_chapters") or []
            latest_text: str | None = None
            latest_url: str | None = None
            if latest_chapters:
                first = latest_chapters[0] or {}
                latest_text = first.get("name") or first.get("text")
                latest_url = first.get("url")

            await self._tracked.upsert_series(
                website_key,
                url_name,
                series_url,
                title,
                cover_url=cover_url,
                status=status,
                last_chapter_text=latest_text,
                last_chapter_url=latest_url,
            )
            await self._tracked.add_to_guild(
                guild_id, website_key, url_name, ping_role.id if ping_role else None
            )

            immediate_check_failed = False
            try:
                request = getattr(self.bot.crawler, "request", None)  # type: ignore[attr-defined]
                if request is not None:
                    await request(
                        "check_series",
                        website_key=website_key,
                        url_name=url_name,
                    )
            except CrawlerError, RequestTimeout, Disconnected:
                immediate_check_failed = True
                _log.exception("immediate check_series failed for %s:%s", website_key, url_name)

            warning = None
            if immediate_check_failed:
                warning = (
                    "Tracking was saved, but the immediate update check failed. "
                    "The scheduler will retry later."
                )
            view = build_tracking_success_view(
                title=title,
                series_url=series_url,
                ping_role=ping_role,
                notif_channel=channel,
                cover_url=cover_url,
                is_dm=interaction.guild_id is None,
                warning=warning,
                bot=self.bot,
            )
            terminal_started = True
            await try_terminal_edit(view)
        except Exception as exc:
            _log.exception("track_new post-crawler success path failed")
            terminal_started = True
            message = f"Failed to finish tracking setup after crawler completed: {exc}"
            progress.add(message, severity="error")
            await try_terminal_edit(build_error_view(message, bot=self.bot))

    async def _resolve_notifications_channel(
        self, guild: discord.Guild, website_key: str
    ) -> discord.abc.GuildChannel | discord.Thread | None:
        """Per-scanlator override → guild-wide notifications channel → None."""
        try:
            scanlator_rows = await self._guild_settings.list_scanlator_channels(guild.id)
        except Exception:
            scanlator_rows = []
        for row in scanlator_rows:
            if row.get("website_key") == website_key and row.get("channel_id"):
                ch = guild.get_channel(int(row["channel_id"]))
                if ch is not None:
                    return ch
        gs = await self._guild_settings.get(guild.id)
        if gs and gs.notifications_channel_id:
            ch = guild.get_channel(int(gs.notifications_channel_id))
            if ch is not None:
                return ch
        return None

    # -- /track update ------------------------------------------------------

    @track.command(
        name="update",
        description="Update a tracked manga for the server to get notifications.",
    )
    @app_commands.describe(
        manga_id="The name of the manga.",
        role="The new role to ping.",
    )
    @app_commands.autocomplete(manga_id=autocomplete.tracked_manga_in_guild)
    @app_commands.rename(manga_id="manga")
    @has_premium(dm_only=True)
    async def track_update(
        self,
        interaction: discord.Interaction,
        manga_id: str,
        role: discord.Role | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        parsed = _parse_manga_id(manga_id)
        if parsed is None:
            await interaction.followup.send(
                view=build_error_view(
                    "Couldn't parse that manga ID. Use the autocomplete.", bot=self.bot
                ),
                ephemeral=True,
            )
            return

        website_key, url_name = parsed
        guild_id = interaction.guild_id  # type: ignore[union-attr]

        if role is not None and interaction.guild is not None:
            me = interaction.guild.me
            if role.is_bot_managed():
                await interaction.followup.send(
                    view=build_role_managed_view(bot=self.bot), ephemeral=True
                )
                return
            if me is not None and role >= me.top_role:
                await interaction.followup.send(
                    view=build_role_hierarchy_view(bot=self.bot), ephemeral=True
                )
                return

        await self._tracked.update_ping_role(
            guild_id, website_key, url_name, role.id if role else None
        )

        series = await self._tracked.find(website_key, url_name)
        title = series.title if series else f"{website_key}:{url_name}"
        cover_url = series.cover_url if series else None
        role_text = role.mention if role else "nothing"

        view = build_track_update_view(
            title=title,
            role_text=role_text,
            cover_url=cover_url,
            bot=self.bot,
        )
        await interaction.followup.send(view=view, ephemeral=True)

    # -- /track remove ------------------------------------------------------

    @track.command(name="remove", description="Stop tracking a manga on this server.")
    @app_commands.describe(
        manga_id="The name of the manga.",
        delete_role="Whether to delete the role associated with the manhwa.",
    )
    @app_commands.autocomplete(manga_id=autocomplete.tracked_manga_in_guild)
    @app_commands.rename(manga_id="manga")
    @has_premium(dm_only=True)
    async def track_remove(
        self,
        interaction: discord.Interaction,
        manga_id: str,
        delete_role: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        parsed = _parse_manga_id(manga_id)
        if parsed is None:
            await interaction.followup.send(
                view=build_error_view(
                    "Couldn't parse that manga ID. Use the autocomplete.", bot=self.bot
                ),
                ephemeral=True,
            )
            return

        website_key, url_name = parsed
        guild_id = interaction.guild_id  # type: ignore[union-attr]

        # Capture metadata before deletion.
        series = await self._tracked.find(website_key, url_name)
        title = series.title if series else f"{website_key}:{url_name}"

        guild_rows = await self._tracked.list_guilds_tracking(website_key, url_name)
        this_row = next((r for r in guild_rows if r.guild_id == guild_id), None)
        captured_role_id = this_row.ping_role_id if this_row else None

        was_last, _remaining = await self._tracked.remove_from_guild(
            guild_id, website_key, url_name
        )

        crawler_untracked = False
        if was_last:
            try:
                await self.bot.crawler.request_with_progress(  # type: ignore[attr-defined]
                    "untrack_series",
                    request_id=None,
                    on_progress=None,
                    website_key=website_key,
                    url_name=url_name,
                )
                crawler_untracked = True
            except CrawlerError, RequestTimeout, Disconnected:
                _log.exception(
                    "untrack_series call failed for %s:%s — series removed from bot DB anyway",
                    website_key,
                    url_name,
                )
            await self._tracked.delete_series(website_key, url_name)

        role_deleted = False
        deleted_role_name: str | None = None
        if delete_role and captured_role_id:
            role_obj = (
                interaction.guild.get_role(captured_role_id)  # type: ignore[union-attr]
                if interaction.guild
                else None
            )
            if role_obj is None:
                try:
                    fetched = await interaction.guild.fetch_roles()  # type: ignore[union-attr]
                    role_obj = next((r for r in fetched if r.id == captured_role_id), None)
                except discord.HTTPException:
                    role_obj = None
            if role_obj is not None:
                deleted_role_name = role_obj.name
                try:
                    await role_obj.delete(reason=f"Deleted with /track remove for {title}")
                    role_deleted = True
                except discord.HTTPException:
                    _log.warning("failed to delete ping role %s for %s", captured_role_id, title)
                    deleted_role_name = None

        view = build_track_remove_view(
            title=title,
            series_url=series.series_url if series else None,
            deleted_role_name=deleted_role_name,
            crawler_warning=was_last and not crawler_untracked,
            role_warning=delete_role and not role_deleted and bool(captured_role_id),
            bot=self.bot,
        )
        await interaction.followup.send(view=view, ephemeral=True)

    # -- /track list --------------------------------------------------------

    @track.command(
        name="list",
        description="List all the manga that are being tracked in this server.",
    )
    @has_premium(dm_only=True)
    async def track_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild_id  # type: ignore[union-attr]
        rows = await self._tracked.list_for_guild(guild_id, limit=_LIST_FETCH_LIMIT)

        sorted_rows = sorted(rows, key=lambda r: r.title.lower())
        items = [
            {
                "title": r.title,
                "url": r.series_url,
                "website_key": r.website_key,
                "last_chapter": r.last_chapter_text,
                "last_chapter_url": r.last_chapter_url,
            }
            for r in sorted_rows
        ]
        pages = build_grouped_list_views(
            items,
            title=f"Tracked Manhwa ({len(items)})",
            bot=self.bot,
            empty_title="Nothing found",
            empty_description=(
                "There are no tracked manga in this server."
                if interaction.guild_id is not None
                else "You are not tracking any manga."
            ),
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


# -- module helpers ---------------------------------------------------------


def _parse_new_url(manga_url: str) -> tuple[str, str] | None:
    """Parse an autocomplete value for /track new.

    Accepts ``"website_key|https://..."`` (search result format).
    """
    if not manga_url:
        return None
    if "|" in manga_url and not manga_url.startswith("http"):
        parts = manga_url.split("|", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])
    return None


async def _resolve_track_input(bot: Any, manga_url: str) -> tuple[str, str] | None:
    """Return ``(website_key, series_url)`` for /track new input."""
    parsed = _parse_new_url(manga_url)
    if parsed is not None:
        return parsed
    if manga_url and manga_url.startswith("http"):
        wk = await detect_website_key(bot, manga_url)
        if wk:
            return (wk, manga_url)
    return None


def _parse_manga_id(manga_id: str) -> tuple[str, str] | None:
    """Parse ``"website_key:url_name"`` → ``(website_key, url_name)``, or None."""
    if ":" in manga_id and not manga_id.startswith("http"):
        parts = manga_id.split(":", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])
    return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrackingCog(bot))
