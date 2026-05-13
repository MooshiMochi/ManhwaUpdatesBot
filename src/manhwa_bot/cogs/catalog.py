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
from ..crawler.website_detect import detect_website_key
from ..db.tracked import TrackedStore
from ..formatting import (
    chapters_embeds_v1,
    failed_websites_field,
    info_display_embed,
    supported_websites_embeds_v1,
)
from ..ui.error import SOURCE_CRAWLER
from ..ui.error import error_embed as _shared_error_embed
from ..ui.paginator import Paginator
from ..ui.progress_embed import ProgressEmbedState, progress_event_message
from ..ui.subscribe_view import SubscribeView

_log = logging.getLogger(__name__)

_SEARCH_PAGE_SIZE = 1  # v1 shows one result per page (rich embed with cover)
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


def _search_result_embed(item: dict, *, websites: dict[str, dict]) -> discord.Embed:
    """V1-style per-result embed for /search."""
    title = str(item.get("title") or "Unknown")
    series_url = item.get("series_url") or item.get("url") or None
    cover_url = item.get("cover_url") or item.get("cover") or None
    website_key = str(item.get("website_key") or "")
    status = item.get("status") or ""

    embed = discord.Embed(
        title=title,
        url=series_url,
        colour=discord.Colour.blurple(),
    )
    if cover_url:
        embed.set_image(url=cover_url)

    site_meta = websites.get(website_key, {})
    scanlator_name = site_meta.get("name") or website_key.title() if website_key else None
    base_url = site_meta.get("base_url") or None
    icon_url = site_meta.get("icon_url") or None
    if scanlator_name:
        embed.set_author(
            name=scanlator_name,
            url=base_url,
            icon_url=icon_url,
        )

    desc_lines: list[str] = []
    if status:
        desc_lines.append(f"**Status:** {status}")
    if website_key and base_url:
        desc_lines.append(f"**Scanlator:** [{website_key.title()}]({base_url})")
    elif website_key:
        desc_lines.append(f"**Scanlator:** {website_key.title()}")
    embed.description = "\n".join(desc_lines) if desc_lines else None
    return embed


