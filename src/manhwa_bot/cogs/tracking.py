"""Tracking cog — /track new|update|remove|list."""

from __future__ import annotations

import logging
from itertools import groupby

import discord
from discord import app_commands
from discord.ext import commands

from .. import autocomplete
from ..checks import has_premium
from ..crawler.errors import CrawlerError, Disconnected, RequestTimeout
from ..db.guild_settings import GuildSettingsStore
from ..db.tracked import TrackedStore
from ..ui.paginator import Paginator

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
        description="Manage tracked manga",
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )

    # -- /track new ---------------------------------------------------------

    @track.command(name="new", description="Start tracking a manga in this guild")
    @app_commands.describe(
        manga_url="Search or paste a URL (use autocomplete for best results)",
        ping_role="Role to mention when a new chapter drops (optional)",
    )
    @app_commands.autocomplete(manga_url=autocomplete.track_new_url_or_search)
    @has_premium(dm_only=True)
    async def track_new(
        self,
        interaction: discord.Interaction,
        manga_url: str,
        ping_role: discord.Role | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=False)

        parsed = _parse_new_url(manga_url)
        if parsed is None:
            await interaction.followup.send(
                embed=_error_embed(
                    "Couldn't parse that URL.\n"
                    "Use the autocomplete to search by title, or paste a value in "
                    "`website_key|https://...` format."
                ),
                ephemeral=True,
            )
            return

        website_key, series_url = parsed
        try:
            data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                "track_series", website_key=website_key, series_url=series_url
            )
        except CrawlerError as exc:
            friendly = _FRIENDLY_ERRORS.get(exc.code, f"Crawler error: {exc.message}")
            await interaction.followup.send(embed=_error_embed(friendly), ephemeral=True)
            return
        except (RequestTimeout, Disconnected) as exc:
            await interaction.followup.send(embed=_error_embed(str(exc)), ephemeral=True)
            return

        website_key = data["website_key"]
        url_name = data["url_name"]
        series_url = data["series_url"]
        series_data: dict = data.get("series") or {}
        title: str = series_data.get("title") or url_name
        status: str | None = series_data.get("status")

        guild_id = interaction.guild_id  # type: ignore[union-attr]

        await self._tracked.upsert_series(
            website_key, url_name, series_url, title, cover_url=None, status=status
        )
        await self._tracked.add_to_guild(
            guild_id, website_key, url_name, ping_role.id if ping_role else None
        )

        gs = await self._guild_settings.get(guild_id)

        embed = discord.Embed(
            title=f"Now tracking: {title}",
            url=series_url,
            colour=discord.Colour.green(),
        )
        if status:
            embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Website", value=website_key, inline=True)
        embed.add_field(
            name="Ping role",
            value=ping_role.mention if ping_role else "None",
            inline=True,
        )
        if gs and gs.notifications_channel_id:
            embed.set_footer(
                text=f"Updates → #{interaction.guild.get_channel(gs.notifications_channel_id) or gs.notifications_channel_id}"
            )  # type: ignore[union-attr]
        else:
            embed.set_footer(text="Set a notifications channel with /settings")

        await interaction.followup.send(embed=embed)

    # -- /track update ------------------------------------------------------

    @track.command(name="update", description="Change the ping role for a tracked manga")
    @app_commands.describe(
        manga_id="Manga to update (use autocomplete)",
        role="New ping role — leave empty to remove the current role",
    )
    @app_commands.autocomplete(manga_id=autocomplete.tracked_manga_in_guild)
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
                embed=_error_embed("Couldn't parse that manga ID. Use the autocomplete."),
                ephemeral=True,
            )
            return

        website_key, url_name = parsed
        guild_id = interaction.guild_id  # type: ignore[union-attr]

        await self._tracked.update_ping_role(
            guild_id, website_key, url_name, role.id if role else None
        )

        series = await self._tracked.find(website_key, url_name)
        title = series.title if series else f"{website_key}:{url_name}"
        role_text = role.mention if role else "*removed*"

        embed = discord.Embed(
            title="Ping role updated",
            description=f"**{title}** ping role → {role_text}",
            colour=discord.Colour.blurple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # -- /track remove ------------------------------------------------------

    @track.command(name="remove", description="Stop tracking a manga in this guild")
    @app_commands.describe(
        manga_id="Manga to untrack (use autocomplete)",
        delete_role="Also delete the manga's ping role from this server",
    )
    @app_commands.autocomplete(manga_id=autocomplete.tracked_manga_in_guild)
    @has_premium(dm_only=True)
    async def track_remove(
        self,
        interaction: discord.Interaction,
        manga_id: str,
        delete_role: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=False)

        parsed = _parse_manga_id(manga_id)
        if parsed is None:
            await interaction.followup.send(
                embed=_error_embed("Couldn't parse that manga ID. Use the autocomplete."),
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
                await self.bot.crawler.request(  # type: ignore[attr-defined]
                    "untrack_series", website_key=website_key, url_name=url_name
                )
                crawler_untracked = True
            except (CrawlerError, RequestTimeout, Disconnected):
                _log.exception(
                    "untrack_series call failed for %s:%s — series removed from bot DB anyway",
                    website_key,
                    url_name,
                )
            await self._tracked.delete_series(website_key, url_name)

        role_deleted = False
        if delete_role and captured_role_id:
            role_obj = (
                interaction.guild.get_role(captured_role_id)  # type: ignore[union-attr]
                if interaction.guild
                else None
            )
            if role_obj is None:
                try:
                    role_obj = await interaction.guild.fetch_roles()  # type: ignore[union-attr]
                    role_obj = next((r for r in role_obj if r.id == captured_role_id), None)
                except discord.HTTPException:
                    role_obj = None
            if role_obj is not None:
                try:
                    await role_obj.delete(reason=f"Deleted with /track remove for {title}")
                    role_deleted = True
                except discord.HTTPException:
                    _log.warning("failed to delete ping role %s for %s", captured_role_id, title)

        embed = discord.Embed(
            title=f"Untracked: {title}",
            colour=discord.Colour.orange(),
        )
        if was_last:
            embed.add_field(
                name="Crawler untracked",
                value="Yes — no other guilds track this series."
                if crawler_untracked
                else "Attempted (error — see logs)",
                inline=False,
            )
        if delete_role:
            embed.add_field(
                name="Role deleted",
                value="Yes"
                if role_deleted
                else ("No role assigned" if not captured_role_id else "Failed (see logs)"),
                inline=True,
            )

        await interaction.followup.send(embed=embed)

    # -- /track list --------------------------------------------------------

    @track.command(name="list", description="List all tracked manga in this guild")
    @has_premium(dm_only=True)
    async def track_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=False)

        guild_id = interaction.guild_id  # type: ignore[union-attr]
        rows = await self._tracked.list_for_guild(guild_id, limit=_LIST_FETCH_LIMIT)

        if not rows:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="No manga tracked",
                    description="This guild isn't tracking any manga yet. Use `/track new` to start.",
                    colour=discord.Colour.greyple(),
                )
            )
            return

        guild_name = interaction.guild.name if interaction.guild else "this guild"  # type: ignore[union-attr]
        embeds = _build_list_embeds(rows, guild_name=guild_name)

        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0])
        else:
            paginator = Paginator(embeds, invoker_id=interaction.user.id)
            await interaction.followup.send(embed=embeds[0], view=paginator)


