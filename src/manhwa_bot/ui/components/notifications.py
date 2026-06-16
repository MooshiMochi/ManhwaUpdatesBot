"""Chapter update push-notification LayoutView factory."""

from __future__ import annotations

import discord

from ...crawler.chapter import Chapter
from .base import (
    BaseLayoutView,
    chapter_markdown,
    hero_cover_gallery,
    small_separator,
)
from .notification_buttons import (
    ALL_UPDATE_BUTTONS,
    UPDATE_BUTTON_KEYS,
    UPDATE_BUTTON_LABELS,
    BookmarkButton,
    LastReadChapterButton,
    MarkReadButton,
    SubscribeToggleButton,
)


def build_chapter_update_view(
    payload: dict,
    *,
    bot: discord.Client | None = None,
    allowed_buttons: frozenset[str] = ALL_UPDATE_BUTTONS,
    ping: str | None = None,
    spoiler: bool = False,
) -> discord.ui.LayoutView:
    """Build a fresh push-notification LayoutView for a new chapter.

    Must be called per delivery — views can't be shared across messages. The
    view has `timeout=None` so interactive buttons survive bot restarts
    (callbacks are routed through `DynamicItem` classes registered in
    `ManhwaBot.setup_hook`).
    """
    series_title = payload.get("series_title") or payload.get("url_name") or "New chapter"
    series_url = payload.get("series_url") or None
    raw_chapter = payload.get("chapter") or {}
    chapter = raw_chapter if isinstance(raw_chapter, Chapter) else Chapter.from_dict(raw_chapter)
    is_premium = chapter.is_premium
    cover_url = payload.get("cover_url")
    website_key = str(payload.get("website_key") or "")
    url_name = str(payload.get("url_name") or "")

    glyph = "🥇" if is_premium else "📖"
    header = (
        f"## {glyph}  [{series_title}]({series_url})"
        if series_url
        else f"## {glyph}  {series_title}"
    )
    chapter_display = chapter_markdown(chapter)
    body = f"**New chapter:** {chapter_display}"

    container = discord.ui.Container()  # no accent_colour
    gallery = hero_cover_gallery(cover_url, spoiler=spoiler)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(header))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(body))

    button_row = _build_button_row(
        allowed_buttons=allowed_buttons,
        website_key=website_key,
        url_name=url_name,
        chapter=chapter,
    )
    if button_row is not None:
        container.add_item(small_separator())
        container.add_item(button_row)

    del bot
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    ping = (ping or "").strip()
    if ping:
        view.add_item(discord.ui.TextDisplay(ping))
    view.add_item(container)
    return view


def build_status_change_view(
    payload: dict,
    *,
    bot: discord.Client | None = None,
    ping: str | None = None,
    spoiler: bool = False,
) -> discord.ui.LayoutView:
    series_title = payload.get("series_title") or payload.get("url_name") or "Series"
    series_url = payload.get("series_url") or None
    old_status = str(payload.get("old_status") or "Unknown")
    new_status = str(payload.get("new_status") or payload.get("status") or "Unknown")
    cover_url = payload.get("cover_url")

    header = f"## 🔔  [{series_title}]({series_url})" if series_url else f"## 🔔  {series_title}"
    body = f"**Status changed:** `{old_status}` → `{new_status}`"
    if bool(payload.get("terminal")):
        body += "\n\nTracking has ended for this series."

    container = discord.ui.Container()
    gallery = hero_cover_gallery(cover_url)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(header))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(body))

    del bot
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    ping = (ping or "").strip()
    if ping:
        view.add_item(discord.ui.TextDisplay(ping))
    view.add_item(container)
    return view


def _build_button_row(
    *,
    allowed_buttons: frozenset[str],
    website_key: str,
    url_name: str,
    chapter: Chapter,
) -> discord.ui.ActionRow | None:
    if not allowed_buttons or not website_key or not url_name:
        return None

    row = discord.ui.ActionRow()

    # Iterate in canonical order so the visual layout is stable.
    # We add the inner .item (the plain Button) rather than the DynamicItem
    # wrapper so that walk_children() yields Button instances that tests can
    # inspect directly. Dispatch still works because the DynamicItem templates
    # are registered globally in ManhwaBot.setup_hook and matched by custom_id.
    chapter_index = chapter.index if chapter.index is not None else -1
    ordered_keys = ("open_chapter", *(key for key in UPDATE_BUTTON_KEYS if key != "open_chapter"))
    for key in ordered_keys:
        if key not in allowed_buttons:
            continue
        if key == "mark_read":
            row.add_item(MarkReadButton(website_key, url_name, chapter_index).item)
        elif key == "bookmark":
            row.add_item(BookmarkButton(website_key, url_name).item)
        elif key == "subscribe":
            row.add_item(SubscribeToggleButton(website_key, url_name).item)
        elif key == "open_chapter":
            row.add_item(LastReadChapterButton(website_key, url_name).item)

    if len(list(row.children)) == 0:
        return None
    return row


__all__ = [
    "ALL_UPDATE_BUTTONS",
    "UPDATE_BUTTON_KEYS",
    "UPDATE_BUTTON_LABELS",
    "build_chapter_update_view",
    "build_status_change_view",
]
