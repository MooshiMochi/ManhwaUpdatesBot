"""Catalog cog — /search, /info, /chapters, /supported_websites."""

from __future__ import annotations

import asyncio
import logging
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from .. import autocomplete
from ..checks import has_premium
from ..crawler.errors import CrawlerError, Disconnected, RequestTimeout
from ..crawler.website_detect import detect_website_key, series_url_from_maybe_chapter_url
from ..db.tracked import TrackedStore
from ..ui.components.chapter_list import build_chapter_list_views, build_supported_websites_views
from ..ui.components.error import SOURCE_CRAWLER, build_error_view
from ..ui.components.paginator import LayoutPaginator
from ..ui.components.progress import ProgressLayoutState, progress_event_message
from ..ui.components.series_info import (
    SeriesActionRow,
    build_info_view,
    build_no_results_view,
    build_search_result_view,
)

_log = logging.getLogger(__name__)

_SEARCH_LIMIT = 20
_SEARCH_TIMEOUT_MS = 15_000


async def _get_websites_lookup(bot) -> dict[str, dict]:
    """Return a lookup of website_key -> website metadata dict using the cache."""
    ttl = bot.config.supported_websites_cache.ttl_seconds

    async def _loader() -> list[dict]:
        d = await bot.crawler.request("supported_websites")
        return d.get("websites") or []

    try:
        websites: list[dict] = await bot.websites_cache.get_or_set("websites_full", _loader, ttl)
    except CrawlerError, RequestTimeout, Disconnected:
        websites = []

    return {
        str(w.get("key") or w.get("website_key") or ""): w
        for w in websites
        if w.get("key") or w.get("website_key")
    }