# -- module helpers ---------------------------------------------------------


def _parse_new_url(manga_url: str) -> tuple[str, str] | None:
    """Parse an autocomplete value for /track new.

    Accepts ``"website_key|https://..."`` (search result format).
    Rejects bare ``https://`` URLs — website_key cannot be inferred.
    """
    if not manga_url:
        return None
    if "|" in manga_url and not manga_url.startswith("http"):
        parts = manga_url.split("|", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])
    return None


def _parse_manga_id(manga_id: str) -> tuple[str, str] | None:
    """Parse ``"website_key:url_name"`` → ``(website_key, url_name)``, or None."""
    if ":" in manga_id and not manga_id.startswith("http"):
        parts = manga_id.split(":", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])
    return None


def _build_list_embeds(rows: list, *, guild_name: str) -> list[discord.Embed]:
    """Build paginated embeds from a list of GuildTrackedSeries, grouped by website_key."""
    total = len(rows)
    # Sort by website_key then title (list_for_guild already orders by title, re-sort for grouping).
    sorted_rows = sorted(rows, key=lambda r: (r.website_key, r.title.lower()))

    lines: list[str] = []
    for website_key, group in groupby(sorted_rows, key=lambda r: r.website_key):
        lines.append(f"**{website_key}**")
        for row in group:
            role_part = f" — <@&{row.ping_role_id}>" if row.ping_role_id else ""
            lines.append(f"• [{row.title}]({row.series_url}){role_part}")

    pages: list[discord.Embed] = []
    total_pages = max(1, (len(lines) + _LIST_PAGE_SIZE - 1) // _LIST_PAGE_SIZE)
    for i in range(0, len(lines), _LIST_PAGE_SIZE):
        chunk = lines[i : i + _LIST_PAGE_SIZE]
        page_num = i // _LIST_PAGE_SIZE + 1
        embed = discord.Embed(
            title=f"Tracked manga — {guild_name}",
            description="\n".join(chunk),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text=f"Page {page_num}/{total_pages} • {total} series total")
        pages.append(embed)
    return pages


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(title="Error", description=message, colour=discord.Colour.red())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrackingCog(bot))
