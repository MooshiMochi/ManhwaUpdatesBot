"""Catalog cog — /search, /info, /chapters, /supported_websites."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import autocomplete
from ..checks import has_premium
from ..crawler.errors import CrawlerError, Disconnected, RequestTimeout
from ..formatting import (
    chapter_list_embeds,
    failed_websites_field,
    search_results_embed,
    series_info_embed,
    supported_websites_embeds,
)
from ..ui.paginator import Paginator
from ..ui.subscribe_view import SubscribeView

_log = logging.getLogger(__name__)

_SEARCH_PAGE_SIZE = 5
_SEARCH_LIMIT = 20
_SEARCH_TIMEOUT_MS = 15_000


class CatalogCog(commands.Cog, name="Catalog"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -- /search ---------------------------------------------------------

    @app_commands.command(name="search", description="Search for a manga / manhwa across all sites")
    @app_commands.describe(
        query="Title or URL to search for",
        scanlator_website="Restrict results to one website (optional)",
    )
    @app_commands.autocomplete(scanlator_website=autocomplete.supported_website_keys)
    @has_premium(dm_only=True)
    async def search(
        self,
        interaction: discord.Interaction,
        query: str,
        scanlator_website: str | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)

        try:
            kwargs: dict = {"query": query, "limit": _SEARCH_LIMIT}
            if scanlator_website:
                kwargs["website_key"] = scanlator_website
            data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                "search", timeout=_SEARCH_TIMEOUT_MS / 1000, **kwargs
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await interaction.followup.send(
                embed=_error_embed(f"Search failed: {exc}"), ephemeral=True
            )
            return

        results: list[dict] = data.get("results") or []
        failed: list[str] = data.get("failed_websites") or []

        if not results:
            embed = discord.Embed(
                title=f'No results for "{query}"',
                colour=discord.Colour.greyple(),
            )
            field = failed_websites_field(failed)
            if field:
                embed.add_field(name=field[0], value=field[1], inline=False)
            await interaction.followup.send(embed=embed)
            return

        total_pages = max(1, (len(results) + _SEARCH_PAGE_SIZE - 1) // _SEARCH_PAGE_SIZE)

        def _make_embed(page: int) -> discord.Embed:
            emb = search_results_embed(
                results,
                query=query,
                page=page,
                page_size=_SEARCH_PAGE_SIZE,
                total_pages=total_pages,
            )
            field = failed_websites_field(failed)
            if field:
                emb.add_field(name=field[0], value=field[1], inline=False)
            return emb

        embeds = [_make_embed(p) for p in range(total_pages)]

        def _subscribe_items(page: int) -> list[discord.ui.Item]:
            chunk_start = page * _SEARCH_PAGE_SIZE
            chunk = results[chunk_start : chunk_start + _SEARCH_PAGE_SIZE]
            if not chunk:
                return []
            first = chunk[0]
            wk = first.get("website_key") or ""
            un = first.get("url_name") or ""
            if not wk or not un:
                return []
            view = SubscribeView(website_key=wk, url_name=un)
            return list(view.children)

        paginator = Paginator(
            embeds,
            invoker_id=interaction.user.id,
            items_factory=_subscribe_items,
        )
        await interaction.followup.send(embed=embeds[0], view=paginator)

    # -- /info -----------------------------------------------------------

    @app_commands.command(name="info", description="Fetch details for a manga / manhwa series")
    @app_commands.describe(series_id="Autocomplete value or direct series URL")
    @app_commands.autocomplete(series_id=autocomplete.tracked_manga_in_guild)
    @has_premium(dm_only=True)
    async def info(
        self,
        interaction: discord.Interaction,
        series_id: str,
    ) -> None:
        await interaction.response.defer(thinking=True)

        resolved = _resolve_series_id(series_id)
        if resolved is None:
            await interaction.followup.send(
                embed=_error_embed(
                    "Couldn't parse that series ID. Use the autocomplete or paste a series URL."
                ),
                ephemeral=True,
            )
            return

        website_key, identifier = resolved
        try:
            data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                "info", website_key=website_key, url=identifier
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await interaction.followup.send(embed=_error_embed(str(exc)), ephemeral=True)
            return

        if not data:
            await interaction.followup.send(
                embed=_error_embed("No data returned for that series."), ephemeral=True
            )
            return

        request_id = data.get("request_id") or "n/a"
        embed = series_info_embed(data, request_id=request_id)

        url_name = data.get("url_name") or identifier
        view = SubscribeView(
            website_key=website_key,
            url_name=url_name,
            show_track_button=True,
        )
        await interaction.followup.send(embed=embed, view=view)

    # -- /chapters -------------------------------------------------------

    @app_commands.command(name="chapters", description="List chapters for a tracked series")
    @app_commands.describe(series_id="Autocomplete value or direct series URL")
    @app_commands.autocomplete(series_id=autocomplete.tracked_manga_in_guild)
    @has_premium(dm_only=True)
    async def chapters(
        self,
        interaction: discord.Interaction,
        series_id: str,
    ) -> None:
        await interaction.response.defer(thinking=True)

        resolved = _resolve_series_id(series_id)
        if resolved is None:
            await interaction.followup.send(
                embed=_error_embed("Couldn't parse that series ID."),
                ephemeral=True,
            )
            return

        website_key, identifier = resolved
        try:
            data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                "chapters", website_key=website_key, url=identifier
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await interaction.followup.send(embed=_error_embed(str(exc)), ephemeral=True)
            return

        chapter_list: list[dict] = data.get("chapters") or []
        series_title = data.get("title") or identifier

        embeds = chapter_list_embeds(chapter_list, title=f"Chapters — {series_title}")

        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0])
        else:
            paginator = Paginator(embeds, invoker_id=interaction.user.id)
            await interaction.followup.send(embed=embeds[0], view=paginator)

    # -- /supported_websites --------------------------------------------

    @app_commands.command(
        name="supported_websites",
        description="List all websites the crawler supports",
    )
    async def supported_websites(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)

        bot = self.bot  # type: ignore[attr-defined]
        ttl = bot.config.supported_websites_cache.ttl_seconds

        async def _loader() -> list[dict]:
            d = await bot.crawler.request("supported_websites")
            return d.get("websites") or []

        try:
            websites: list[dict] = await bot.websites_cache.get_or_set(
                "websites_full", _loader, ttl
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await interaction.followup.send(embed=_error_embed(str(exc)), ephemeral=True)
            return

        embeds = supported_websites_embeds(websites)

        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0])
        else:
            paginator = Paginator(embeds, invoker_id=interaction.user.id)
            await interaction.followup.send(embed=embeds[0], view=paginator)


# -- helpers -------------------------------------------------------------


def _resolve_series_id(series_id: str) -> tuple[str, str] | None:
    """Parse a series_id string into ``(website_key, identifier)``.

    Supported formats:
    - ``"website_key:url_name"``   — from tracked_manga_in_guild autocomplete
    - ``"website_key|series_url"`` — from track_new_url_or_search autocomplete
    - direct ``https://…`` URL     — not parseable without website_key; returns None
    """
    if not series_id:
        return None

    # "website_key|series_url" from search-as-you-type autocomplete
    if "|" in series_id and not series_id.startswith("http"):
        parts = series_id.split("|", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])

    # "website_key:url_name" from tracked_manga_in_guild autocomplete
    # Exclude http:// and https:// so we don't split on the colon in URLs.
    if ":" in series_id and not series_id.startswith("http"):
        parts = series_id.split(":", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])

    return None


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(
        title="Error",
        description=message,
        colour=discord.Colour.red(),
    )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CatalogCog(bot))
