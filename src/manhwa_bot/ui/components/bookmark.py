"""Bookmark layouts: single-bookmark display, update-ack, and browser view."""

from __future__ import annotations

import asyncio
import difflib
import logging
from dataclasses import dataclass, replace
from typing import Any, Literal

import discord

from ...crawler.chapter import Chapter
from ...db.bookmarks import Bookmark, BookmarkStore
from ...db.guild_settings import GuildSettingsStore
from ...db.subscriptions import SubscriptionStore
from ...db.tracked import TrackedStore
from .. import emojis
from .base import (
    BaseLayoutView,
    chapter_markdown,
    folder_accent,
    footer_section,
    hero_cover_gallery,
    large_separator,
    safe_truncate,
    small_separator,
    status_emoji,
)
from .nsfw import should_spoiler

_log = logging.getLogger(__name__)

BOOKMARK_FOLDERS: tuple[str, ...] = (
    "Reading",
    "Subscribed",
    "Planned",
    "Finished",
    "Dropped",
)

_TEXT_PAGE_SIZE = 20
_BROWSER_TIMEOUT_SECONDS = 2 * 24 * 60 * 60
_PRELOAD_CHUNK_SIZE = 10
_PRELOAD_EDGE_THRESHOLD = 3
# Minimum SequenceMatcher ratio for the bookmark-search fuzzy fallback to accept
# a non-prefix match (query vs. the title's leading slice).
_SEARCH_SIMILARITY_THRESHOLD = 0.6
_FOLDER_DESCRIPTIONS: dict[str, str] = {
    "Reading": "Actively reading.",
    "Subscribed": "Marked from update notifications.",
    "Planned": "Saved for later.",
    "Finished": "Finished series.",
    "Dropped": "No longer reading.",
}


# ---------------------------------------------------------------------------
# Static factory: rich bookmark detail (used by /bookmark new success message)
# ---------------------------------------------------------------------------


def build_bookmark_detail_view(
    *,
    title: str,
    series_url: str,
    website_key: str,
    cover_url: str | None,
    scanlator_base_url: str | None,
    last_read_chapter: str,
    next_chapter: str | None,
    folder: str,
    available_chapters_label: str,
    chapter_count: int,
    status: str,
    is_completed: bool,
    bot: discord.Client | None = None,
    invoker_id: int | None = None,
    extra_action_row: discord.ui.ActionRow | None = None,
    is_nsfw: bool | None = None,
) -> discord.ui.LayoutView:
    """Hero `/bookmark new`/`view` single-card layout."""
    if next_chapter:
        next_text = next_chapter
    elif is_completed:
        next_text = f"`None — manhwa is {status.lower() or 'completed'}`"
    else:
        next_text = "`Wait for updates`"

    available = (
        f"{available_chapters_label} ({chapter_count})" if chapter_count else "`Wait for updates`"
    )

    scanlator_link = (
        f"[{website_key.title()}]({scanlator_base_url})"
        if scanlator_base_url
        else website_key.title()
    )
    header_block = f"## 🔖  [{title}]({series_url})" if series_url else f"## 🔖  {title}"
    details_block = (
        f"**Scanlator:** {scanlator_link} • **Status:** {status_emoji(status)} {status}\n"
        f"**Folder:** `{folder}`\n"
        f"**Last Read:** {last_read_chapter}\n"
        f"**Next Chapter:** {next_text}\n"
        f"**Available Chapters:** Up to {available}"
    )

    container = discord.ui.Container(accent_colour=None)
    gallery = hero_cover_gallery(cover_url, spoiler=should_spoiler(is_nsfw))
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(header_block))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(details_block))
    container.add_item(small_separator())
    container.add_item(footer_section(bot))
    if extra_action_row is not None:
        container.add_item(small_separator())
        container.add_item(extra_action_row)

    view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
    view.add_item(container)
    return view


