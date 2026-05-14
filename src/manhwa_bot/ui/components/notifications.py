"""Chapter update push-notification LayoutView factory."""

from __future__ import annotations

import discord

from .base import (
    BaseLayoutView,
    chapter_is_premium,
    chapter_markdown,
    footer_section,
    hero_cover_gallery,
    small_separator,
)


def build_chapter_update_view(
    payload: dict,
    *,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Build a fresh push-notification LayoutView for a new chapter.

    Must be called per delivery — views can't be shared across messages.
    """
    series_title = payload.get("series_title") or payload.get("url_name") or "New chapter"
    series_url = payload.get("series_url") or None
    chapter = payload.get("chapter") or {}
    is_premium = chapter_is_premium(chapter)
    cover_url = payload.get("cover_url")
    website_key = payload.get("website_key")

    accent = discord.Colour.gold() if is_premium else discord.Colour.green()
    glyph = "🥇" if is_premium else "📖"

    header = (
        f"## {glyph}  [{series_title}]({series_url})"
        if series_url
        else f"## {glyph}  {series_title}"
    )
    chapter_display = chapter_markdown(chapter, chapter.get("index"))
    body = f"**New chapter:** {chapter_display}"

    container = discord.ui.Container(accent_colour=accent)
    gallery = hero_cover_gallery(cover_url)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(header))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(body))
    container.add_item(small_separator())
    container.add_item(footer_section(bot, extra=str(website_key) if website_key else None))

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view
