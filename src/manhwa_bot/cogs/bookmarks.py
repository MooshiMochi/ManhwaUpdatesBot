"""Bookmarks cog — /bookmark new|view|update|delete."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .. import autocomplete, formatting
from ..checks import has_premium
from ..crawler.errors import CrawlerError, Disconnected, RequestTimeout
from ..crawler.website_detect import detect_website_key, series_url_from_maybe_chapter_url
from ..db.bookmarks import Bookmark, BookmarkStore
from ..db.subscriptions import SubscriptionStore
from ..db.tracked import TrackedStore
from ..ui.bookmark_view import BOOKMARK_FOLDERS, BookmarkView
from ..ui.error import SOURCE_CRAWLER
from ..ui.error import error_embed as _shared_error_embed
from ..ui.progress_embed import ProgressEmbedState, progress_event_message

_log = logging.getLogger(__name__)

_DEFAULT_FOLDER = "Reading"
_COMPLETED_STATUSES = {"completed", "ended", "finished", "dropped", "cancelled"}

_FOLDER_CHOICES = [app_commands.Choice(name=f, value=f) for f in BOOKMARK_FOLDERS]


@dataclass(frozen=True)
class _ResolvedSeries:
    website_key: str
    url_name: str
    series_url: str
    info: dict[str, Any]

    def __iter__(self):
        yield self.website_key
        yield self.url_name
        yield self.series_url


class _BookmarkSuccessView(discord.ui.View):
    def __init__(
        self,
        *,
        bookmark: Bookmark,
        store: BookmarkStore,
        tracked: TrackedStore,
        crawler: Any,
        invoker_id: int,
        guild_id: int | None,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._bookmark = bookmark
        self._store = store
        self._tracked = tracked
        self._crawler = crawler
        self._invoker_id = invoker_id
        self._guild_id = guild_id

        button = discord.ui.Button(label="View Bookmark", style=discord.ButtonStyle.blurple)
        button.callback = self._on_view_bookmark  # type: ignore[assignment]
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._invoker_id:
            await interaction.response.send_message(
                "Only the person who ran this command can view this bookmark.",
                ephemeral=True,
            )
            return False
        return True

    async def _on_view_bookmark(self, interaction: discord.Interaction) -> None:
        view = BookmarkView(
            [self._bookmark],
            store=self._store,
            tracked=self._tracked,
            crawler=self._crawler,
            invoker_id=self._invoker_id,
            guild_id=self._guild_id,
        )
        embed = await view.initial_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(title="Error", description=message, colour=discord.Colour.red())


def _ok_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(title=title, description=description, colour=discord.Colour.green())


def _split_series_id(series_id: str) -> tuple[str, str] | None:
    """Parse ``"website_key:url_name"``."""
    if not series_id or ":" not in series_id or series_id.startswith("http"):
        return None
    parts = series_id.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return (parts[0].strip(), parts[1].strip())


def _url_name_from_url(url: str) -> str | None:
    """Derive a stable slug from the URL path (last non-empty segment)."""
    from urllib.parse import urlparse

    try:
        path = urlparse(url).path or ""
    except ValueError:
        return None
    segs = [s for s in path.split("/") if s]
    return segs[-1] if segs else None


def _chapter_label(ch: dict, fallback_idx: int) -> str:
    return (
        ch.get("chapter")
        or ch.get("name")
        or ch.get("text")
        or ch.get("chapter_number")
        or f"#{ch.get('index', fallback_idx)}"
    )


def _chapter_markdown(ch: dict, fallback_idx: int) -> str:
    """Hyperlinked chapter label, or the bare label when no URL is present."""
    label = _chapter_label(ch, fallback_idx)
    url = ch.get("url") or ch.get("chapter_url") or ""
    return f"[{label}]({url})" if url else str(label)


class BookmarksCog(commands.Cog, name="Bookmarks"):
    bookmark = app_commands.Group(name="bookmark", description="Bookmark a manga")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._bookmarks = BookmarkStore(bot.db)  # type: ignore[attr-defined]
        self._tracked = TrackedStore(bot.db)  # type: ignore[attr-defined]
        self._subs = SubscriptionStore(bot.db)  # type: ignore[attr-defined]

    # -- internal helpers -----------------------------------------------

    async def _resolve_series(
        self,
        manga_url_or_id: str,
        *,
        request_id: str | None = None,
        on_progress: Any | None = None,
    ) -> _ResolvedSeries | None:
        """Return ``(website_key, url_name, series_url)`` or None.

        Tries the autocomplete value format first, then falls back to a
        crawler ``info`` lookup when given a raw URL.
        """
        parsed = _split_series_id(manga_url_or_id)
        if parsed is not None:
            website_key, url_name = parsed
            tracked = await self._tracked.find(website_key, url_name)
            if tracked is not None:
                return _ResolvedSeries(website_key, url_name, tracked.series_url, {})
            # Not yet tracked; canonicalize via the crawler so we know the
            # series_url (used by /bookmark new for the chapters call). The
            # crawler needs a full series URL — passing a bare url_name fails
            # the schema URL-template rebuild for many sites, so don't try.
            return None

        # Fallback: treat as a URL. Detect the website_key locally; the
        # ``info`` endpoint doesn't return ``url_name``, so derive it from the
        # URL path (last non-empty segment, ignoring trailing slashes).
        if manga_url_or_id.startswith("http"):
            wk = await detect_website_key(self.bot, manga_url_or_id)
            if not wk:
                return None
            series_url = series_url_from_maybe_chapter_url(manga_url_or_id)
            try:
                if hasattr(self.bot.crawler, "request_with_progress"):  # type: ignore[attr-defined]
                    data = await self.bot.crawler.request_with_progress(  # type: ignore[attr-defined]
                        "info",
                        website_key=wk,
                        url=series_url,
                        request_id=request_id,
                        on_progress=on_progress,
                    )
                else:
                    data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                        "info",
                        website_key=wk,
                        url=series_url,
                    )
            except CrawlerError, RequestTimeout, Disconnected:
                return None
            su = data.get("series_url") or data.get("url") or series_url
            un = data.get("url_name") or _url_name_from_url(su)
            if not un:
                return None
            return _ResolvedSeries(wk, un, su, data)
        return None

    async def _fetch_chapters_for(self, resolved: _ResolvedSeries) -> list[dict]:
        """Use live info chapters first, then fall back to cached crawler chapters."""
        chapters = resolved.info.get("chapters")
        if isinstance(chapters, list) and chapters:
            return list(chapters)
        data = await self.bot.crawler.request(  # type: ignore[attr-defined]
            "chapters",
            website_key=resolved.website_key,
            url=resolved.series_url,
        )
        return list(data.get("chapters") or [])

    async def _cache_series_metadata(
        self,
        resolved: _ResolvedSeries,
        chapters: list[dict],
    ) -> tuple[str, str | None, str]:
        """Persist best-effort metadata without marking the series tracked in a guild."""
        info = resolved.info
        title = str(info.get("title") or resolved.url_name)
        cover_url = info.get("cover_url")
        status = str(info.get("status") or "Unknown")
        latest = chapters[0] if chapters else {}
        await self._tracked.upsert_series(
            resolved.website_key,
            resolved.url_name,
            resolved.series_url,
            title,
            cover_url=cover_url,
            status=status,
            last_chapter_text=_chapter_label(latest, 0) if latest else None,
            last_chapter_url=latest.get("url") or latest.get("chapter_url") if latest else None,
        )
        return title, cover_url, status

    async def _maybe_auto_subscribe(
        self,
        *,
        user_id: int,
        guild_id: int | None,
        website_key: str,
        url_name: str,
        chapter_index: int,
        total_chapters: int,
        status: str | None,
    ) -> str | None:
        """Run the auto-subscribe gate; return a suffix to append, or None.

        Mirrors v1: only fires on the final chapter of an ongoing series
        that's tracked in the invoking guild and not yet subscribed by the
        user. Returns a "subscribed" message on success, or a "ask an admin"
        hint when the series isn't tracked. Skipped entirely in DMs.
        """
        if guild_id is None or total_chapters <= 0:
            return None
        if chapter_index != total_chapters - 1:
            return None

        tracked_in_guild = await self._tracked.list_for_guild(guild_id, limit=500)
        match = next(
            (
                t
                for t in tracked_in_guild
                if t.website_key == website_key and t.url_name == url_name
            ),
            None,
        )
        if match is None:
            return "Ask a server admin to `/track new` this series to receive new-chapter pings."

        effective_status = (status or match.status or "").strip().lower()
        if effective_status in _COMPLETED_STATUSES:
            return None

        already = await self._subs.is_subscribed(user_id, guild_id, website_key, url_name)
        if already:
            return None

        await self._subs.subscribe(user_id, guild_id, website_key, url_name)
        return "Auto-subscribed for new chapters."

    # -- /bookmark new --------------------------------------------------

    @bookmark.command(name="new", description="Bookmark a new manga")
    @app_commands.describe(
        manga_url_or_id="The name of the bookmarked manga you want to view",
        folder="The folder you want to view. If manga is specified, this is ignored.",
    )
    @app_commands.autocomplete(manga_url_or_id=autocomplete.tracked_manga_in_guild)
    @app_commands.choices(folder=_FOLDER_CHOICES)
    @app_commands.rename(manga_url_or_id="manga_url")
    @has_premium(dm_only=True)
    async def bookmark_new(
        self,
        interaction: discord.Interaction,
        manga_url_or_id: str,
        folder: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        folder_value = folder.value if folder else _DEFAULT_FOLDER
        if folder_value not in BOOKMARK_FOLDERS:
            await interaction.followup.send(embed=_error_embed("Unknown folder."), ephemeral=True)
            return

        progress: ProgressEmbedState | None = None
        progress_edit_lock = asyncio.Lock()
        terminal_started = False

        if manga_url_or_id.startswith("http"):
            request_id = uuid.uuid4().hex
            progress = ProgressEmbedState(command_name="/bookmark new", request_id=request_id)
            progress.add("Sent request to crawler.")
            await interaction.edit_original_response(embed=progress.to_embed())

            async def on_progress(event: object) -> None:
                async with progress_edit_lock:
                    if terminal_started:
                        return
                    message, severity = progress_event_message(event)
                    progress.add(message, severity=severity)
                    await interaction.edit_original_response(embed=progress.to_embed())

        else:
            request_id = None
            on_progress = None

        async def respond_final(**kwargs) -> None:
            nonlocal terminal_started
            if progress is None:
                await interaction.followup.send(**kwargs, ephemeral=True)
                return
            terminal_started = True
            async with progress_edit_lock:
                await interaction.edit_original_response(**kwargs)

        resolved = await self._resolve_series(
            manga_url_or_id,
            request_id=request_id,
            on_progress=on_progress,
        )
        if resolved is None:
            message = "Couldn't resolve that series. Use the autocomplete or paste a series URL."
            if progress is not None:
                progress.add(message, severity="error")
                history = progress.to_embed(final_error=True).description or ""
                message = f"{message}\n\nProgress:\n{history}"
            await respond_final(
                embed=_error_embed(
                    message,
                )
            )
            return
        website_key, url_name, series_url = resolved

        try:
            info_data = await self.bot.crawler.request_with_progress(  # type: ignore[attr-defined]
                "info",
                website_key=website_key,
                url=series_url or url_name,
                request_id=request_id,
                on_progress=on_progress,
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await respond_final(
                embed=_shared_error_embed(f"Couldn't fetch chapters: {exc}", source=SOURCE_CRAWLER),
            )
            return
        data = info_data

        chapters: list[dict] = info_data.get("chapters") or info_data.get("latest_chapters") or []
        if not chapters:
            await respond_final(
                embed=_error_embed("No chapters available for this series."),
            )
            return

        first_label = _chapter_label(chapters[0], 0)
        await self._bookmarks.upsert_bookmark(
            interaction.user.id,
            website_key,
            url_name,
            folder=folder_value,
            last_read_chapter=first_label,
            last_read_index=0,
        )
        get_bookmark = getattr(self._bookmarks, "get_bookmark", None)
        bookmark = (
            await get_bookmark(interaction.user.id, website_key, url_name)
            if get_bookmark is not None
            else None
        )

        title = data.get("title") or url_name
        site_meta = await self._site_metadata(website_key)
        tracked = await self._tracked.find(website_key, url_name)
        cover_url = (tracked.cover_url if tracked else None) or data.get("cover_url")
        status = data.get("status") or (tracked.status if tracked else None) or "Unknown"
        is_completed = (status or "").strip().lower() in _COMPLETED_STATUSES

        first_md = _chapter_markdown(chapters[0], 0)
        latest_md = _chapter_markdown(chapters[-1], len(chapters) - 1)
        next_md = _chapter_markdown(chapters[1], 1) if len(chapters) > 1 else None

        embed = formatting.bookmark_embed_v1(
            title=str(title),
            series_url=series_url or "",
            website_key=website_key,
            cover_url=cover_url,
            scanlator_base_url=site_meta.get("base_url"),
            scanlator_icon_url=site_meta.get("icon_url"),
            last_read_chapter=first_md,
            next_chapter=next_md,
            folder=folder_value,
            available_chapters_label=latest_md,
            chapter_count=len(chapters),
            status=str(status),
            is_completed=is_completed,
            bot=self.bot,
        )
        success_view = (
            _BookmarkSuccessView(
                bookmark=bookmark,
                store=self._bookmarks,
                tracked=self._tracked,
                crawler=self.bot.crawler,  # type: ignore[attr-defined]
                invoker_id=interaction.user.id,
                guild_id=interaction.guild_id,
            )
            if bookmark is not None
            else None
        )
        await respond_final(
            content=f"Successfully bookmarked {title}",
            embed=embed,
            view=success_view,
        )

    # -- /bookmark view -------------------------------------------------

    @bookmark.command(name="view", description="View your bookmark(s)")
    @app_commands.describe(
        series="The name of the bookmarked manga you want to view",
        folder="The folder you want to view. If manga is specified, this is ignored.",
    )
    @app_commands.autocomplete(series=autocomplete.user_bookmarks)
    @app_commands.choices(folder=_FOLDER_CHOICES)
    @app_commands.rename(series="manga")
    @has_premium(dm_only=True)
    async def bookmark_view(
        self,
        interaction: discord.Interaction,
        series: str | None = None,
        folder: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        folder_value = folder.value if folder else None
        bookmarks = await self._bookmarks.list_user_bookmarks(
            interaction.user.id, folder=folder_value, limit=500
        )

        # Drop entries whose website is no longer supported.
        supported = await self._supported_websites_keys()
        if supported:
            bookmarks = [b for b in bookmarks if b.website_key in supported]

        if not bookmarks:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="No Bookmarks",
                    description="You have no bookmarks.",
                    colour=discord.Colour.red(),
                ),
                ephemeral=True,
            )
            return

        # Optional jump-to.
        jump_index = 0
        if series:
            parsed = _split_series_id(series)
            if parsed is None:
                await interaction.followup.send(
                    embed=_error_embed("Invalid series id."), ephemeral=True
                )
                return
            wk, un = parsed
            for i, bm in enumerate(bookmarks):
                if bm.website_key == wk and bm.url_name == un:
                    jump_index = i
                    break
            else:
                await interaction.followup.send(
                    embed=_error_embed("That bookmark wasn't found in the current view."),
                    ephemeral=True,
                )
                return

        view = BookmarkView(
            bookmarks,
            store=self._bookmarks,
            tracked=self._tracked,
            crawler=self.bot.crawler,  # type: ignore[attr-defined]
            invoker_id=interaction.user.id,
            guild_id=interaction.guild_id,
            current_folder=folder_value,
            index=jump_index,
        )
        embed = await view.initial_embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def _site_metadata(self, website_key: str) -> dict:
        """Return cached metadata dict for *website_key*, or {} on error."""
        try:
            bot: Any = self.bot
            ttl = bot.config.supported_websites_cache.ttl_seconds

            async def _loader() -> list[dict]:
                d = await bot.crawler.request("supported_websites")
                return d.get("websites") or []

            websites: list[dict] = await bot.websites_cache.get_or_set(
                "websites_full", _loader, ttl
            )
        except Exception:
            return {}
        for w in websites:
            if (w.get("key") or w.get("website_key")) == website_key:
                return w
        return {}

    async def _supported_websites_keys(self) -> set[str]:
        """Return the cached set of supported website keys, or empty set on error."""
        try:
            bot: Any = self.bot
            ttl = bot.config.supported_websites_cache.ttl_seconds

            async def _loader() -> list[dict]:
                d = await bot.crawler.request("supported_websites")
                return d.get("websites") or []

            websites: list[dict] = await bot.websites_cache.get_or_set(
                "websites_full", _loader, ttl
            )
            return {
                (w.get("key") or w.get("website_key"))
                for w in websites
                if w.get("key") or w.get("website_key")
            }
        except Exception:
            _log.exception("supported_websites lookup failed; not filtering")
            return set()

    # -- /bookmark update -----------------------------------------------

    @bookmark.command(name="update", description="Update a bookmark")
    @app_commands.describe(
        series="The name of the bookmarked manga you want to update",
        chapter_index="The chapter you want to update the bookmark to",
        folder="The folder you want to view. If manga is specified, this is ignored.",
    )
    @app_commands.autocomplete(series=autocomplete.user_bookmarks)
    @app_commands.choices(folder=_FOLDER_CHOICES)
    @app_commands.rename(series="manga")
    @app_commands.rename(chapter_index="chapter")
    @has_premium(dm_only=True)
    async def bookmark_update(
        self,
        interaction: discord.Interaction,
        series: str,
        chapter_index: int | None = None,
        folder: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        if chapter_index is None and folder is None:
            await interaction.followup.send(
                embed=_error_embed("Specify at least one of `chapter_index` or `folder`."),
                ephemeral=True,
            )
            return

        parsed = _split_series_id(series)
        if parsed is None:
            await interaction.followup.send(
                embed=_error_embed("Invalid series id."), ephemeral=True
            )
            return
        website_key, url_name = parsed

        existing = await self._bookmarks.get_bookmark(interaction.user.id, website_key, url_name)
        if existing is None:
            await interaction.followup.send(
                embed=_error_embed(
                    "You don't have a bookmark for that series — use `/bookmark new` first."
                ),
                ephemeral=True,
            )
            return

        new_chapter_label: str | None = None
        auto_subscribed_title: str | None = None
        should_track = False

        if chapter_index is not None:
            tracked = await self._tracked.find(website_key, url_name)
            identifier = tracked.series_url if tracked else url_name

            upd_request_id = uuid.uuid4().hex
            upd_progress = ProgressEmbedState(
                command_name="/bookmark update", request_id=upd_request_id
            )
            upd_progress.add("Sent request to crawler.")
            upd_progress_message = await interaction.followup.send(
                embed=upd_progress.to_embed(), ephemeral=True, wait=True
            )
            upd_terminal_started = False
            upd_progress_edit_lock = asyncio.Lock()

            async def on_upd_progress(event: object) -> None:
                nonlocal upd_terminal_started
                async with upd_progress_edit_lock:
                    if upd_terminal_started:
                        return
                    msg, severity = progress_event_message(event)
                    upd_progress.add(msg, severity=severity)
                    await upd_progress_message.edit(embed=upd_progress.to_embed())

            try:
                info_data = await self.bot.crawler.request_with_progress(  # type: ignore[attr-defined]
                    "info",
                    website_key=website_key,
                    url=identifier,
                    request_id=upd_request_id,
                    on_progress=on_upd_progress,
                )
            except (CrawlerError, RequestTimeout, Disconnected) as exc:
                upd_terminal_started = True
                upd_progress.add(str(exc), severity="error")
                history = upd_progress.to_embed(final_error=True).description or ""
                async with upd_progress_edit_lock:
                    await upd_progress_message.edit(
                        embed=_shared_error_embed(
                            f"Couldn't fetch chapters: {exc}\n\nProgress:\n{history}",
                            source=SOURCE_CRAWLER,
                        )
                    )
                return
            upd_terminal_started = True
            data = info_data
            chapters: list[dict] = (
                info_data.get("chapters") or info_data.get("latest_chapters") or []
            )
            if not chapters:
                async with upd_progress_edit_lock:
                    await upd_progress_message.edit(
                        embed=_error_embed("No chapters available for this series.")
                    )
                return
            if not (0 <= chapter_index < len(chapters)):
                async with upd_progress_edit_lock:
                    await upd_progress_message.edit(
                        embed=_error_embed(f"Chapter index out of range (0 - {len(chapters) - 1}).")
                    )
                return

            label = _chapter_label(chapters[chapter_index], chapter_index)
            await self._bookmarks.update_last_read(
                interaction.user.id,
                website_key,
                url_name,
                chapter_text=label,
                chapter_index=chapter_index,
            )
            new_chapter_label = label

            suffix = await self._maybe_auto_subscribe(
                user_id=interaction.user.id,
                guild_id=interaction.guild_id,
                website_key=website_key,
                url_name=url_name,
                chapter_index=chapter_index,
                total_chapters=len(chapters),
                status=data.get("status"),
            )
            if suffix:
                if "Auto-subscribed" in suffix:
                    auto_subscribed_title = (
                        tracked.title if tracked else (data.get("title") or url_name)
                    )
                else:
                    should_track = True

        if folder is not None:
            await self._bookmarks.update_folder(
                interaction.user.id, website_key, url_name, folder.value
            )

        embed = formatting.bookmark_update_success_embed(
            moved_folder=folder.value if folder is not None else None,
            new_chapter_label=new_chapter_label,
            auto_subscribed_title=auto_subscribed_title,
            should_track=should_track,
        )
        if chapter_index is not None:
            # Replace the progress message with the final success embed.
            async with upd_progress_edit_lock:
                await upd_progress_message.edit(embed=embed)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    # -- /bookmark delete -----------------------------------------------

    @bookmark.command(name="delete", description="Delete a bookmark")
    @app_commands.describe(series="The name of the bookmarked manga you want to delete")
    @app_commands.autocomplete(series=autocomplete.user_bookmarks)
    @app_commands.rename(series="manga")
    @has_premium(dm_only=True)
    async def bookmark_delete(
        self,
        interaction: discord.Interaction,
        series: str,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        parsed = _split_series_id(series)
        if parsed is None:
            await interaction.followup.send(
                embed=_error_embed("Invalid series id."), ephemeral=True
            )
            return
        website_key, url_name = parsed

        existing = await self._bookmarks.get_bookmark(interaction.user.id, website_key, url_name)
        if existing is None:
            await interaction.followup.send(
                embed=_error_embed("You don't have a bookmark for that series."),
                ephemeral=True,
            )
            return

        await self._bookmarks.delete_bookmark(interaction.user.id, website_key, url_name)
        await interaction.followup.send("Successfully deleted bookmark", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BookmarksCog(bot))
