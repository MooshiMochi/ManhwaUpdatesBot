"""Series-info layouts: /info hero card + /search result cards.

Also exposes ``SeriesActionRow`` — the Subscribe / Track / Bookmark / More-Info
buttons appended to series cards. Replaces the legacy ``SubscribeView``.
"""

from __future__ import annotations

import logging

import discord

from ...db.bookmarks import BookmarkStore
from ...db.subscriptions import SubscriptionStore
from ...db.tracked import TrackedStore
from .. import emojis
from .base import (
    SYNOPSIS_MAX,
    BaseLayoutView,
    footer_section,
    hero_cover_gallery,
    large_separator,
    safe_truncate,
    small_separator,
    status_accent,
)

_log = logging.getLogger(__name__)


class SeriesActionRow(discord.ui.ActionRow):
    """Row with Subscribe / More-Info / Bookmark buttons for a series card."""

    def __init__(
        self,
        *,
        website_key: str,
        url_name: str,
        series_url: str | None = None,
        show_info_button: bool = False,
        show_bookmark_button: bool = False,
    ) -> None:
        super().__init__()
        self._website_key = website_key
        self._url_name = url_name
        self._series_url = series_url

        sub_btn = discord.ui.Button(
            label="Track and Subscribe",
            style=discord.ButtonStyle.blurple,
            emoji="📚",
        )
        sub_btn.callback = self._on_subscribe  # type: ignore[assignment]
        self.add_item(sub_btn)

        if show_info_button:
            info_btn = discord.ui.Button(
                label="More Info",
                style=discord.ButtonStyle.blurple,
                emoji="🔍",
            )
            info_btn.callback = self._on_more_info  # type: ignore[assignment]
            self.add_item(info_btn)

        if show_bookmark_button:
            bm_btn = discord.ui.Button(
                label="Bookmark",
                style=discord.ButtonStyle.blurple,
                emoji="🔖",
            )
            bm_btn.callback = self._on_bookmark  # type: ignore[assignment]
            self.add_item(bm_btn)

    async def _on_subscribe(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Subscriptions are server-specific. Run this in a server.",
                ephemeral=True,
            )
            return

        bot: discord.Client = interaction.client
        sub_store = SubscriptionStore(bot.db)  # type: ignore[attr-defined]
        tracked_store = TrackedStore(bot.db)  # type: ignore[attr-defined]

        tracked = await tracked_store.find(self._website_key, self._url_name)
        if tracked is None:
            await interaction.response.send_message(
                "This series isn't tracked in any server yet — ask an admin to `/track new` first.",
                ephemeral=True,
            )
            return

        try:
            await sub_store.subscribe(
                interaction.user.id,
                interaction.guild.id,
                self._website_key,
                self._url_name,
            )
        except Exception:
            _log.exception(
                "subscribe button failed for %s:%s",
                self._website_key,
                self._url_name,
            )
            await interaction.response.send_message(
                "Failed to subscribe — please try again.", ephemeral=True
            )
            return

        link = (
            f"[{tracked.title}]({tracked.series_url})"
            if tracked.series_url
            else f"**{tracked.title}**"
        )
        await interaction.response.send_message(
            f"{emojis.CHECK} Subscribed to {link}! "
            "You'll receive notifications when new chapters drop.",
            ephemeral=True,
        )

    async def _on_bookmark(self, interaction: discord.Interaction) -> None:
        bot: discord.Client = interaction.client
        bookmark_store = BookmarkStore(bot.db)  # type: ignore[attr-defined]

        existing = await bookmark_store.get_bookmark(
            interaction.user.id, self._website_key, self._url_name
        )
        if existing is not None:
            await interaction.response.send_message(
                "You already have a bookmark for this series — use `/bookmark view`.",
                ephemeral=True,
            )
            return

        try:
            await bookmark_store.upsert_bookmark(
                interaction.user.id,
                self._website_key,
                self._url_name,
                folder="Reading",
                last_read_chapter="—",
                last_read_index=0,
            )
        except Exception:
            _log.exception(
                "bookmark button failed for %s:%s",
                self._website_key,
                self._url_name,
            )
            await interaction.response.send_message(
                "Failed to bookmark — please try again.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🔖 Bookmark added to **Reading**. Use `/bookmark update` to set a chapter.",
            ephemeral=True,
        )

    async def _on_more_info(self, interaction: discord.Interaction) -> None:
        url = self._series_url or self._url_name
        await interaction.response.send_message(
            f"Run `/info series:{url}` for the full details.",
            ephemeral=True,
        )


def _chapter_label(ch: object) -> str:
    if isinstance(ch, dict):
        return str(ch.get("name") or ch.get("chapter") or ch.get("text") or "?")
    return str(ch)


