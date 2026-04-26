"""Pure embed-builder functions shared across cogs. No side effects."""

from __future__ import annotations

import discord

_SYNOPSIS_MAX = 4096
_FIELD_MAX = 1024


def series_info_embed(data: dict, *, request_id: str) -> discord.Embed:
    """Build an embed from a crawler ``info`` response payload."""
    title = data.get("title") or "Unknown title"
    status = data.get("status") or "Unknown"
    synopsis = data.get("synopsis") or ""
    cover_url = data.get("cover_url") or data.get("cover") or ""
    website_key = data.get("website_key") or ""
    series_url = data.get("series_url") or ""

    description = synopsis[:_SYNOPSIS_MAX] if synopsis else "*No synopsis available.*"

    colour = _status_colour(status)
    embed = discord.Embed(
        title=title, description=description, colour=colour, url=series_url or None
    )

    if status:
        embed.add_field(name="Status", value=status, inline=True)

    genres: list = data.get("genres") or []
    if genres:
        embed.add_field(
            name="Genres", value=", ".join(str(g) for g in genres)[:_FIELD_MAX], inline=True
        )

    authors: list = data.get("authors") or data.get("author") or []
    if isinstance(authors, str):
        authors = [authors]
    if authors:
        embed.add_field(
            name="Authors", value=", ".join(str(a) for a in authors)[:_FIELD_MAX], inline=True
        )

    if cover_url:
        embed.set_thumbnail(url=cover_url)

    footer_parts = []
    if website_key:
        footer_parts.append(website_key)
    footer_parts.append(f"req: {request_id}")
    embed.set_footer(text=" • ".join(footer_parts))

    return embed


def chapter_list_embeds(
    chapters: list[dict],
    *,
    title: str = "Chapters",
    page_size: int = 15,
) -> list[discord.Embed]:
    """Split a chapter list into paginated embeds of *page_size* rows each."""
    if not chapters:
        embed = discord.Embed(
            title=title, description="No chapters found.", colour=discord.Colour.greyple()
        )
        return [embed]

    pages: list[discord.Embed] = []
    total = len(chapters)
    for start in range(0, total, page_size):
        chunk = chapters[start : start + page_size]
        lines: list[str] = []
        for ch in chunk:
            ch_label = ch.get("chapter") or ch.get("chapter_number") or f"#{ch.get('index', '?')}"
            url = ch.get("url") or ch.get("chapter_url") or ""
            if url:
                lines.append(f"[{ch_label}]({url})")
            else:
                lines.append(ch_label)

        page_num = start // page_size + 1
        total_pages = (total + page_size - 1) // page_size
        embed = discord.Embed(
            title=title,
            description="\n".join(lines),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text=f"Page {page_num}/{total_pages} • {total} chapters total")
        pages.append(embed)

    return pages


def search_results_embed(
    results: list[dict],
    *,
    query: str,
    page: int,
    page_size: int = 5,
    total_pages: int,
) -> discord.Embed:
    """Build a single search-results embed for the given page."""
    start = page * page_size
    chunk = results[start : start + page_size]

    embed = discord.Embed(
        title=f"Search: {query[:100]}",
        colour=discord.Colour.blurple(),
    )

    if not chunk:
        embed.description = "No results found."
        return embed

    for item in chunk:
        item_title = item.get("title") or "Unknown"
        website_key = item.get("website_key") or ""
        series_url = item.get("series_url") or item.get("url") or ""
        status = item.get("status") or ""

        name = f"{item_title}"
        value_parts = []
        if website_key:
            value_parts.append(f"**Site:** {website_key}")
        if status:
            value_parts.append(f"**Status:** {status}")
        if series_url:
            value_parts.append(f"[View series]({series_url})")
        value = "\n".join(value_parts) or "​"

        embed.add_field(name=name[:256], value=value[:_FIELD_MAX], inline=False)

    embed.set_footer(text=f"Page {page + 1}/{total_pages}")
    return embed


def failed_websites_field(failed: list[str]) -> tuple[str, str] | None:
    """Return a (name, value) pair for failed websites, or None if the list is empty."""
    if not failed:
        return None
    return ("Failed websites", ", ".join(failed)[:_FIELD_MAX])


def supported_websites_embeds(websites: list[dict], *, page_size: int = 20) -> list[discord.Embed]:
    """Render the supported websites list as paginated embeds."""
    if not websites:
        return [
            discord.Embed(
                title="Supported websites",
                description="None available.",
                colour=discord.Colour.greyple(),
            )
        ]

    pages: list[discord.Embed] = []
    total = len(websites)
    for start in range(0, total, page_size):
        chunk = websites[start : start + page_size]
        lines = []
        for w in chunk:
            key = w.get("key") or w.get("website_key") or str(w)
            name = w.get("name") or key
            enabled = w.get("enabled", True)
            marker = "✓" if enabled else "✗"
            lines.append(f"{marker} **{key}** — {name}")

        page_num = start // page_size + 1
        total_pages = (total + page_size - 1) // page_size
        embed = discord.Embed(
            title="Supported websites",
            description="\n".join(lines),
            colour=discord.Colour.green(),
        )
        embed.set_footer(text=f"Page {page_num}/{total_pages} • {total} websites")
        pages.append(embed)

    return pages


def chapter_update_embed(payload: dict) -> discord.Embed:
    """Embed for a single new-chapter notification, used by the updates cog."""
    series_title = payload.get("series_title") or payload.get("url_name") or "New chapter"
    series_url = payload.get("series_url") or None
    chapter = payload.get("chapter") or {}
    chapter_name = chapter.get("name") or f"Chapter {chapter.get('index', '?')}"
    chapter_url = chapter.get("url") or series_url or ""
    is_premium = bool(chapter.get("is_premium"))

    suffix = " (premium)" if is_premium else ""
    if chapter_url:
        description = f"New chapter: [{chapter_name}{suffix}]({chapter_url})"
    else:
        description = f"New chapter: {chapter_name}{suffix}"

    colour = discord.Colour.gold() if is_premium else discord.Colour.green()
    embed = discord.Embed(
        title=f"📖 {series_title}",
        description=description,
        url=series_url,
        colour=colour,
    )
    cover = payload.get("cover_url")
    if cover:
        embed.set_thumbnail(url=cover)
    website_key = payload.get("website_key")
    if website_key:
        embed.set_footer(text=str(website_key))
    return embed


def _status_colour(status: str) -> discord.Colour:
    s = status.lower()
    if "ongoing" in s or "releasing" in s:
        return discord.Colour.green()
    if "completed" in s or "finished" in s:
        return discord.Colour.blue()
    if "hiatus" in s or "paused" in s:
        return discord.Colour.orange()
    if "dropped" in s or "cancelled" in s:
        return discord.Colour.red()
    return discord.Colour.blurple()