def build_bookmark_update_success_view(
    *,
    moved_folder: str | None,
    new_chapter_label: str | None,
    auto_subscribed_title: str | None,
    should_track: bool,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Acknowledgement view for `/bookmark update`."""
    lines: list[str] = ["Bookmark updated successfully!"]
    if moved_folder:
        lines.append(f"\n• Moved bookmark to **{moved_folder}**")
    if new_chapter_label:
        lines.append(f"\n• Updated last read chapter to **{new_chapter_label}**")
    if auto_subscribed_title:
        lines.append(f"\n\n📨  You have been subscribed to updates for **{auto_subscribed_title}**")
    elif should_track:
        lines.append(
            "\n\n-# *You should consider tracking and subscribing to this manga to get updates.*"
        )
    body = "".join(lines)

    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {emojis.CHECK}  Bookmark updated"),
        small_separator(),
        discord.ui.TextDisplay(body),
        small_separator(),
        footer_section(bot),
        accent_colour=None,
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


# ---------------------------------------------------------------------------
# Tracking-state helper
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TrackingStatus:
    """Computed tracking + subscription state for the current user/bookmark."""

    is_tracked: bool
    mutual_guild: discord.Guild | None
    display_guild_name: str | None
    display_guild_id: int | None
    update_channel_id: int | None
    update_channel_name: str | None
    channel_visible: bool
    subscribed: bool


@dataclass(frozen=True)
class _TrackButtonState:
    """Whether the current user can add tracking for the current bookmark."""

    show: bool
    enabled: bool
    reason: str | None = None


# ---------------------------------------------------------------------------
# BookmarkBrowserView
# ---------------------------------------------------------------------------


class _SetLastReadModal(discord.ui.Modal, title="Set last read chapter"):
    chapter_index: discord.ui.TextInput = discord.ui.TextInput(
        label="Chapter index (0-based)",
        placeholder="e.g. 42",
        required=True,
        max_length=10,
    )

    def __init__(self, view: BookmarkBrowserView, current_bm: Bookmark) -> None:
        super().__init__()
        self._view = view
        self._bm = current_bm
        if current_bm.last_read_index is not None:
            self.chapter_index.default = str(current_bm.last_read_index)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = (self.chapter_index.value or "").strip()
        try:
            idx = int(raw)
        except ValueError:
            await interaction.response.send_message(
                "Chapter index must be an integer.", ephemeral=True
            )
            return
        if idx < 0:
            await interaction.response.send_message("Chapter index must be ≥ 0.", ephemeral=True)
            return

        try:
            chapters = await self._view._get_chapters(self._bm)
        except Exception as exc:
            await interaction.response.send_message(
                f"Couldn't fetch chapters: {exc}", ephemeral=True
            )
            return

        if not chapters or idx >= len(chapters):
            await interaction.response.send_message(
                f"Chapter index out of range (0 - {max(0, len(chapters) - 1)}).",
                ephemeral=True,
            )
            return

        ch = chapters[idx]
        await self._view._store.update_last_read(
            self._bm.user_id,
            self._bm.website_key,
            self._bm.url_name,
            chapter_text=ch.name,
            chapter_index=idx,
        )
        await self._view._refresh_current(interaction, chapter_text=ch.name, chapter_index=idx)


def resolve_last_read_nav(
    last_read_index: int | None, chapter_count: int
) -> tuple[int | None, bool, bool]:
    """Resolve the last-read row's nav state: ``(clamped_index, can_back, can_forward)``.

    ``last_read_index`` is a 0-based position into the chapter list, but a value
    carried over from a context with a different (or not-yet-loaded) chapter list
    can fall outside the current range — which otherwise flips the ±1/±5 enabled
    states and can index out of bounds on click. Clamp it into ``[0, count-1]`` and
    derive the button states from the clamped value.

    With no chapters there is nothing to navigate. With nothing read yet
    (``None``) the reader can only move forward into the list.
    """
    if chapter_count <= 0:
        return None, False, False
    if last_read_index is None:
        return None, False, True
    idx = max(0, min(last_read_index, chapter_count - 1))
    return idx, idx > 0, idx < chapter_count - 1


class BookmarkBrowserView(BaseLayoutView):
    """V2 bookmark browser. Visual + text modes, folder select, tracking, subscribe."""

    def __init__(
        self,
        bookmarks: list[Bookmark],
        *,
        store: BookmarkStore,
        tracked: TrackedStore,
        subscriptions: SubscriptionStore,
        guild_settings: GuildSettingsStore,
        crawler: Any,
        invoker_id: int,
        guild_id: int | None = None,
        current_folder: str | None = None,
        index: int = 0,
        timeout: float = _BROWSER_TIMEOUT_SECONDS,
        bot: discord.Client | None = None,
    ) -> None:
        super().__init__(invoker_id=invoker_id, timeout=timeout)
        self._all = list(bookmarks)
        self._store = store
        self._tracked = tracked
        self._subs = subscriptions
        self._guild_settings = guild_settings
        self._crawler = crawler
        self._guild_id = guild_id
        self._current_folder = current_folder
        self._mode: Literal["visual", "text"] = "visual"
        self._bot = bot
        self._meta: dict[tuple[str, str], dict[str, Any]] = {}
        self._series_data_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._chapter_cache: dict[tuple[str, str], list[Chapter]] = {}
        self._site_meta_cache: dict[str, dict[str, Any]] = {}
        self._tracking_cache: dict[tuple[str, str], _TrackingStatus] = {}
        self._track_button_cache: dict[tuple[str, str], _TrackButtonState] = {}
        self._preload_task: asyncio.Task[None] | None = None
        self._filtered = self._apply_folder_filter()
        self._index = max(0, min(index, max(0, len(self._filtered) - 1)))
        self._preload_start = 0
        self._preload_end = 0
        self._reset_preload_window()
        self._pending_delete_key: tuple[str, str] | None = None

    # ---- public ---------------------------------------------------------

    async def initial_render(self) -> None:
        """Populate the view with its first render (must be awaited before send)."""
        await self._rebuild()
        self._schedule_preload()

    async def on_timeout(self) -> None:
        if self._preload_task is not None and not self._preload_task.done():
            self._preload_task.cancel()
        await super().on_timeout()

    # ---- helpers --------------------------------------------------------

    def _custom_id(self, name: str) -> str:
        return f"bookmark:{self.id}:{name}"

    async def _defer_update(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()

    async def _rebuild_and_edit(self, interaction: discord.Interaction) -> None:
        await self._defer_update(interaction)
        await self._rebuild()
        await interaction.edit_original_response(view=self)
        self._schedule_preload()

    async def _send_ephemeral(self, interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    def _apply_folder_filter(self) -> list[Bookmark]:
        if self._current_folder is None:
            return list(self._all)
        return [b for b in self._all if b.folder == self._current_folder]

    def _bookmark_key(self, bm: Bookmark) -> tuple[str, str]:
        return (bm.website_key, bm.url_name)

    async def _meta_for(self, bm: Bookmark) -> dict[str, Any]:
        key = self._bookmark_key(bm)
        if key in self._meta:
            return self._meta[key]
        title = bm.url_name
        series_url = ""
        cover_url: str | None = None
        status: str | None = None
        is_nsfw: bool | None = None
        series_data = await self._series_data_for(bm)
        if series_data:
            title = str(series_data.get("title") or title)
            series_url = str(series_data.get("url") or series_data.get("series_url") or "")
            cover_url = series_data.get("cover_url")
            status = series_data.get("status")
            is_nsfw = series_data.get("is_nsfw")
        try:
            tracked = await self._tracked.find(bm.website_key, bm.url_name)
        except Exception:
            tracked = None
        if tracked is not None:
            title = title if title != bm.url_name else tracked.title
            series_url = series_url or tracked.series_url
            cover_url = cover_url or tracked.cover_url
            status = status or tracked.status
            if is_nsfw is None:
                is_nsfw = tracked.is_nsfw
        meta = {
            "title": title,
            "series_url": series_url,
            "cover_url": cover_url,
            "status": status or "Unknown",
            "is_nsfw": is_nsfw,
        }
        self._meta[key] = meta
        return meta

    async def _series_data_for(self, bm: Bookmark) -> dict[str, Any]:
        key = self._bookmark_key(bm)
        if key in self._series_data_cache:
            return self._series_data_cache[key]
        data: dict[str, Any] = {}
        try:
            raw = await self._crawler.request(
                "series_data",
                website_key=bm.website_key,
                url_name=bm.url_name,
                allow_live=False,
            )
            if isinstance(raw, dict):
                data = raw
                website = raw.get("website")
                if isinstance(website, dict):
                    self._site_meta_cache[bm.website_key] = dict(website)
        except Exception:
            _log.debug("series_data cache lookup failed for %s:%s", bm.website_key, bm.url_name)
        self._series_data_cache[key] = data
        return data

    async def _site_meta_for(self, website_key: str) -> dict[str, Any]:
        if website_key in self._site_meta_cache:
            return self._site_meta_cache[website_key]
        meta: dict[str, Any] = {"key": website_key, "name": website_key.title()}
        self._site_meta_cache[website_key] = meta
        return meta

    async def _get_chapters(self, bm: Bookmark) -> list[Chapter]:
        key = self._bookmark_key(bm)
        if key in self._chapter_cache:
            return self._chapter_cache[key]
        data = await self._series_data_for(bm)
        chapters = Chapter.list_from_payload(data) if data else []
        self._chapter_cache[key] = chapters
        return chapters

    async def _tracking_status_for(self, bm: Bookmark) -> _TrackingStatus:
        key = self._bookmark_key(bm)
        if key in self._tracking_cache:
            return self._tracking_cache[key]

        try:
            rows = await self._tracked.list_guilds_tracking(bm.website_key, bm.url_name)
        except Exception:
            rows = []
        if not rows:
            status = _TrackingStatus(
                is_tracked=False,
                mutual_guild=None,
                display_guild_name=None,
                display_guild_id=None,
                update_channel_id=None,
                update_channel_name=None,
                channel_visible=False,
                subscribed=False,
            )
            self._tracking_cache[key] = status
            return status

        mutual_guild: discord.Guild | None = None
        chosen_row = rows[0]
        if self._bot is not None:
            for row in rows:
                guild = self._bot.get_guild(int(row.guild_id))
                if guild is None:
                    continue
                member = guild.get_member(int(self._invoker_id or 0))
                if member is not None:
                    mutual_guild = guild
                    chosen_row = row
                    break

        # Always try to resolve channel info for the chosen row so we can
        # surface "tracked in #X (Server)" even when the user isn't in the
        # guild or can't see the channel.
        display_guild_id = int(chosen_row.guild_id)
        display_guild_name: str | None = None
        if self._bot is not None:
            display_guild = mutual_guild or self._bot.get_guild(display_guild_id)
            if display_guild is not None:
                display_guild_name = display_guild.name

        channel_id = await self._resolve_channel_id(display_guild_id, bm.website_key)
        channel_name: str | None = None
        channel_visible = False
        if channel_id is not None and self._bot is not None:
            channel = self._bot.get_channel(int(channel_id))
            if isinstance(channel, discord.TextChannel | discord.Thread):
                channel_name = channel.name
                if mutual_guild is not None:
                    member = mutual_guild.get_member(int(self._invoker_id or 0))
                    if member is not None:
                        try:
                            channel_visible = channel.permissions_for(member).read_messages
                        except Exception:
                            channel_visible = False

        subscribed = False
        if mutual_guild is not None:
            try:
                subscribed = await self._subs.is_subscribed(
                    int(self._invoker_id or 0),
                    int(mutual_guild.id),
                    bm.website_key,
                    bm.url_name,
                )
            except Exception:
                subscribed = False

        status = _TrackingStatus(
            is_tracked=True,
            mutual_guild=mutual_guild,
            display_guild_name=display_guild_name,
            display_guild_id=display_guild_id,
            update_channel_id=channel_id,
            update_channel_name=channel_name,
            channel_visible=channel_visible,
            subscribed=subscribed,
        )
        self._tracking_cache[key] = status
        return status

    async def _track_button_state(
        self, bm: Bookmark, ts: _TrackingStatus | None
    ) -> _TrackButtonState:
        """Show Track when the user has no visible mutual tracked server."""
        key = self._bookmark_key(bm)
        if key in self._track_button_cache:
            return self._track_button_cache[key]

        if ts is not None and ts.mutual_guild is not None and ts.channel_visible:
            state = _TrackButtonState(show=False, enabled=False)
            self._track_button_cache[key] = state
            return state

        guild = self._current_guild()
        if guild is None:
            state = _TrackButtonState(
                show=True,
                enabled=False,
                reason="Run this from the server where you want to track the series.",
            )
            self._track_button_cache[key] = state
            return state

        member = guild.get_member(int(self._invoker_id or 0))
        if member is None:
            state = _TrackButtonState(
                show=True,
                enabled=False,
                reason="You need to be in this server to track the series.",
            )
            self._track_button_cache[key] = state
            return state

        channel_id = await self._resolve_channel_id(int(guild.id), bm.website_key)
        if channel_id is None:
            state = _TrackButtonState(
                show=True,
                enabled=False,
                reason="Configure an updates channel before tracking this series.",
            )
            self._track_button_cache[key] = state
            return state
        channel = self._channel_for(guild, channel_id)
        if channel is None:
            state = _TrackButtonState(
                show=True,
                enabled=False,
                reason="The configured updates channel could not be found.",
            )
            self._track_button_cache[key] = state
            return state
        try:
            can_see_channel = bool(channel.permissions_for(member).read_messages)
        except Exception:
            can_see_channel = False
        if not can_see_channel:
            state = _TrackButtonState(
                show=True,
                enabled=False,
                reason="You need to be able to see the updates channel to track this series.",
            )
            self._track_button_cache[key] = state
            return state

        if await self._can_manage_tracking(int(guild.id), member):
            state = _TrackButtonState(show=True, enabled=True)
            self._track_button_cache[key] = state
            return state
        state = _TrackButtonState(
            show=True,
            enabled=False,
            reason=(
                "You need Manage Roles, Manage Server, or the configured bot manager role "
                "to track this series."
            ),
        )
        self._track_button_cache[key] = state
        return state

    def _invalidate_status_cache(self, bm: Bookmark) -> None:
        key = self._bookmark_key(bm)
        self._tracking_cache.pop(key, None)
        self._track_button_cache.pop(key, None)

    def _delete_confirmation_active(self) -> bool:
        return bool(
            self._filtered
            and self._pending_delete_key == self._bookmark_key(self._filtered[self._index])
        )

    def _schedule_preload(self) -> None:
        if not self._filtered:
            return
        if self._preload_task is not None and not self._preload_task.done():
            self._preload_task.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._preload_task = loop.create_task(
            self._preload_visible_cache(),
            name=f"bookmark-preload-{self.id}",
        )
        self._preload_task.add_done_callback(self._consume_preload_result)

    def _consume_preload_result(self, task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            _log.debug("bookmark preload task failed", exc_info=True)

    def _preload_order(self) -> list[Bookmark]:
        if not self._filtered:
            return []

        self._ensure_preload_window()
        indices = range(self._preload_start, self._preload_end)
        return [
            self._filtered[i]
            for i in sorted(indices, key=lambda value: (abs(value - self._index), value))
        ]

    def _preload_window_for_index(self) -> tuple[int, int]:
        total = len(self._filtered)
        if total <= 0:
            return 0, 0
        size = min(_PRELOAD_CHUNK_SIZE, total)
        start = self._index - (size // 2)
        start = max(0, min(start, total - size))
        return start, start + size

    def _reset_preload_window(self) -> None:
        self._preload_start, self._preload_end = self._preload_window_for_index()

    def _ensure_preload_window(self) -> None:
        total = len(self._filtered)
        if total <= 0:
            self._preload_start = 0
            self._preload_end = 0
            return
        if self._index < self._preload_start or self._index >= self._preload_end:
            self._reset_preload_window()
            return
        if self._index - self._preload_start <= _PRELOAD_EDGE_THRESHOLD:
            self._preload_start = max(0, self._preload_start - _PRELOAD_CHUNK_SIZE)
        if (self._preload_end - 1) - self._index <= _PRELOAD_EDGE_THRESHOLD:
            self._preload_end = min(total, self._preload_end + _PRELOAD_CHUNK_SIZE)

    async def _preload_visible_cache(self) -> None:
        ordered = self._preload_order()
        for bm in ordered[:3]:
            await self._warm_bookmark(bm)

        if len(ordered) <= 3:
            return

        semaphore = asyncio.Semaphore(3)

        async def warm_with_limit(bm: Bookmark) -> None:
            async with semaphore:
                await self._warm_bookmark(bm)

        await asyncio.gather(
            *(warm_with_limit(bm) for bm in ordered[3:]),
            return_exceptions=True,
        )

    async def _warm_bookmark(self, bm: Bookmark) -> None:
        try:
            await self._meta_for(bm)
            site_meta_result, chapters_result, tracking_result = await asyncio.gather(
                self._site_meta_for(bm.website_key),
                self._get_chapters(bm),
                self._tracking_status_for(bm),
                return_exceptions=True,
            )
            _ = site_meta_result, chapters_result
            if isinstance(tracking_result, _TrackingStatus):
                ts = tracking_result
            else:
                ts = await self._tracking_status_for(bm)
            await self._track_button_state(bm, ts)
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.debug(
                "bookmark preload failed for %s:%s",
                bm.website_key,
                bm.url_name,
                exc_info=True,
            )

    def _current_guild(self) -> discord.Guild | None:
        if self._guild_id is None or self._bot is None:
            return None
        try:
            return self._bot.get_guild(int(self._guild_id))
        except Exception:
            return None

    def _channel_for(
        self, guild: discord.Guild, channel_id: int
    ) -> discord.abc.GuildChannel | discord.Thread | None:
        channel = None
        try:
            channel = guild.get_channel(int(channel_id))
        except Exception:
            channel = None
        if channel is None and self._bot is not None:
            try:
                channel = self._bot.get_channel(int(channel_id))
            except Exception:
                channel = None
        return channel

    async def _can_manage_tracking(self, guild_id: int, member: discord.Member) -> bool:
        perms = getattr(member, "guild_permissions", None)
        if bool(getattr(perms, "manage_roles", False)) or bool(
            getattr(perms, "manage_guild", False)
        ):
            return True
        try:
            settings = await self._guild_settings.get(guild_id)
        except Exception:
            settings = None
        manager_role_id = getattr(settings, "bot_manager_role_id", None)
        return bool(
            manager_role_id
            and any(getattr(role, "id", None) == manager_role_id for role in member.roles)
        )

    async def _resolve_channel_id(self, guild_id: int, website_key: str) -> int | None:
        try:
            scanlator_rows = await self._guild_settings.list_scanlator_channels(guild_id)
            for entry in scanlator_rows:
                if str(entry.get("website_key")) == website_key:
                    cid = entry.get("channel_id")
                    if cid is not None:
                        return int(cid)
            settings = await self._guild_settings.get(guild_id)
            if settings is not None and settings.notifications_channel_id is not None:
                return int(settings.notifications_channel_id)
        except Exception:
            return None
        return None

    # ---- rendering ------------------------------------------------------

    def _tracking_lines(self, ts: _TrackingStatus) -> list[str]:
        """Render the Tracking + Subscribed text rows. The channel is always mentioned."""
        if not ts.is_tracked:
            return ["**Tracking:** Not tracked — ask a server admin to `/track new` this series."]

        if ts.update_channel_id is not None:
            channel_part = f"<#{ts.update_channel_id}>"
        elif ts.update_channel_name:
            channel_part = f"#{ts.update_channel_name}"
        else:
            channel_part = "*(no channel configured)*"
        guild_part = f"(**{ts.display_guild_name}**)" if ts.display_guild_name else ""
        location = f"{channel_part} {guild_part}".strip()

        lines: list[str] = []
        if ts.mutual_guild is None:
            lines.append(
                f"**Tracking:** {emojis.WARNING} Tracked in {location} — "
                "you aren't in a mutual server, so you won't receive notifications."
            )
        elif not ts.channel_visible:
            lines.append(
                f"**Tracking:** {emojis.WARNING} Tracked in {location} — "
                "you can't see this channel, so you won't receive notifications."
            )
        else:
            lines.append(f"**Tracking:** Tracked in {location}")
            lines.append(f"**Subscribed:** {'Yes' if ts.subscribed else 'No'}")
        return lines

    async def _visual_container(self, bm: Bookmark) -> tuple[discord.ui.Container, list[Chapter]]:
        meta = await self._meta_for(bm)
        title = meta["title"]
        series_url = meta["series_url"]
        cover_url = meta["cover_url"]
        status = meta.get("status") or "Unknown"

        site_meta = await self._site_meta_for(bm.website_key)
        site_label = site_meta.get("name") or bm.website_key.title()
        site_base_url = site_meta.get("base_url")
        site_link = f"[{site_label}]({site_base_url})" if site_base_url else f"**{site_label}**"

        chapters = await self._get_chapters(bm)
        ts = await self._tracking_status_for(bm)

        header_block = f"## 🔖  [{title}]({series_url})" if series_url else f"## 🔖  {title}"

        # Website + Status share a single line.
        details_lines = [
            f"**Website:** {site_link} • **Status:** {status_emoji(status)} {status}",
            *self._tracking_lines(ts),
        ]
        details_block = "\n".join(details_lines)

        container = discord.ui.Container(accent_colour=None)
        gallery = hero_cover_gallery(cover_url, spoiler=should_spoiler(meta.get("is_nsfw")))
        if gallery is not None:
            container.add_item(gallery)
        container.add_item(discord.ui.TextDisplay(header_block))
        container.add_item(small_separator())
        container.add_item(discord.ui.TextDisplay(details_block))

        # Folder select for THIS bookmark moves it across folders.
        container.add_item(self._build_bookmark_folder_row(bm))

        container.add_item(small_separator())

        # Last-read row: [-5] [-1] + [link button to current chapter] + [+1] [+5].
        container.add_item(discord.ui.TextDisplay("**Set last read chapter:**"))
        container.add_item(self._build_last_read_row(bm, chapters))
        return container, chapters

    def _build_bookmark_folder_row(self, bm: Bookmark) -> discord.ui.ActionRow:
        """Select that moves the current bookmark between folders."""
        select = discord.ui.Select(
            placeholder=f"Move bookmark: {bm.folder}",
            custom_id=self._custom_id("move-folder"),
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=f,
                    value=f,
                    default=bm.folder == f,
                    description=f"Move this bookmark to {f}.",
                )
                for f in BOOKMARK_FOLDERS
            ],
        )
        select.callback = self._on_folder_change  # type: ignore[assignment]
        row = discord.ui.ActionRow()
        row.add_item(select)
        return row

    def _build_folder_filter_row(self) -> discord.ui.ActionRow:
        """Select that filters which folder of bookmarks we are currently viewing."""
        current = self._current_folder or "All folders"
        select = discord.ui.Select(
            placeholder=f"Browsing folder: {current}",
            custom_id=self._custom_id("browse-folder"),
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="All folders",
                    value="__all__",
                    default=self._current_folder is None,
                    description="Show bookmarks from every folder.",
                )
            ]
            + [
                discord.SelectOption(
                    label=f,
                    value=f,
                    default=self._current_folder == f,
                    description=f"Show bookmarks in {f}. {_FOLDER_DESCRIPTIONS[f]}",
                )
                for f in BOOKMARK_FOLDERS
            ],
        )
        select.callback = self._on_filter_change  # type: ignore[assignment]
        row = discord.ui.ActionRow()
        row.add_item(select)
        return row

    def _build_last_read_row(self, bm: Bookmark, chapters: list[Chapter]) -> discord.ui.ActionRow:
        """[-5] [-1] [Chapter X (link)] [+1] [+5]."""
        row = discord.ui.ActionRow()

        current_idx, can_go_back, can_go_forward = resolve_last_read_nav(
            bm.last_read_index, len(chapters)
        )
        last_ch: Chapter | None = chapters[current_idx] if current_idx is not None else None

        # Backward steps.
        for delta, label in ((-5, "-5"), (-1, "-1")):
            back_btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                disabled=not can_go_back,
                custom_id=self._custom_id(f"mark-delta-{delta}"),
            )
            back_btn.callback = self._make_mark_delta_callback(delta)  # type: ignore[assignment]
            row.add_item(back_btn)

        # Current chapter (link when available).
        if last_ch is not None and last_ch.url:
            label = safe_truncate(last_ch.name or "Last chapter", 60)
            row.add_item(
                discord.ui.Button(
                    label=label,
                    style=discord.ButtonStyle.link,
                    url=last_ch.url,
                )
            )
        else:
            # No URL → render a disabled grey button with the chapter text so
            # the visual placement stays consistent.
            label = safe_truncate(
                (last_ch.name if last_ch else bm.last_read_chapter) or "—",
                60,
            )
            row.add_item(
                discord.ui.Button(
                    label=label,
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                )
            )

        # Forward steps.
        for delta, label in ((1, "+1"), (5, "+5")):
            fwd_btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                disabled=not can_go_forward,
                custom_id=self._custom_id(f"mark-delta-{delta}"),
            )
            fwd_btn.callback = self._make_mark_delta_callback(delta)  # type: ignore[assignment]
            row.add_item(fwd_btn)
        return row

    def _build_pagination_row(self) -> discord.ui.ActionRow:
        total = max(1, len(self._filtered))
        if self._mode == "visual":
            page_x = self._index + 1
            page_y = total
        else:
            page_x = (self._index // _TEXT_PAGE_SIZE) + 1
            page_y = max(1, (total + _TEXT_PAGE_SIZE - 1) // _TEXT_PAGE_SIZE)

        is_first = page_x <= 1
        is_last = page_x >= page_y

        nav_row = discord.ui.ActionRow()
        for label, target in (("<<", "first"), ("<", "prev")):
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                disabled=is_first,
                custom_id=self._custom_id(f"nav-{target}"),
            )
            btn.callback = self._make_nav_callback(target)  # type: ignore[assignment]
            nav_row.add_item(btn)
        page_btn = discord.ui.Button(
            label=f"Page {page_x}/{page_y}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
        )
        nav_row.add_item(page_btn)
        for label, target in ((">", "next"), (">>", "last")):
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                disabled=is_last,
                custom_id=self._custom_id(f"nav-{target}"),
            )
            btn.callback = self._make_nav_callback(target)  # type: ignore[assignment]
            nav_row.add_item(btn)
        return nav_row

    def _build_text_container(self) -> discord.ui.Container:
        page = self._index // _TEXT_PAGE_SIZE
        total_pages = max(1, (len(self._filtered) + _TEXT_PAGE_SIZE - 1) // _TEXT_PAGE_SIZE)
        start = page * _TEXT_PAGE_SIZE
        chunk = self._filtered[start : start + _TEXT_PAGE_SIZE]
        lines: list[str] = []
        for offset, bm in enumerate(chunk):
            meta = self._meta.get((bm.website_key, bm.url_name)) or {}
            title = meta.get("title") or bm.url_name
            series_url = meta.get("series_url") or ""
            status = str(meta.get("status") or "Unknown")
            site = self._site_meta_cache.get(bm.website_key) or {}
            scanlator = str(site.get("name") or bm.website_key.title())
            chapters = self._chapter_cache.get((bm.website_key, bm.url_name)) or []
            last_md = _format_last_read(bm, chapters)
            title_link = f"[{title}]({series_url})" if series_url else f"**{title}**"
            folder_initial = (bm.folder or "?")[:1].upper()
            lines.append(
                f"`{start + offset + 1}. ({folder_initial})` [{scanlator}] {title_link}"
                f" · `{status}` · {last_md}"
            )
        body = "\n".join(lines) if lines else "No bookmarks in this folder."
        folder_label = self._current_folder or "All"

        container = discord.ui.Container(accent_colour=None)
        container.add_item(discord.ui.TextDisplay("## 🔖  Your bookmarks"))
        container.add_item(small_separator())
        container.add_item(discord.ui.TextDisplay(safe_truncate(body, 3700)))

        # Sort select (text-mode only) also inside the container.
        sort_row = discord.ui.ActionRow()
        sort_select = discord.ui.Select(
            placeholder="Sort by…",
            custom_id=self._custom_id("sort"),
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Last Updated", value="last_updated"),
                discord.SelectOption(label="Title", value="title"),
                discord.SelectOption(label="Scanlator", value="scanlator"),
            ],
        )
        sort_select.callback = self._on_sort_select  # type: ignore[assignment]
        sort_row.add_item(sort_select)
        container.add_item(sort_row)

        # Stash text-mode footer extras so _rebuild can place the footer at the
        # end of the container, right after the action/pagination rows.
        self._text_footer_extra = f"{folder_label} • Page {page + 1}/{total_pages}"
        return container

    async def _build_container(self) -> discord.ui.Container:
        if not self._filtered:
            label = self._current_folder or "All"
            return discord.ui.Container(
                discord.ui.TextDisplay("## 🔖  No bookmarks"),
                small_separator(),
                discord.ui.TextDisplay(f"No bookmarks in **{label}**."),
                large_separator(),
                footer_section(self._bot),
                accent_colour=None,
            )

        if self._mode == "visual":
            container, _ = await self._visual_container(self._filtered[self._index])
            return container

        # Text mode — prefetch meta for the visible chunk so lines have titles.
        page = self._index // _TEXT_PAGE_SIZE
        start = page * _TEXT_PAGE_SIZE
        for bm in self._filtered[start : start + _TEXT_PAGE_SIZE]:
            await self._meta_for(bm)
        return self._build_text_container()

    async def _rebuild(self) -> None:
        """Reconstruct all top-level children of this view."""
        self._text_footer_extra: str | None = None
        container = await self._build_container()

        ts: _TrackingStatus | None = None
        track_state: _TrackButtonState | None = None
        if self._filtered and self._mode == "visual":
            try:
                ts = await self._tracking_status_for(self._filtered[self._index])
            except Exception:
                ts = None
            try:
                track_state = await self._track_button_state(self._filtered[self._index], ts)
            except Exception:
                track_state = _TrackButtonState(show=True, enabled=False)

        # Per-bookmark action buttons + pagination live inside the container so
        # they share the visual frame.
        if self._filtered:
            container.add_item(small_separator())
            if self._delete_confirmation_active():
                container.add_item(
                    discord.ui.TextDisplay(
                        f"{emojis.WARNING} Delete this bookmark? This cannot be undone."
                    )
                )
                container.add_item(small_separator())
            container.add_item(self._build_action_row(ts, track_state))

        container.add_item(small_separator())
        container.add_item(self._build_pagination_row())

        container.add_item(small_separator())
        container.add_item(self._build_folder_filter_row())

        # Footer at the very bottom of the container.
        if self._filtered:
            if self._mode == "visual":
                footer_extra = f"Bookmark {self._index + 1}/{len(self._filtered)}"
            else:
                footer_extra = self._text_footer_extra
            container.add_item(small_separator())
            container.add_item(footer_section(self._bot, extra=footer_extra))

        self.clear_items()
        self.add_item(container)

    def _build_action_row(
        self,
        ts: _TrackingStatus | None,
        track_state: _TrackButtonState | None,
    ) -> discord.ui.ActionRow:
        row = discord.ui.ActionRow()
        toggle_btn = discord.ui.Button(
            label="Text mode" if self._mode == "visual" else "Visual mode",
            style=discord.ButtonStyle.secondary,
            custom_id=self._custom_id("toggle-mode"),
        )
        toggle_btn.callback = self._on_mode_toggle  # type: ignore[assignment]
        row.add_item(toggle_btn)
        # Skipped during delete confirmation: the row is already at Discord's
        # five-button cap there (toggle, confirm, cancel, track, subscribe).
        if not self._delete_confirmation_active():
            search_btn = discord.ui.Button(
                label="Search",
                emoji="🔎",
                style=discord.ButtonStyle.secondary,
                custom_id=self._custom_id("search"),
            )
            search_btn.callback = self._on_search  # type: ignore[assignment]
            row.add_item(search_btn)
        if self._mode == "visual":
            if self._delete_confirmation_active():
                confirm_btn = discord.ui.Button(
                    label="Confirm delete",
                    emoji="🗑️",
                    style=discord.ButtonStyle.danger,
                    custom_id=self._custom_id("delete-confirm"),
                )
                confirm_btn.callback = self._on_delete_confirm  # type: ignore[assignment]
                row.add_item(confirm_btn)

                cancel_btn = discord.ui.Button(
                    label="Cancel",
                    style=discord.ButtonStyle.secondary,
                    custom_id=self._custom_id("delete-cancel"),
                )
                cancel_btn.callback = self._on_delete_cancel  # type: ignore[assignment]
                row.add_item(cancel_btn)
            else:
                delete_btn = discord.ui.Button(
                    label="Delete bookmark",
                    emoji="🗑️",
                    style=discord.ButtonStyle.danger,
                    custom_id=self._custom_id("delete"),
                )
                delete_btn.callback = self._on_delete  # type: ignore[assignment]
                row.add_item(delete_btn)
            if track_state is not None and track_state.show:
                track_btn = discord.ui.Button(
                    label="Track",
                    style=(
                        discord.ButtonStyle.blurple
                        if track_state.enabled
                        else discord.ButtonStyle.secondary
                    ),
                    disabled=not track_state.enabled,
                    custom_id=self._custom_id("track"),
                )
                track_btn.callback = self._on_track  # type: ignore[assignment]
                row.add_item(track_btn)
            if ts is not None and ts.mutual_guild is not None and ts.channel_visible:
                sub_btn = discord.ui.Button(
                    label="Unsubscribe" if ts.subscribed else "Subscribe",
                    style=discord.ButtonStyle.secondary,
                    custom_id=self._custom_id("subscribe"),
                )
                sub_btn.callback = self._on_subscribe_toggle  # type: ignore[assignment]
                row.add_item(sub_btn)
        return row

    # ---- callbacks ------------------------------------------------------

    def _make_nav_callback(self, target: str):
        async def cb(interaction: discord.Interaction) -> None:
            if not self._filtered:
                await interaction.response.defer()
                return
            total_pages = max(1, (len(self._filtered) + _TEXT_PAGE_SIZE - 1) // _TEXT_PAGE_SIZE)
            last_text_index = max(0, (total_pages - 1) * _TEXT_PAGE_SIZE)
            if target == "first":
                self._index = 0
            elif target == "prev":
                step = 1 if self._mode == "visual" else _TEXT_PAGE_SIZE
                self._index = max(0, self._index - step)
            elif target == "next":
                step = 1 if self._mode == "visual" else _TEXT_PAGE_SIZE
                max_index = len(self._filtered) - 1 if self._mode == "visual" else last_text_index
                self._index = min(max_index, self._index + step)
            elif target == "last":
                self._index = len(self._filtered) - 1 if self._mode == "visual" else last_text_index
            await self._rebuild_and_edit(interaction)

        return cb

    async def _on_mode_toggle(self, interaction: discord.Interaction) -> None:
        self._mode = "text" if self._mode == "visual" else "visual"
        if self._mode == "text":
            self._index = (self._index // _TEXT_PAGE_SIZE) * _TEXT_PAGE_SIZE
        await self._rebuild_and_edit(interaction)

    async def _on_search(self, interaction: discord.Interaction) -> None:
        if not self._filtered:
            await self._send_ephemeral(interaction, "No bookmarks to search in this view.")
            return
        await interaction.response.send_modal(_BookmarkSearchModal(self))

    async def _display_titles(self) -> dict[tuple[str, str], str]:
        """One-query map of (website_key, url_name) → display title for search."""
        lister = getattr(self._store, "list_user_bookmarks_with_titles", None)
        if lister is None:
            return {}
        try:
            rows = await lister(int(self._invoker_id or 0), limit=5000)
            return {(bm.website_key, bm.url_name): title for bm, title in rows}
        except Exception:
            _log.debug("bookmark title lookup for search failed", exc_info=True)
            return {}

    async def _jump_to_search(self, interaction: discord.Interaction, raw_query: str) -> None:
        query = raw_query.strip().casefold()
        if not query:
            await self._send_ephemeral(interaction, "Enter part of a title to search for.")
            return
        titles = await self._display_titles()

        def _title_of(bm: Bookmark) -> str:
            key = self._bookmark_key(bm)
            meta = self._meta.get(key) or {}
            return str(titles.get(key) or meta.get("title") or bm.url_name)

        # First: jump to the first title that starts with the query.
        pos = next(
            (
                i
                for i, bm in enumerate(self._filtered)
                if _title_of(bm).casefold().startswith(query)
            ),
            None,
        )
        # Fallback: no prefix match → fuzzy-match the query against each title's
        # leading slice (truncated to the query length), so a near-miss typo at
        # the start of a title still lands on the closest bookmark.
        if pos is None:
            best_pos: int | None = None
            best_score = 0.0
            for i, bm in enumerate(self._filtered):
                title_prefix = _title_of(bm).casefold()[: len(query)]
                score = difflib.SequenceMatcher(None, query, title_prefix).ratio()
                if score > best_score:
                    best_score = score
                    best_pos = i
            if best_pos is not None and best_score >= _SEARCH_SIMILARITY_THRESHOLD:
                pos = best_pos
        if pos is None:
            where = (
                f"in **{self._current_folder}**" if self._current_folder else "in your bookmarks"
            )
            await self._send_ephemeral(
                interaction,
                f"No bookmark title matching **{raw_query.strip()}** {where}.",
            )
            return
        self._index = pos
        self._reset_preload_window()
        await self._rebuild_and_edit(interaction)

    async def _on_sort_select(self, interaction: discord.Interaction) -> None:
        values = (interaction.data or {}).get("values") or []  # type: ignore[union-attr]
        choice = values[0] if values else "last_updated"
        if choice == "title":
            self._filtered = sorted(self._filtered, key=lambda bm: bm.url_name.lower())
        elif choice == "scanlator":
            self._filtered = sorted(
                self._filtered,
                key=lambda bm: (bm.website_key.lower(), bm.url_name.lower()),
            )
        else:
            self._filtered = sorted(self._filtered, key=lambda bm: bm.updated_at, reverse=True)
        self._index = 0
        self._reset_preload_window()
        await self._rebuild_and_edit(interaction)

    async def _on_filter_change(self, interaction: discord.Interaction) -> None:
        values = (interaction.data or {}).get("values") or []  # type: ignore[union-attr]
        choice = values[0] if values else "__all__"
        self._current_folder = None if choice == "__all__" else choice
        self._filtered = self._apply_folder_filter()
        self._index = 0
        self._reset_preload_window()
        await self._rebuild_and_edit(interaction)

    async def _on_folder_change(self, interaction: discord.Interaction) -> None:
        if not self._filtered:
            await interaction.response.defer()
            return
        values = (interaction.data or {}).get("values") or []  # type: ignore[union-attr]
        new_folder = values[0] if values else None
        if new_folder is None or new_folder not in BOOKMARK_FOLDERS:
            await interaction.response.defer()
            return
        await self._defer_update(interaction)
        bm = self._filtered[self._index]
        try:
            await self._store.update_folder(bm.user_id, bm.website_key, bm.url_name, new_folder)
        except Exception:
            _log.exception("update_folder failed")
            await self._send_ephemeral(interaction, "Failed to move bookmark — please try again.")
            return
        new_bm = replace(bm, folder=new_folder)
        self._replace_bookmark(bm, new_bm)
        # If a folder filter is active and the new folder no longer matches, re-apply.
        self._filtered = self._apply_folder_filter()
        if not self._filtered:
            self._index = 0
        else:
            self._index = min(self._index, len(self._filtered) - 1)
        self._reset_preload_window()
        await self._rebuild_and_edit(interaction)

    async def _on_track(self, interaction: discord.Interaction) -> None:
        if not self._filtered:
            await interaction.response.defer()
            return
        await self._defer_update(interaction)
        bm = self._filtered[self._index]
        ts = await self._tracking_status_for(bm)
        state = await self._track_button_state(bm, ts)
        if not state.enabled:
            await self._send_ephemeral(
                interaction,
                state.reason or "You can't track this series from here.",
            )
            return
        guild = self._current_guild()
        if guild is None:
            await self._send_ephemeral(
                interaction,
                "Run this from the server where you want to track the series.",
            )
            return

        meta = await self._meta_for(bm)
        series_url = str(meta.get("series_url") or bm.url_name)
        title = str(meta.get("title") or bm.url_name)
        try:
            track_data = await self._crawler.request(
                "track_series",
                website_key=bm.website_key,
                series_url=series_url,
            )
        except Exception:
            _log.exception("track button crawler track_series failed")
            await self._send_ephemeral(
                interaction, "Failed to track this series — please try `/track new`."
            )
            return
        if isinstance(track_data, dict) and _is_terminal_track_response(track_data):
            series_payload = (
                track_data.get("series") if isinstance(track_data.get("series"), dict) else {}
            )
            tracked_website_key = str(track_data.get("website_key") or bm.website_key)
            tracked_url_name = str(track_data.get("url_name") or bm.url_name)
            tracked_series_url = str(track_data.get("series_url") or series_url)
            tracked_title = str(series_payload.get("title") or title)
            try:
                await self._tracked.upsert_series(
                    tracked_website_key,
                    tracked_url_name,
                    tracked_series_url,
                    tracked_title,
                    cover_url=series_payload.get("cover_url") or meta.get("cover_url"),
                    status=series_payload.get("status") or meta.get("status"),
                )
            except Exception:
                _log.debug("terminal track metadata cache failed", exc_info=True)
            await self._send_ephemeral(
                interaction,
                "This series is already completed or cancelled, so it can't be tracked. "
                "Your bookmark is unchanged.",
            )
            return
        if isinstance(track_data, dict):
            series_payload = (
                track_data.get("series") if isinstance(track_data.get("series"), dict) else {}
            )
            tracked_website_key = str(track_data.get("website_key") or bm.website_key)
            tracked_url_name = str(track_data.get("url_name") or bm.url_name)
            series_url = str(track_data.get("series_url") or series_url)
            title = str(series_payload.get("title") or title)
            meta = {
                **meta,
                "cover_url": series_payload.get("cover_url") or meta.get("cover_url"),
                "status": series_payload.get("status") or meta.get("status"),
            }
        else:
            tracked_website_key = bm.website_key
            tracked_url_name = bm.url_name
        try:
            await self._tracked.upsert_series(
                tracked_website_key,
                tracked_url_name,
                series_url,
                title,
                cover_url=meta.get("cover_url"),
                status=meta.get("status"),
            )
            await self._tracked.add_to_guild(int(guild.id), tracked_website_key, tracked_url_name)
        except Exception:
            _log.exception("track button failed")
            await self._send_ephemeral(
                interaction, "Failed to track this series — please try `/track new`."
            )
            return
        self._invalidate_status_cache(bm)

        try:
            await self._crawler.request(
                "check_series",
                website_key=tracked_website_key,
                url_name=tracked_url_name,
            )
        except Exception:
            _log.debug("track button immediate check failed", exc_info=True)

        await self._rebuild_and_edit(interaction)

    def _make_mark_delta_callback(self, delta: int):
        """Build a callback that steps the last-read chapter by ``delta`` (clamped)."""

        async def cb(interaction: discord.Interaction) -> None:
            if not self._filtered:
                await interaction.response.defer()
                return
            await self._defer_update(interaction)
            bm = self._filtered[self._index]
            chapters = await self._get_chapters(bm)
            if not chapters:
                await self._send_ephemeral(interaction, "Couldn't fetch chapters for this series.")
                return
            current, can_back, can_forward = resolve_last_read_nav(
                bm.last_read_index, len(chapters)
            )
            if delta < 0:
                if not can_back:
                    await self._send_ephemeral(interaction, "You're already on the first chapter.")
                    return
                target = current + delta  # current is a valid index when can_back
            else:
                if not can_forward:
                    await self._send_ephemeral(interaction, "You're already on the latest chapter.")
                    return
                base = current if current is not None else -1
                target = base + delta
            # Clamp into range so an over/under-shoot (e.g. -5 near the start) lands
            # on a real chapter instead of raising.
            target = max(0, min(len(chapters) - 1, target))
            ch = chapters[target]
            try:
                await self._store.update_last_read(
                    bm.user_id,
                    bm.website_key,
                    bm.url_name,
                    chapter_text=ch.name,
                    chapter_index=target,
                )
            except Exception:
                _log.exception("update_last_read failed")
                await self._send_ephemeral(interaction, "Failed to update — please try again.")
                return
            await self._refresh_current(interaction, chapter_text=ch.name, chapter_index=target)

        return cb

    async def _on_subscribe_toggle(self, interaction: discord.Interaction) -> None:
        if not self._filtered:
            await interaction.response.defer()
            return
        await self._defer_update(interaction)
        bm = self._filtered[self._index]
        ts = await self._tracking_status_for(bm)
        if ts.mutual_guild is None or not ts.channel_visible:
            await self._send_ephemeral(
                interaction,
                "You can't subscribe here — series isn't tracked in any visible channel for you.",
            )
            return
        try:
            if ts.subscribed:
                await self._subs.unsubscribe(
                    int(self._invoker_id or 0),
                    int(ts.mutual_guild.id),
                    bm.website_key,
                    bm.url_name,
                )
            else:
                await self._subs.subscribe(
                    int(self._invoker_id or 0),
                    int(ts.mutual_guild.id),
                    bm.website_key,
                    bm.url_name,
                )
        except Exception:
            _log.exception("subscribe toggle failed")
            await self._send_ephemeral(
                interaction, "Failed to update subscription — please try again."
            )
            return
        self._invalidate_status_cache(bm)
        await self._rebuild_and_edit(interaction)

    async def _on_delete(self, interaction: discord.Interaction) -> None:
        if not self._filtered:
            await interaction.response.defer()
            return
        self._pending_delete_key = self._bookmark_key(self._filtered[self._index])
        await self._rebuild_and_edit(interaction)

    async def _on_delete_cancel(self, interaction: discord.Interaction) -> None:
        self._pending_delete_key = None
        await self._rebuild_and_edit(interaction)

    async def _on_delete_confirm(self, interaction: discord.Interaction) -> None:
        if not self._filtered:
            await interaction.response.defer()
            return
        await self._defer_update(interaction)
        bm = self._filtered[self._index]
        try:
            await self._store.delete_bookmark(bm.user_id, bm.website_key, bm.url_name)
        except Exception:
            _log.exception("delete_bookmark failed")
            await self._send_ephemeral(interaction, "Failed to delete bookmark — please try again.")
            return
        self._pending_delete_key = None
        self._remove_bookmark(bm)
        self._reset_preload_window()
        await self._rebuild_and_edit(interaction)

    # ---- mutation helpers ----------------------------------------------

    def _replace_bookmark(self, old: Bookmark, new: Bookmark) -> None:
        for i, bm in enumerate(self._all):
            if (
                bm.user_id == old.user_id
                and bm.website_key == old.website_key
                and bm.url_name == old.url_name
            ):
                self._all[i] = new
                break
        for i, bm in enumerate(self._filtered):
            if (
                bm.user_id == old.user_id
                and bm.website_key == old.website_key
                and bm.url_name == old.url_name
            ):
                self._filtered[i] = new
                break

    def _remove_bookmark(self, target: Bookmark) -> None:
        key = self._bookmark_key(target)
        self._all = [bm for bm in self._all if self._bookmark_key(bm) != key]
        self._filtered = [bm for bm in self._filtered if self._bookmark_key(bm) != key]
        self._meta.pop(key, None)
        self._series_data_cache.pop(key, None)
        self._chapter_cache.pop(key, None)
        self._tracking_cache.pop(key, None)
        self._track_button_cache.pop(key, None)
        if self._filtered:
            self._index = min(self._index, len(self._filtered) - 1)
        else:
            self._index = 0

    async def _refresh_current(
        self,
        interaction: discord.Interaction,
        *,
        chapter_text: str,
        chapter_index: int,
    ) -> None:
        if not self._filtered:
            return
        bm = self._filtered[self._index]
        new_bm = replace(bm, last_read_chapter=chapter_text, last_read_index=chapter_index)
        self._replace_bookmark(bm, new_bm)
        await self._rebuild_and_edit(interaction)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _BookmarkSearchModal(discord.ui.Modal, title="Search bookmarks"):
    """Prefix-search the browser's current bookmark list by title."""

    query = discord.ui.TextInput(
        label="Title",
        placeholder="e.g. Tomb — jumps to the first title starting with this",
        required=True,
        max_length=100,
    )

    def __init__(self, browser: BookmarkBrowserView) -> None:
        super().__init__()
        self._browser = browser

    async def on_submit(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        await self._browser._jump_to_search(interaction, str(self.query.value or ""))


def _format_last_read(bm: Bookmark, chapters: list[Chapter]) -> str:
    """Format the bookmark's last-read chapter as a hyperlink when possible."""
    if bm.last_read_index is not None and 0 <= bm.last_read_index < len(chapters):
        return chapter_markdown(chapters[bm.last_read_index])
    if bm.last_read_chapter:
        return bm.last_read_chapter
    return "—"


def _is_terminal_track_response(data: dict[str, Any]) -> bool:
    return (
        data.get("tracked") is False
        and data.get("source") == "terminal_status"
        and data.get("blocked_reason") == "terminal_status"
    )


# ---------------------------------------------------------------------------
# "View Bookmark" action row used by `/bookmark new` success message
# ---------------------------------------------------------------------------


class _ViewBookmarkButton(discord.ui.Button):
    """Single-button row factory consumer; opens a BookmarkBrowserView."""

    def __init__(self, factory):
        super().__init__(label="View Bookmark", emoji="🔖", style=discord.ButtonStyle.secondary)
        self._factory = factory

    async def callback(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        try:
            view = await self._factory()
        except Exception as exc:
            _log.exception("View Bookmark button factory failed")
            await interaction.response.send_message(
                f"Couldn't open bookmark view: {exc}", ephemeral=True
            )
            return
        await interaction.response.send_message(view=view, ephemeral=True)


def view_bookmark_action_row(factory) -> discord.ui.ActionRow:
    row = discord.ui.ActionRow()
    row.add_item(_ViewBookmarkButton(factory))
    return row


__all__ = [
    "BOOKMARK_FOLDERS",
    "BookmarkBrowserView",
    "build_bookmark_detail_view",
    "build_bookmark_update_success_view",
    "folder_accent",
    "view_bookmark_action_row",
]
