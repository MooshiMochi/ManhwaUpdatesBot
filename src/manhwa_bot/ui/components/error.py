"""Error and success acknowledgement views (Components V2)."""

from __future__ import annotations

import discord

from .. import emojis
from .base import (
    TEXT_MAX,
    BaseLayoutView,
    add_children,
    footer_section,
    safe_truncate,
    severity_accent,
)

# Source labels reused by the global app-command error handler and per-cog
# helpers. Same constants as the legacy `ui/error.py` so call sites can keep
# importing the same names.
SOURCE_BOT = "Bot Error"
SOURCE_CRAWLER = "Crawler Error"
SOURCE_PERMISSION = "Permission Error"
SOURCE_COOLDOWN = "Cooldown"
SOURCE_VALIDATION = "Invalid Input"


def _glyph_for_source(source: str) -> str:
    s = source.lower()
    if "permission" in s:
        return emojis.LOCK
    if "cooldown" in s:
        return emojis.LOADING
    if "invalid" in s or "validation" in s:
        return emojis.WARNING
    return emojis.ERROR


def build_error_view(
    message: str,
    *,
    source: str = SOURCE_BOT,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Modernized error response — red Container with glyph header."""
    glyph = _glyph_for_source(source)
    body = safe_truncate(str(message), TEXT_MAX)

    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {glyph}  {source}"),
        discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
        discord.ui.TextDisplay(body),
        accent_colour=severity_accent("error"),
    )
    if bot is not None:
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(footer_section(bot))

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def build_success_view(
    *,
    title: str,
    description: str,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Compact green acknowledgement Container."""
    body = safe_truncate(str(description), TEXT_MAX)
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {emojis.CHECK}  {title}"),
        discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
        discord.ui.TextDisplay(body),
        accent_colour=severity_accent("success"),
    )
    if bot is not None:
        add_children(
            container,  # type: ignore[arg-type]
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
            footer_section(bot),
        )

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def build_info_view(
    *,
    title: str,
    description: str,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    body = safe_truncate(str(description), TEXT_MAX)
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## ℹ️  {title}"),
        discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
        discord.ui.TextDisplay(body),
        accent_colour=severity_accent("info"),
    )
    if bot is not None:
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(footer_section(bot))
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view
