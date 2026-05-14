"""Tracking + subscription LayoutView factories.

Includes the shared "scanlator-grouped numbered list" pagination used by both
``/track list`` and ``/subscribe list`` so we don't duplicate the layout
formatter.
"""

from __future__ import annotations

from collections.abc import Sequence

import discord

from .. import emojis
from .base import (
    LIST_MAX,
    TEXT_MAX,
    BaseLayoutView,
    chapter_markdown,
    footer_section,
    hero_cover_gallery,
    large_separator,
    safe_truncate,
    small_separator,
)

# ---------------------------------------------------------------------------
# /track new — hero success view
# ---------------------------------------------------------------------------


def build_tracking_success_view(
    *,
    title: str,
    series_url: str,
    ping_role: discord.Role | None,
    notif_channel: discord.abc.GuildChannel | discord.Thread | None,
    cover_url: str | None,
    is_dm: bool,
    warning: str | None = None,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Hero image-forward 'Tracking Successful' view."""
    if is_dm:
        body = (
            f"Successfully tracked **[{title}]({series_url})**!\n"
            "Please make sure your DMs are open to receive notifications."
        )
    else:
        if ping_role is not None:
            head = f"Tracking **[{title}]({series_url})** ({ping_role.mention}) is now active."
        else:
            head = f"Tracking **[{title}]({series_url})** is now active."
        chan = notif_channel.mention if notif_channel is not None else "the configured channel"
        body = (
            f"{head}\n\n"
            f"📢 New updates will be sent to {chan}.\n\n"
            "-# *Use `/track update` to change the ping role.*"
        )

    container = discord.ui.Container(accent_colour=discord.Colour.green())
    gallery = hero_cover_gallery(cover_url)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(f"## {emojis.CHECK}  Tracking Successful"))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(body))
    if warning:
        container.add_item(small_separator())
        container.add_item(discord.ui.TextDisplay(f"{emojis.WARNING}  {warning}"))
    container.add_item(small_separator())
    container.add_item(footer_section(bot))

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


# ---------------------------------------------------------------------------
# /track update — small green acknowledgement, optional hero cover
# ---------------------------------------------------------------------------


def build_track_update_view(
    *,
    title: str,
    role_text: str,
    cover_url: str | None,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    body = f"The role for **{title}** has been updated to {role_text}."
    container = discord.ui.Container(accent_colour=discord.Colour.green())
    gallery = hero_cover_gallery(cover_url)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(f"## {emojis.CHECK}  Track updated"))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(body))
    container.add_item(small_separator())
    container.add_item(footer_section(bot))

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


# ---------------------------------------------------------------------------
# /track remove — small green acknowledgement with optional warnings
# ---------------------------------------------------------------------------


def build_track_remove_view(
    *,
    title: str,
    series_url: str | None,
    deleted_role_name: str | None,
    crawler_warning: bool,
    role_warning: bool,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    if series_url:
        body = f"Successfully stopped tracking **[{title}]({series_url})**"
    else:
        body = f"Successfully stopped tracking **{title}**"
    if deleted_role_name:
        body += f" and deleted the @{deleted_role_name} role"
    body += "."

    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {emojis.CHECK}  Track removed"),
        small_separator(),
        discord.ui.TextDisplay(body),
        accent_colour=discord.Colour.green(),
    )
    warnings: list[str] = []
    if crawler_warning:
        warnings.append(f"{emojis.WARNING} Could not notify the crawler (error — see logs).")
    if role_warning:
        warnings.append(f"{emojis.WARNING} Failed to delete the role (see logs).")
    if warnings:
        container.add_item(small_separator())
        container.add_item(discord.ui.TextDisplay("\n".join(warnings)))
    container.add_item(small_separator())
    container.add_item(footer_section(bot))

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


# ---------------------------------------------------------------------------
# Role-validation error helpers (managed / hierarchy)
# ---------------------------------------------------------------------------


def build_role_managed_view(bot: discord.Client | None = None) -> discord.ui.LayoutView:
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {emojis.ERROR}  Role is bot-managed"),
        small_separator(),
        discord.ui.TextDisplay(
            "The role you provided is managed by another bot.\n"
            "Please pick a role that isn't bot-managed and try again."
        ),
        accent_colour=discord.Colour.red(),
    )
    if bot is not None:
        container.add_item(small_separator())
        container.add_item(footer_section(bot))
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def build_role_hierarchy_view(bot: discord.Client | None = None) -> discord.ui.LayoutView:
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {emojis.ERROR}  Role above my top role"),
        small_separator(),
        discord.ui.TextDisplay(
            "The role you provided is higher than my top role.\n"
            "Please move the role below my top role and try again."
        ),
        accent_colour=discord.Colour.red(),
    )
    if bot is not None:
        container.add_item(small_separator())
        container.add_item(footer_section(bot))
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


# ---------------------------------------------------------------------------
# Shared grouped list (used by /track list and /subscribe list)
# ---------------------------------------------------------------------------


def build_grouped_list_views(
    items: Sequence[dict],
    *,
    title: str,
    bot: discord.Client | None,
    empty_title: str = "Nothing found",
    empty_description: str = "No entries.",
    invoker_id: int | None = None,
    accent_colour: discord.Colour | None = None,
) -> list[discord.ui.LayoutView]:
    """Scanlator-grouped numbered list rendered as paginated LayoutViews."""
    accent = accent_colour or discord.Colour.blurple()

    if not items:
        container = discord.ui.Container(
            discord.ui.TextDisplay(f"## 📚  {empty_title}"),
            small_separator(),
            discord.ui.TextDisplay(empty_description),
            large_separator(),
            footer_section(bot),
            accent_colour=discord.Colour.red(),
        )
        view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
        view.add_item(container)
        return [view]

    blocks: list[str] = []
    current: list[str] = []
    last_scanlator: str | None = None
    line_index = 0
    chars = 0

    def _flush() -> None:
        nonlocal current, chars
        if current:
            blocks.append("\n".join(current))
            current = []
            chars = 0

    for item in items:
        line_index += 1
        scanlator = str(item.get("website_key") or "").strip() or "unknown"
        item_title = str(item.get("title") or "Unknown")
        url = str(item.get("url") or "")
        last_chapter = item.get("last_chapter")
        last_chapter_url = item.get("last_chapter_url")
        last_chapter_is_premium = item.get("last_chapter_is_premium")

        if last_chapter:
            chapter_part = chapter_markdown(
                {
                    "name": last_chapter,
                    "url": last_chapter_url,
                    "is_premium": last_chapter_is_premium,
                }
            )
            line = f"**{line_index}.** [{item_title}]({url}) • {chapter_part}"
        else:
            line = f"**{line_index}.** [{item_title}]({url})"

        # Section header when scanlator changes.
        if scanlator != last_scanlator:
            header = f"\n**{scanlator.title()}**"
            if chars + len(header) + len(line) + 2 > LIST_MAX and current:
                _flush()
            current.append(header)
            chars += len(header) + 1
            last_scanlator = scanlator

        if chars + len(line) + 1 > LIST_MAX:
            _flush()
            current.append(f"**{scanlator.title()}**")
            chars += len(scanlator) + 5
        current.append(line)
        chars += len(line) + 1

    _flush()

    total_pages = len(blocks)
    pages: list[discord.ui.LayoutView] = []
    for i, body in enumerate(blocks, start=1):
        container = discord.ui.Container(
            discord.ui.TextDisplay(f"## 📚  {title}"),
            small_separator(),
            discord.ui.TextDisplay(safe_truncate(body, TEXT_MAX)),
            small_separator(),
            footer_section(bot, extra=(f"Page {i}/{total_pages}" if total_pages > 1 else None)),
            accent_colour=accent,
        )
        view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
        view.add_item(container)
        pages.append(view)
    return pages


# ---------------------------------------------------------------------------
# /subscribe — success views
# ---------------------------------------------------------------------------


def build_subscribe_success_view(
    *,
    title: str,
    series_url: str,
    ping_role: discord.Role | None,
    notif_channel: discord.abc.GuildChannel | discord.Thread | None,
    cover_url: str | None,
    is_dm: bool,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Hero image-forward 'Subscribed to Series' view."""
    if is_dm:
        body = (
            f"Successfully subscribed to **[{title}]({series_url})**!\n\n"
            "📨  You'll receive notifications for this manhwa in your DMs."
        )
    else:
        ping_part = f" ({ping_role.mention})" if ping_role is not None else ""
        chan = notif_channel.mention if notif_channel is not None else "the configured channel"
        body = (
            f"Successfully subscribed to **[{title}]({series_url}){ping_part}**!\n\n"
            f"📢  New updates will be sent to {chan}."
        )

    container = discord.ui.Container(accent_colour=discord.Colour.green())
    gallery = hero_cover_gallery(cover_url)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(f"## {emojis.CHECK}  Subscribed"))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(body))
    container.add_item(small_separator())
    container.add_item(footer_section(bot))

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def build_unsubscribe_view(
    *,
    title: str,
    series_url: str | None,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    if series_url:
        body = f"Successfully unsubscribed from **[{title}]({series_url})**."
    else:
        body = f"Successfully unsubscribed from **{title}**."
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {emojis.CHECK}  Unsubscribed"),
        small_separator(),
        discord.ui.TextDisplay(body),
        small_separator(),
        footer_section(bot),
        accent_colour=discord.Colour.green(),
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def build_bulk_subscribe_result_view(
    *,
    successes: int,
    fails: int,
    action: str,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Result view for /subscribe all and /unsubscribe all."""
    verb_past = "subscribed to" if action == "subscribe" else "unsubscribed from"
    body = f"You have successfully {verb_past} **{successes}** series!"
    if fails:
        body += (
            f"\n\n{emojis.WARNING} I was unable to {verb_past.split()[0]} **{fails}** series. "
            "Double-check my permissions and try again."
        )
    accent = discord.Colour.orange() if fails else discord.Colour.green()
    label = "Subscribed" if action == "subscribe" else "Unsubscribed"
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {emojis.CHECK}  {label}"),
        small_separator(),
        discord.ui.TextDisplay(body),
        small_separator(),
        footer_section(bot),
        accent_colour=accent,
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def build_simple_status_view(
    *,
    title: str,
    description: str,
    accent: discord.Colour,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Generic compact status container — used for cancellation / 'nothing to do' messages."""
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {title}"),
        small_separator(),
        discord.ui.TextDisplay(description),
        small_separator(),
        footer_section(bot),
        accent_colour=accent,
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view
