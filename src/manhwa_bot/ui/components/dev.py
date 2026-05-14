"""Dev cog diagnostic Components V2 layouts."""

from __future__ import annotations

import discord

from .. import emojis
from .base import (
    TEXT_MAX,
    BaseLayoutView,
    footer_section,
    safe_truncate,
    small_separator,
)


def _wrap_code(text: str, lang: str = "") -> str:
    safe = text.replace("```", "`​`​`")
    return f"```{lang}\n{safe}\n```"


def build_diagnostic_view(
    *,
    title: str,
    body: str,
    lang: str = "",
    accent: discord.Colour | None = None,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Single-page diagnostic — title + monospace body."""
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {title}"),
        small_separator(),
        discord.ui.TextDisplay(_wrap_code(safe_truncate(body, TEXT_MAX - 16), lang)),
        small_separator(),
        footer_section(bot),
        accent_colour=accent or discord.Colour.dark_grey(),
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def build_diagnostic_pages(
    text: str,
    *,
    title: str = "Output",
    lang: str = "",
    accent: discord.Colour | None = None,
    chunk_size: int = 1800,
    bot: discord.Client | None = None,
    invoker_id: int | None = None,
) -> list[discord.ui.LayoutView]:
    """Split a long diagnostic blob into LayoutView pages."""
    if not text:
        text = "(no output)"
    pieces: list[str] = []
    for i in range(0, len(text), chunk_size):
        pieces.append(text[i : i + chunk_size])
    pages: list[discord.ui.LayoutView] = []
    total = len(pieces)
    for i, body in enumerate(pieces, start=1):
        container = discord.ui.Container(
            discord.ui.TextDisplay(f"## {title}" + (f" ({i}/{total})" if total > 1 else "")),
            small_separator(),
            discord.ui.TextDisplay(_wrap_code(body, lang)),
            small_separator(),
            footer_section(bot),
            accent_colour=accent or discord.Colour.dark_grey(),
        )
        view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
        view.add_item(container)
        pages.append(view)
    return pages


def build_g_update_view(
    *,
    message: str,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    body = (
        f"{message}\n\n*If you have any questions, please join the support server "
        "and ping the maintainers.*"
    )
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"# {emojis.WARNING}  Important Update"),
        small_separator(),
        discord.ui.TextDisplay(body),
        small_separator(),
        footer_section(bot, extra="Sent by the bot owner"),
        accent_colour=discord.Colour.red(),
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def build_premium_check_view(
    *,
    user: discord.User,
    ok: bool,
    reason: str | None,
    sources: list[str],
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    body = (
        f"**ok:** `{ok}`\n"
        f"**consolidated reason:** `{reason or '-'}`\n"
        f"**qualifying sources:** {', '.join(sources) if sources else '(none)'}"
    )
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## 💎  Premium check — {user}"),
        small_separator(),
        discord.ui.TextDisplay(body),
        small_separator(),
        footer_section(bot),
        accent_colour=discord.Colour.green() if ok else discord.Colour.red(),
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def build_premium_list_views(
    grants: list,
    *,
    page_size: int = 10,
    bot: discord.Client | None = None,
    invoker_id: int | None = None,
) -> list[discord.ui.LayoutView]:
    pages: list[discord.ui.LayoutView] = []
    total = len(grants)
    for i in range(0, total, page_size):
        chunk = grants[i : i + page_size]
        lines = []
        for g in chunk:
            expiry = g.expires_at or "permanent"
            revoked = f" revoked={g.revoked_at}" if g.revoked_at else ""
            lines.append(
                f"`{g.id}` {g.scope}={g.target_id} expires={expiry}{revoked} "
                f"reason={g.reason or '-'}"
            )
        end = i + len(chunk)
        container = discord.ui.Container(
            discord.ui.TextDisplay(f"## 💎  Premium grants ({i + 1}-{end} / {total})"),
            small_separator(),
            discord.ui.TextDisplay("\n".join(lines)),
            small_separator(),
            footer_section(bot),
            accent_colour=discord.Colour.gold(),
        )
        view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
        view.add_item(container)
        pages.append(view)
    return pages