class CatalogCog(commands.Cog, name="Catalog"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._tracked = TrackedStore(bot.db)  # type: ignore[attr-defined]

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
                return (wk, url)

        if ":" in value and not value.startswith("http"):
            wk, _, url_name = value.partition(":")
            if wk and url_name:
                tracked = await self._tracked.find(wk, url_name)
                if tracked is not None and tracked.series_url:
                    return (wk, tracked.series_url)
                # Fall through: we have no series_url cached. Letting the
                # crawler render the URL from the schema template would fail
                # for many sites, so surface a clear error instead.
                return None

        if value.startswith("http"):
            wk = await detect_website_key(self.bot, value)
            if wk:
                return (wk, value)

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
        # V1-style loading embed.
        loading = discord.Embed(
            title="Processing your request, please wait!",
            description=(
                f"🔄 Searching for **{query}** on {scanlator_website or 'all known websites'}…"
            ),
            colour=discord.Colour.green(),
        )
        bot_user = self.bot.user
        if bot_user:
            loading.set_footer(
                text=str(bot_user.display_name), icon_url=bot_user.display_avatar.url
            )
        await interaction.response.send_message(embed=loading, ephemeral=True)

        try:
            kwargs: dict = {"query": query, "limit": _SEARCH_LIMIT}
            if scanlator_website:
                kwargs["website_key"] = scanlator_website
            data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                "search", timeout=_SEARCH_TIMEOUT_MS / 1000, **kwargs
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await interaction.edit_original_response(
                embed=_shared_error_embed(f"Search failed: {exc}", source=SOURCE_CRAWLER)
            )
            return

        results: list[dict] = data.get("results") or []
        failed: list[str] = data.get("failed_websites") or []

        if not results:
            embed = discord.Embed(
                title=f'No results for "{query}"',
                colour=discord.Colour.red(),
            )
            field = failed_websites_field(failed)
            if field:
                embed.add_field(name=field[0], value=field[1], inline=False)
            await interaction.edit_original_response(embed=embed)
            return

        websites_lookup = await _get_websites_lookup(self.bot)
        embeds = [_search_result_embed(r, websites=websites_lookup) for r in results]
        field = failed_websites_field(failed)
        if field:
            for e in embeds:
                e.add_field(name=field[0], value=field[1], inline=False)

        def _subscribe_items(page: int) -> list[discord.ui.Item]:
            if page >= len(results):
                return []
            item = results[page]
            wk = item.get("website_key") or ""
            un = item.get("url_name") or ""
            su = item.get("series_url") or item.get("url") or None
            if not wk or not un:
                return []
            view = SubscribeView(
                website_key=wk,
                url_name=un,
                series_url=su,
                show_info_button=True,
                show_bookmark_button=True,
            )
            return list(view.children)

        paginator = Paginator(
            embeds,
            invoker_id=interaction.user.id,
            items_factory=_subscribe_items,
        )
        await interaction.edit_original_response(embed=embeds[0], view=paginator)

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
                embed=_error_embed(
                    "Couldn't resolve that series. Use the autocomplete or paste a "
                    "full series URL from a supported website."
                ),
                ephemeral=True,
            )
            return

        website_key, identifier = resolved

        request_id = uuid.uuid4().hex
        progress = ProgressEmbedState(command_name="/info", request_id=request_id)
        progress.add("Sent request to crawler.")
        await interaction.edit_original_response(embed=progress.to_embed())
        terminal_started = False
        progress_edit_lock = asyncio.Lock()

        async def on_progress(event: object) -> None:
            async with progress_edit_lock:
                if terminal_started:
                    return
                message, severity = progress_event_message(event)
                progress.add(message, severity=severity)
                await interaction.edit_original_response(embed=progress.to_embed())

        info_task = asyncio.create_task(
            self.bot.crawler.request_with_progress(  # type: ignore[attr-defined]
                "info",
                website_key=website_key,
                url=identifier,
                request_id=request_id,
                on_progress=on_progress,
            )
        )
        chapters_task = asyncio.create_task(
            self.bot.crawler.request(  # type: ignore[attr-defined]
                "chapters", website_key=website_key, url=identifier
            )
        )
        try:
            info_data, chapters_data = await asyncio.gather(info_task, chapters_task)
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            terminal_started = True
            for task in (info_task, chapters_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(info_task, chapters_task, return_exceptions=True)
            progress.add(str(exc), severity="error")
            history = progress.to_embed(final_error=True).description or ""
            async with progress_edit_lock:
                await interaction.edit_original_response(
                    embed=_shared_error_embed(
                        f"{exc}\n\nProgress:\n{history}",
                        source=SOURCE_CRAWLER,
                    )
                )
            return

        if not info_data:
            terminal_started = True
            progress.add("No data returned for that series.", severity="error")
            history = progress.to_embed(final_error=True).description or ""
            async with progress_edit_lock:
                await interaction.edit_original_response(
                    embed=_error_embed(f"No data returned for that series.\n\nProgress:\n{history}")
                )
            return

        chapters_list = (chapters_data or {}).get("chapters") or []
        merged: dict = dict(info_data)
        merged.setdefault("series_url", info_data.get("url") or identifier)
        merged["website_key"] = website_key
        merged["chapters"] = chapters_list
        merged["chapter_count"] = len(chapters_list)

        websites_lookup = await _get_websites_lookup(self.bot)
        site_meta = websites_lookup.get(website_key, {})
        embed = info_display_embed(
            merged,
            scanlator_icon_url=site_meta.get("icon_url"),
            scanlator_base_url=site_meta.get("base_url"),
            bot=self.bot,
        )

        url_name = await self._resolve_url_name(website_key, identifier)
        view = SubscribeView(
            website_key=website_key,
            url_name=url_name or identifier,
            series_url=merged["series_url"],
            show_track_button=True,
            show_bookmark_button=True,
        )
        terminal_started = True
        async with progress_edit_lock:
            await interaction.edit_original_response(embed=embed, view=view)

    async def _resolve_url_name(self, website_key: str, identifier: str) -> str | None:
        """Best-effort lookup: convert a series URL into a stored ``url_name``.

        We search the local tracked store by ``series_url`` first; if not
        found, return ``None`` and let callers fall back to the URL itself.
        """
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
                embed=_error_embed(
                    "Couldn't resolve that series. Use the autocomplete or paste a "
                    "full series URL from a supported website."
                ),
                ephemeral=True,
            )
            return

        website_key, identifier = resolved
        try:
            data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                "chapters", website_key=website_key, url=identifier
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await interaction.followup.send(
                embed=_shared_error_embed(str(exc), source=SOURCE_CRAWLER),
                ephemeral=True,
            )
            return

        chapter_list: list[dict] = data.get("chapters") or []
        series_title = data.get("title") or identifier
        series_url = data.get("series_url")

        embeds = chapters_embeds_v1(
            chapter_list,
            manga_title=str(series_title),
            manga_url=series_url,
            bot=self.bot,
        )

        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0], ephemeral=True)
        else:
            paginator = Paginator(embeds, invoker_id=interaction.user.id)
            await interaction.followup.send(embed=embeds[0], view=paginator, ephemeral=True)

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
                    embed=_shared_error_embed(str(exc), source=SOURCE_CRAWLER),
                    ephemeral=True,
                )
                return
        else:
            websites = list(websites_lookup.values())

        embeds = supported_websites_embeds_v1(websites, bot=bot)

        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0], ephemeral=True)
        else:
            paginator = Paginator(embeds, invoker_id=interaction.user.id)
            await interaction.followup.send(embed=embeds[0], view=paginator, ephemeral=True)


# -- helpers -------------------------------------------------------------


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(
        title="Error",
        description=message,
        colour=discord.Colour.red(),
    )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CatalogCog(bot))