class CatalogCog(commands.Cog, name="Catalog"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._tracked = TrackedStore(bot.db)  # type: ignore[attr-defined]

    async def _fetch_info_and_chapters(
        self,
        *,
        website_key: str,
        identifier: str,
    ) -> tuple[dict, list[dict]]:
        """Fetch live info and use embedded chapters if no cached chapters exist."""
        info_data = await self.bot.crawler.request(  # type: ignore[attr-defined]
            "info",
            website_key=website_key,
            url=identifier,
        )
        chapters = await self._fetch_display_chapters(
            website_key=website_key,
            identifier=identifier,
            info_data=info_data,
            raise_unexpected=True,
        )
        return info_data, chapters

    async def _fetch_display_chapters(
        self,
        *,
        website_key: str,
        identifier: str,
        info_data: dict,
        raise_unexpected: bool = False,
    ) -> list[dict]:
        """Fetch URL-rich chapter rows, falling back to chapters embedded in info."""
        try:
            chapters_data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                "chapters",
                website_key=website_key,
                url=identifier,
            )
            chapters = list(chapters_data.get("chapters") or [])
            if chapters:
                return chapters
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            if raise_unexpected and (not isinstance(exc, CrawlerError) or exc.code != "not_found"):
                raise
        return list(info_data.get("chapters") or info_data.get("latest_chapters") or [])

    async def _resolve_series_input(self, value: str) -> tuple[str, str] | None:
        """Resolve a slash-command series input into ``(website_key, series_url)``.

        Accepts:
        - ``"website_key|series_url"`` — search-as-you-type autocomplete value.
        - ``"website_key:url_name"``   — tracked-manga autocomplete value;
          looked up in the local tracked store to recover the full series URL.
        - bare ``https://…`` URL       — website_key inferred from the host
          via the supported-websites cache.

        Returns ``None`` when the input cannot be resolved to a usable URL.
        """
        if not value:
            return None

        if "|" in value and not value.startswith("http"):
            wk, _, url = value.partition("|")
            if wk and url:
                return (wk, series_url_from_maybe_chapter_url(url))

        if ":" in value and not value.startswith("http"):
            wk, _, url_name = value.partition(":")
            if wk and url_name:
                tracked = await self._tracked.find(wk, url_name)
                if tracked is not None and tracked.series_url:
                    return (wk, tracked.series_url)
                return None

        if value.startswith("http"):
            wk = await detect_website_key(self.bot, value)
            if wk:
                return (wk, series_url_from_maybe_chapter_url(value))

        return None

    # -- /search ---------------------------------------------------------

    @app_commands.command(
        name="search",
        description="Search for a manga on on all/one scanlator of choice.",
    )
    @app_commands.describe(
        query="The name of the manga.",
        scanlator_website="The website to search on.",
    )
    @app_commands.autocomplete(scanlator_website=autocomplete.supported_website_keys)
    @app_commands.rename(scanlator_website="scanlator")
    @has_premium(dm_only=True)
    async def search(
        self,
        interaction: discord.Interaction,
        query: str,
        scanlator_website: str | None = None,
    ) -> None:
        request_id = uuid.uuid4().hex
        progress = ProgressLayoutState(command_name="/search", request_id=request_id, bot=self.bot)
        progress.add("Sent request to crawler.")
        await interaction.response.send_message(view=progress.to_view(), ephemeral=True)
        terminal_started = False
        progress_edit_lock = asyncio.Lock()

        async def on_progress(event: object) -> None:
            async with progress_edit_lock:
                if terminal_started:
                    return
                message, severity = progress_event_message(event)
                progress.add(message, severity=severity)
                await interaction.edit_original_response(view=progress.to_view())

        try:
            kwargs: dict = {"query": query, "limit": _SEARCH_LIMIT}
            if scanlator_website:
                kwargs["website_key"] = scanlator_website
            data = await self.bot.crawler.request_with_progress(  # type: ignore[attr-defined]
                "search",
                request_id=request_id,
                on_progress=on_progress,
                timeout=_SEARCH_TIMEOUT_MS / 1000,
                **kwargs,
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            terminal_started = True
            progress.add(str(exc), severity="error")
            async with progress_edit_lock:
                await interaction.edit_original_response(
                    view=build_error_view(str(exc), source=SOURCE_CRAWLER, bot=self.bot),
                )
            return

        results: list[dict] = data.get("results") or []
        failed: list[str] = data.get("failed_websites") or []

        if not results:
            terminal_started = True
            async with progress_edit_lock:
                await interaction.edit_original_response(
                    view=build_no_results_view(query=query, failed_websites=failed, bot=self.bot),
                )
            return

        websites_lookup = await _get_websites_lookup(self.bot)

        pages: list[discord.ui.LayoutView] = []
        total = len(results)
        for i, item in enumerate(results):
            wk = str(item.get("website_key") or "")
            un = str(item.get("url_name") or "")
            su = item.get("series_url") or item.get("url") or None
            action_row: SeriesActionRow | None = None
            if wk and un:
                action_row = SeriesActionRow(
                    website_key=wk,
                    url_name=un,
                    series_url=su,
                    show_info_button=True,
                    show_bookmark_button=True,
                )
            pages.append(
                build_search_result_view(
                    item,
                    site_meta=websites_lookup.get(wk, {}),
                    page=i + 1,
                    total_pages=total,
                    failed_websites=failed if i == 0 else None,
                    action_row=action_row,
                    bot=self.bot,
                    invoker_id=interaction.user.id,
                )
            )

        terminal_started = True
        paginator = LayoutPaginator(pages, invoker_id=interaction.user.id)
        async with progress_edit_lock:
            await interaction.edit_original_response(view=paginator.current_view)
        try:
            paginator.bind_message(await interaction.original_response())
        except discord.HTTPException:
            pass

    # -- /info -----------------------------------------------------------

    @app_commands.command(name="info", description="Display info about a manhwa.")
    @app_commands.describe(series="The name of the manhwa you want to get info for.")
    @app_commands.autocomplete(series=autocomplete.tracked_manga_in_guild)
    @app_commands.rename(series="manhwa")
    @has_premium(dm_only=True)
    async def info(
        self,
        interaction: discord.Interaction,
        series: str,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        resolved = await self._resolve_series_input(series)
        if resolved is None:
            await interaction.followup.send(
                view=build_error_view(
                    "Couldn't resolve that series. Use the autocomplete or paste a "
                    "full series URL from a supported website.",
                    bot=self.bot,
                ),
                ephemeral=True,
            )
            return

        website_key, identifier = resolved

        request_id = uuid.uuid4().hex
        progress = ProgressLayoutState(command_name="/info", request_id=request_id, bot=self.bot)
        progress.add("Sent request to crawler.")
        progress_message = await interaction.followup.send(
            view=progress.to_view(),
            ephemeral=True,
            wait=True,
        )
        terminal_started = False
        progress_edit_lock = asyncio.Lock()

        async def on_progress(event: object) -> None:
            async with progress_edit_lock:
                if terminal_started:
                    return
                message, severity = progress_event_message(event)
                progress.add(message, severity=severity)
                await progress_message.edit(view=progress.to_view())

        try:
            info_data = await self.bot.crawler.request_with_progress(  # type: ignore[attr-defined]
                "info",
                website_key=website_key,
                url=identifier,
                request_id=request_id,
                on_progress=on_progress,
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            terminal_started = True
            progress.add(str(exc), severity="error")
            async with progress_edit_lock:
                await progress_message.edit(
                    view=build_error_view(str(exc), source=SOURCE_CRAWLER, bot=self.bot),
                )
            return

        if not info_data:
            terminal_started = True
            async with progress_edit_lock:
                await progress_message.edit(
                    view=build_error_view("No data returned for that series.", bot=self.bot),
                )
            return

        chapter_list = await self._fetch_display_chapters(
            website_key=website_key,
            identifier=identifier,
            info_data=info_data,
        )

        merged: dict = dict(info_data)
        merged.setdefault("series_url", info_data.get("url") or identifier)
        merged["website_key"] = website_key
        merged["chapters"] = chapter_list
        merged.setdefault("chapter_count", len(chapter_list) if chapter_list else 0)

        websites_lookup = await _get_websites_lookup(self.bot)
        site_meta = websites_lookup.get(website_key, {})

        url_name = (
            merged.get("url_name")
            or await self._resolve_url_name(website_key, str(merged["series_url"]))
            or await self._resolve_url_name(website_key, identifier)
        )
        action_row = SeriesActionRow(
            website_key=website_key,
            url_name=url_name or identifier,
            series_url=merged.get("series_url"),
            show_bookmark_button=True,
        )

        view = build_info_view(
            merged,
            site_meta=site_meta,
            request_id=request_id,
            action_row=action_row,
            bot=self.bot,
            invoker_id=interaction.user.id,
        )
        terminal_started = True
        async with progress_edit_lock:
            await progress_message.edit(view=view)

    async def _resolve_url_name(self, website_key: str, identifier: str) -> str | None:
        """Best-effort lookup: convert a series URL into a stored ``url_name``."""
        if not identifier.startswith("http"):
            return identifier
        try:
            row = await self.bot.db.fetchone(  # type: ignore[attr-defined]
                "SELECT url_name FROM tracked_series WHERE website_key = ? AND series_url = ?",
                (website_key, identifier),
            )
        except Exception:
            return None
        return row["url_name"] if row else None

    # -- /chapters -------------------------------------------------------

    @app_commands.command(name="chapters", description="Get a list of chapters for a manga.")
    @app_commands.describe(series="The name of the manga.")
    @app_commands.autocomplete(series=autocomplete.tracked_manga_in_guild)
    @app_commands.rename(series="manga")
    @has_premium(dm_only=True)
    async def chapters(
        self,
        interaction: discord.Interaction,
        series: str,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        resolved = await self._resolve_series_input(series)
        if resolved is None:
            await interaction.followup.send(
                view=build_error_view(
                    "Couldn't resolve that series. Use the autocomplete or paste a "
                    "full series URL from a supported website.",
                    bot=self.bot,
                ),
                ephemeral=True,
            )
            return

        website_key, identifier = resolved

        request_id = uuid.uuid4().hex
        progress = ProgressLayoutState(
            command_name="/chapters", request_id=request_id, bot=self.bot
        )
        progress.add("Sent request to crawler.")
        progress_message = await interaction.followup.send(
            view=progress.to_view(),
            ephemeral=True,
            wait=True,
        )
        terminal_started = False
        progress_edit_lock = asyncio.Lock()

        async def on_progress(event: object) -> None:
            async with progress_edit_lock:
                if terminal_started:
                    return
                message, severity = progress_event_message(event)
                progress.add(message, severity=severity)
                await progress_message.edit(view=progress.to_view())

        try:
            info_data = await self.bot.crawler.request_with_progress(  # type: ignore[attr-defined]
                "info",
                website_key=website_key,
                url=identifier,
                request_id=request_id,
                on_progress=on_progress,
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            terminal_started = True
            progress.add(str(exc), severity="error")
            async with progress_edit_lock:
                await progress_message.edit(
                    view=build_error_view(str(exc), source=SOURCE_CRAWLER, bot=self.bot),
                )
            return

        chapter_list = await self._fetch_display_chapters(
            website_key=website_key,
            identifier=identifier,
            info_data=info_data,
        )
        series_title = info_data.get("title") or identifier
        series_url = info_data.get("url")

        pages = build_chapter_list_views(
            chapter_list,
            manga_title=str(series_title),
            manga_url=series_url,
            bot=self.bot,
            invoker_id=interaction.user.id,
        )

        if not pages:
            terminal_started = True
            async with progress_edit_lock:
                await progress_message.edit(
                    view=build_error_view(
                        f"No chapters found for **{series_title}**.", bot=self.bot
                    ),
                )
            return

        terminal_started = True
        paginator = LayoutPaginator(pages, invoker_id=interaction.user.id)
        async with progress_edit_lock:
            await progress_message.edit(view=paginator.current_view)
        paginator.bind_message(progress_message)

    # -- /supported_websites --------------------------------------------

    @app_commands.command(
        name="supported_websites",
        description="Get a list of supported websites.",
    )
    async def supported_websites(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        bot = self.bot  # type: ignore[attr-defined]
        websites_lookup = await _get_websites_lookup(bot)
        if not websites_lookup:
            try:
                d = await bot.crawler.request("supported_websites")
                websites = d.get("websites") or []
            except (CrawlerError, RequestTimeout, Disconnected) as exc:
                await interaction.followup.send(
                    view=build_error_view(str(exc), source=SOURCE_CRAWLER, bot=self.bot),
                    ephemeral=True,
                )
                return
        else:
            websites = list(websites_lookup.values())

        pages = build_supported_websites_views(
            websites, bot=self.bot, invoker_id=interaction.user.id
        )

        if len(pages) == 1:
            await interaction.followup.send(view=pages[0], ephemeral=True)
            return

        paginator = LayoutPaginator(pages, invoker_id=interaction.user.id)
        msg = await interaction.followup.send(
            view=paginator.current_view, ephemeral=True, wait=True
        )
        paginator.bind_message(msg)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CatalogCog(bot))
