"""Chapter list and supported-websites paginated layouts."""

from __future__ import annotations

import discord

from .base import (
    LIST_MAX,
    BaseLayoutView,
    chapter_markdown,
    footer_section,
    large_separator,
    safe_truncate,
    small_separator,
)


def _format_chapter_line(idx: int, ch: dict) -> str:
    return f"`{idx:>3}.` {chapter_markdown(ch, idx)}"


def build_chapter_list_views(
    chapters: list[dict],
    *,
    manga_title: str,
    manga_url: str | None,
    bot: discord.Client | None,
    page_size: int = 30,
    invoker_id: int | None = None,
) -> list[discord.ui.LayoutView]:
    """Build paginated chapter-list LayoutViews. Two-column visual layout per page."""
    title_block = (
        f"# 📚 [Chapters for {manga_title}]({manga_url})"
        if manga_url
        else f"# 📚 Chapters for {manga_title}"
    )

    if not chapters:
        container = discord.ui.Container(
            discord.ui.TextDisplay(title_block),
            small_separator(),
            discord.ui.TextDisplay("*No chapters found.*"),
            large_separator(),
            footer_section(bot),
            accent_colour=discord.Colour.greyple(),
        )
        view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
        view.add_item(container)
        return [view]

    pages: list[discord.ui.LayoutView] = []
    total = len(chapters)
    total_pages = (total + page_size - 1) // page_size
    for start in range(0, total, page_size):
        chunk = chapters[start : start + page_size]
        lines: list[str] = [
            _format_chapter_line(start + offset + 1, ch) for offset, ch in enumerate(chunk)
        ]
        half = (len(lines) + 1) // 2
        left_col = "\n".join(lines[:half])
        right_col = "\n".join(lines[half:])

        body = left_col
        if right_col:
            body = f"{left_col}\n\n{right_col}"
        body = safe_truncate(body, LIST_MAX)

        page_num = start // page_size + 1
        footer_extra = (
            f"Page {page_num}/{total_pages} • {total} chapters"
            if total_pages > 1
            else f"{total} chapters"
        )

        container = discord.ui.Container(
            discord.ui.TextDisplay(title_block),
            small_separator(),
            discord.ui.TextDisplay(body),
            small_separator(),
            footer_section(bot, extra=footer_extra),
            accent_colour=discord.Colour.green(),
        )
        view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
        view.add_item(container)
        pages.append(view)

    return pages


def build_supported_websites_views(
    websites: list[dict],
    *,
    bot: discord.Client | None,
    page_size: int = 12,
    invoker_id: int | None = None,
) -> list[discord.ui.LayoutView]:
    """Paginated `/supported_websites` list."""
    title = "# 🌐 Supported websites"
    note = (
        "More websites will be added in the future. "
        "Don't forget to leave suggestions for sites you'd like to see."
    )

    if not websites:
        container = discord.ui.Container(
            discord.ui.TextDisplay(title),
            small_separator(),
            discord.ui.TextDisplay("*None available.*"),
            large_separator(),
            footer_section(bot),
            accent_colour=discord.Colour.green(),
        )
        view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
        view.add_item(container)
        return [view]

    sorted_sites = sorted(websites, key=lambda w: str(w.get("name") or w.get("key") or "").lower())
    enabled_sites = [w for w in sorted_sites if w.get("enabled", True)]
    total = len(enabled_sites)
    total_pages = max(1, (total + page_size - 1) // page_size)

    pages: list[discord.ui.LayoutView] = []
    for start in range(0, total, page_size):
        chunk = enabled_sites[start : start + page_size]
        lines: list[str] = []
        for w in chunk:
            key = w.get("key") or w.get("website_key") or ""
            name = w.get("name") or key
            base_url = w.get("base_url") or ""
            format_url = w.get("format_url") or ""
            header = f"• [{name}]({base_url})" if base_url else f"• **{name}**"
            lines.append(header)
            if format_url:
                lines.append(f"​ ​ ​ ↪ `{format_url}`")

        body = safe_truncate("\n".join(lines), LIST_MAX)
        page_num = start // page_size + 1
        footer_extra = (
            f"Page {page_num}/{total_pages} • {total} websites"
            if total_pages > 1
            else f"{total} websites"
        )
        container = discord.ui.Container(
            discord.ui.TextDisplay(f"{title} ({total})"),
            small_separator(),
            discord.ui.TextDisplay(body),
            small_separator(),
            discord.ui.TextDisplay(f"-# {note}"),
            small_separator(),
            footer_section(bot, extra=footer_extra),
            accent_colour=discord.Colour.green(),
        )
        view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
        view.add_item(container)
        pages.append(view)

    return pages
