"""Bookmarks cog — /bookmark new|view|update|delete."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .. import autocomplete
from ..checks import has_premium
from ..crawler.errors import CrawlerError, Disconnected, RequestTimeout
from ..db.bookmarks import BookmarkStore
from ..db.subscriptions import SubscriptionStore
from ..db.tracked import TrackedStore
from ..ui.bookmark_view import BOOKMARK_FOLDERS, BookmarkView

_log = logging.getLogger(__name__)

_DEFAULT_FOLDER = "Reading"
_COMPLETED_STATUSES = {"completed", "ended", "finished", "dropped", "cancelled"}

_FOLDER_CHOICES = [app_commands.Choice(name=f, value=f) for f in BOOKMARK_FOLDERS]


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


def _chapter_label(ch: dict, fallback_idx: int) -> str:
    return ch.get("chapter") or ch.get("chapter_number") or f"#{ch.get('index', fallback_idx)}"


class BookmarksCog(commands.Cog, name="Bookmarks"):
    bookmark = app_commands.Group(name="bookmark", description="Track your reading progress")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._bookmarks = BookmarkStore(bot.db)  # type: ignore[attr-defined]
        self._tracked = TrackedStore(bot.db)  # type: ignore[attr-defined]
        self._subs = SubscriptionStore(bot.db)  # type: ignore[attr-defined]

    # -- internal helpers -----------------------------------------------

    async def _resolve_series(self, manga_url_or_id: str) -> tuple[str, str, str] | None:
        """Return ``(website_key, url_name, series_url)`` or None.

        Tries the autocomplete value format first, then falls back to a
        crawler ``info`` lookup when given a raw URL.
        """
        parsed = _split_series_id(manga_url_or_id)
        if parsed is not None:
            website_key, url_name = parsed
            tracked = await self._tracked.find(website_key, url_name)
            if tracked is not None:
                return (website_key, url_name, tracked.series_url)
            # Not yet tracked; canonicalize via the crawler so we know the
            # series_url (used by /bookmark new for the chapters call).
            try:
                data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                    "info", website_key=website_key, url=url_name
                )
            except (CrawlerError, RequestTimeout, Disconnected):
                return None
            series_url = data.get("series_url") or url_name
            return (website_key, url_name, series_url)

        # Fallback: treat as a URL.
        if manga_url_or_id.startswith("http"):
            try:
                data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                    "info", url=manga_url_or_id
                )
            except (CrawlerError, RequestTimeout, Disconnected):
                return None
            wk = data.get("website_key")
            un = data.get("url_name")
            su = data.get("series_url") or manga_url_or_id
            if not wk or not un:
                return None
            return (wk, un, su)
        return None

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

    @bookmark.command(name="new", description="Bookmark a manga")
    @app_commands.describe(
        manga_url_or_id="A tracked-manga autocomplete value or a series URL",
        folder="Which folder to put it in (default: Reading)",
    )
    @app_commands.autocomplete(manga_url_or_id=autocomplete.tracked_manga_in_guild)
    @app_commands.choices(folder=_FOLDER_CHOICES)
    @has_premium(dm_only=True)
    async def bookmark_new(
        self,
        interaction: discord.Interaction,
        manga_url_or_id: str,
        folder: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)

        folder_value = folder.value if folder else _DEFAULT_FOLDER
        if folder_value not in BOOKMARK_FOLDERS:
            await interaction.followup.send(embed=_error_embed("Unknown folder."), ephemeral=True)
            return

        resolved = await self._resolve_series(manga_url_or_id)
        if resolved is None:
            await interaction.followup.send(
                embed=_error_embed(
                    "Couldn't resolve that series. Use the autocomplete or paste a series URL."
                ),
                ephemeral=True,
            )
            return
        website_key, url_name, series_url = resolved

        try:
            data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                "chapters", website_key=website_key, url=series_url or url_name
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await interaction.followup.send(
                embed=_error_embed(f"Couldn't fetch chapters: {exc}"), ephemeral=True
            )
            return

        chapters: list[dict] = data.get("chapters") or []
        if not chapters:
            await interaction.followup.send(
                embed=_error_embed("No chapters available for this series."),
                ephemeral=True,
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

        title = data.get("title") or url_name
        embed = _ok_embed(
            "Bookmark added",
            f"**{title}**\nFolder: `{folder_value}`\nLast read set to `{first_label}`.",
        )
        await interaction.followup.send(embed=embed)

    # -- /bookmark view -------------------------------------------------

    @bookmark.command(name="view", description="Browse your bookmarks")
    @app_commands.describe(
        series_id="Jump to a specific bookmark (optional)",
        folder="Filter to a folder (optional)",
    )
    @app_commands.autocomplete(series_id=autocomplete.user_bookmarks)
    @app_commands.choices(folder=_FOLDER_CHOICES)
    @has_premium(dm_only=True)
    async def bookmark_view(
        self,
        interaction: discord.Interaction,
        series_id: str | None = None,
        folder: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)

        folder_value = folder.value if folder else None
        bookmarks = await self._bookmarks.list_user_bookmarks(
            interaction.user.id, folder=folder_value, limit=500
        )

        # Drop entries whose website is no longer supported.
        supported = await self._supported_websites_keys()
        if supported:
            bookmarks = [b for b in bookmarks if b.website_key in supported]

        if not bookmarks:
            label = folder_value or "any folder"
            await interaction.followup.send(
                embed=discord.Embed(
                    title="No bookmarks",
                    description=f"You don't have any bookmarks in **{label}**.",
                    colour=discord.Colour.greyple(),
                )
            )
            return

        # Optional jump-to.
        jump_index = 0
        if series_id:
            parsed = _split_series_id(series_id)
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
            current_folder=folder_value,
            index=jump_index,
        )
        embed = await view.initial_embed()
        await interaction.followup.send(embed=embed, view=view)

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

    @bookmark.command(name="update", description="Update a bookmark's chapter or folder")
    @app_commands.describe(
        series_id="The bookmark to update",
        chapter_index="0-based index into the chapter list",
        folder="Move the bookmark to a different folder",
    )
    @app_commands.autocomplete(series_id=autocomplete.user_bookmarks)
    @app_commands.choices(folder=_FOLDER_CHOICES)
    @has_premium(dm_only=True)
    async def bookmark_update(
        self,
        interaction: discord.Interaction,
        series_id: str,
        chapter_index: int | None = None,
        folder: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)

        if chapter_index is None and folder is None:
            await interaction.followup.send(
                embed=_error_embed("Specify at least one of `chapter_index` or `folder`."),
                ephemeral=True,
            )
            return

        parsed = _split_series_id(series_id)
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

        notes: list[str] = []

        if chapter_index is not None:
            tracked = await self._tracked.find(website_key, url_name)
            identifier = tracked.series_url if tracked else url_name
            try:
                data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                    "chapters", website_key=website_key, url=identifier
                )
            except (CrawlerError, RequestTimeout, Disconnected) as exc:
                await interaction.followup.send(
                    embed=_error_embed(f"Couldn't fetch chapters: {exc}"),
                    ephemeral=True,
                )
                return
            chapters: list[dict] = data.get("chapters") or []
            if not chapters:
                await interaction.followup.send(
                    embed=_error_embed("No chapters available for this series."),
                    ephemeral=True,
                )
                return
            if not (0 <= chapter_index < len(chapters)):
                await interaction.followup.send(
                    embed=_error_embed(f"Chapter index out of range (0 - {len(chapters) - 1})."),
                    ephemeral=True,
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
            notes.append(f"Last read → `{label}` (index {chapter_index}).")

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
                notes.append(suffix)

        if folder is not None:
            await self._bookmarks.update_folder(
                interaction.user.id, website_key, url_name, folder.value
            )
            notes.append(f"Folder → `{folder.value}`.")

        await interaction.followup.send(embed=_ok_embed("Bookmark updated", "\n".join(notes)))

    # -- /bookmark delete -----------------------------------------------

    @bookmark.command(name="delete", description="Delete a bookmark")
    @app_commands.describe(series_id="The bookmark to delete")
    @app_commands.autocomplete(series_id=autocomplete.user_bookmarks)
    @has_premium(dm_only=True)
    async def bookmark_delete(
        self,
        interaction: discord.Interaction,
        series_id: str,
    ) -> None:
        await interaction.response.defer(thinking=True)

        parsed = _split_series_id(series_id)
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
        await interaction.followup.send(
            embed=discord.Embed(
                title="Bookmark deleted",
                description=f"`{website_key}:{url_name}`",
                colour=discord.Colour.orange(),
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BookmarksCog(bot))