def build_info_view(
    data: dict,
    *,
    site_meta: dict | None = None,
    request_id: str | None = None,
    action_row: SeriesActionRow | None = None,
    bot: discord.Client | None = None,
    invoker_id: int | None = None,
) -> discord.ui.LayoutView:
    """Hero `/info` view — cover MediaGallery, title, synopsis, metadata, action row."""
    site_meta = site_meta or {}
    title = data.get("title") or "Unknown title"
    series_url = data.get("series_url") or data.get("url") or None
    cover_url = data.get("cover_url") or data.get("cover") or None
    website_key = data.get("website_key") or ""
    status = data.get("status") or "Unknown"
    synopsis = (data.get("synopsis") or "").strip()
    chapters = data.get("chapters") or data.get("latest_chapters") or []
    chapter_count = data.get("chapter_count")
    if chapter_count is None:
        chapter_count = len(chapters) if chapters else 0

    genres: list = data.get("genres") or []
    authors: list = data.get("authors") or data.get("author") or []
    if isinstance(authors, str):
        authors = [authors]

    scanlator_label = site_meta.get("name") or (website_key.title() if website_key else "")
    base_url = site_meta.get("base_url") or None
    scanlator_link = (
        f"[{scanlator_label}]({base_url})"
        if scanlator_label and base_url
        else (scanlator_label or "Unknown")
    )

    latest = _chapter_label(chapters[0]) if chapters else "N/A"
    first = _chapter_label(chapters[-1]) if chapters else "N/A"

    header_block = f"# [{title}]({series_url})" if series_url else f"# {title}"
    sub_parts: list[str] = []
    if scanlator_label:
        sub_parts.append(f"**Scanlator:** {scanlator_link}")
    sub_parts.append(f"**Status:** `{status}`")
    if genres:
        genre_text = ", ".join(str(g) for g in genres[:8])
        sub_parts.append(f"**Genres:** {genre_text}")
    if authors:
        sub_parts.append(f"**Authors:** {', '.join(str(a) for a in authors[:4])}")
    sub_line = " • ".join(sub_parts)

    synopsis_block = (
        safe_truncate(synopsis, SYNOPSIS_MAX) if synopsis else "*No synopsis available.*"
    )
    if series_url and len(synopsis) > SYNOPSIS_MAX:
        synopsis_block = synopsis_block.rstrip("…").rstrip() + f" [(read more)]({series_url})"

    details_block = (
        f"**Number of Chapters:** {chapter_count}\n"
        f"**Latest Chapter:** {latest}\n"
        f"**First Chapter:** {first}"
    )

    container = discord.ui.Container(accent_colour=status_accent(status))
    gallery = hero_cover_gallery(cover_url)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(header_block))
    if sub_line:
        container.add_item(discord.ui.TextDisplay(sub_line))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(f"**Synopsis**\n{synopsis_block}"))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(details_block))
    container.add_item(small_separator())
    extra = f"req: {request_id}" if request_id else None
    container.add_item(footer_section(bot, extra=extra))

    view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
    view.add_item(container)
    if action_row is not None:
        view.add_item(action_row)
    return view


def build_search_result_view(
    item: dict,
    *,
    site_meta: dict | None = None,
    page: int,
    total_pages: int,
    failed_websites: list[str] | None = None,
    action_row: SeriesActionRow | None = None,
    bot: discord.Client | None = None,
    invoker_id: int | None = None,
) -> discord.ui.LayoutView:
    """One result per page (image-forward). Used by /search pagination."""
    site_meta = site_meta or {}
    title = str(item.get("title") or "Unknown")
    series_url = item.get("series_url") or item.get("url") or None
    cover_url = item.get("cover_url") or item.get("cover") or None
    website_key = str(item.get("website_key") or "")
    status = item.get("status") or ""

    scanlator_label = site_meta.get("name") or (website_key.title() if website_key else "")
    base_url = site_meta.get("base_url") or None
    scanlator_link = (
        f"[{scanlator_label}]({base_url})"
        if scanlator_label and base_url
        else (scanlator_label or "")
    )

    header_block = f"# [{title}]({series_url})" if series_url else f"# {title}"
    sub_parts: list[str] = []
    if scanlator_link:
        sub_parts.append(f"**Scanlator:** {scanlator_link}")
    if status:
        sub_parts.append(f"**Status:** `{status}`")
    sub_line = " • ".join(sub_parts)

    container = discord.ui.Container(accent_colour=status_accent(str(status)))
    gallery = hero_cover_gallery(cover_url)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(header_block))
    if sub_line:
        container.add_item(discord.ui.TextDisplay(sub_line))
    if failed_websites:
        container.add_item(small_separator())
        container.add_item(
            discord.ui.TextDisplay(
                f"{emojis.WARNING} **Failed websites:** {', '.join(failed_websites)}"
            )
        )
    container.add_item(small_separator())
    container.add_item(footer_section(bot, extra=f"Result {page}/{total_pages}"))

    view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
    view.add_item(container)
    if action_row is not None:
        view.add_item(action_row)
    return view


def build_no_results_view(
    *,
    query: str,
    failed_websites: list[str] | None = None,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Empty-state view for /search when no results were returned."""
    body = f"No results for **{safe_truncate(query, 200)}**."
    container = discord.ui.Container(
        discord.ui.TextDisplay("## 🔎  No results"),
        small_separator(),
        discord.ui.TextDisplay(body),
        accent_colour=discord.Colour.red(),
    )
    if failed_websites:
        container.add_item(small_separator())
        container.add_item(
            discord.ui.TextDisplay(
                f"{emojis.WARNING} **Failed websites:** {', '.join(failed_websites)}"
            )
        )
    container.add_item(large_separator())
    container.add_item(footer_section(bot))
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view
