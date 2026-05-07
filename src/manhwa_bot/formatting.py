"""Pure embed-builder functions shared across cogs. No side effects."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import discord

_SYNOPSIS_MAX = 4096
_FIELD_MAX = 1024
_DESC_MAX = 4096

MU_FOOTER_TEXT = "Manhwa Updates"


def mu_footer(bot: discord.Client | None) -> tuple[str, str | None]:
    """Returns (text, icon_url) for the standard 'Manhwa Updates' footer."""
    icon = None
    if bot is not None and getattr(bot, "user", None) is not None:
        try:
            icon = bot.user.display_avatar.url  # type: ignore[union-attr]
        except Exception:
            icon = None
    return MU_FOOTER_TEXT, icon


def _set_mu_footer(embed: discord.Embed, bot: discord.Client | None) -> None:
    text, icon = mu_footer(bot)
    if icon:
        embed.set_footer(text=text, icon_url=icon)
    else:
        embed.set_footer(text=text)


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


# ----------------------------------------------------------------------------
# v1-style embed builders
# ----------------------------------------------------------------------------


def tracking_success_embed(
    *,
    title: str,
    series_url: str,
    ping_role: discord.Role | None,
    notif_channel: discord.abc.GuildChannel | discord.Thread | None,
    cover_url: str | None,
    is_dm: bool,
    bot: discord.Client | None,
) -> discord.Embed:
    """V1 'Tracking Successful' embed."""
    if is_dm:
        description = (
            f"Successfully tracked **[{title}]({series_url})**!\n"
            "Please make sure your DMs are open to receive notifications."
        )
    else:
        if ping_role is not None:
            head = f"Tracking **[{title}]({series_url}) ({ping_role.mention})** is successful!"
        else:
            head = f"Tracking **[{title}]({series_url})** is successful!"
        chan = notif_channel.mention if notif_channel is not None else "the configured channel"
        description = (
            f"{head}\n"
            f"New updates for this manga will be sent in {chan}\n\n"
            "**Note:** You can change the role to ping with `/track update`."
        )

    embed = discord.Embed(
        title="Tracking Successful",
        colour=discord.Colour.green(),
        description=description,
    )
    if cover_url:
        embed.set_image(url=cover_url)
    _set_mu_footer(embed, bot)
    return embed


def subscribe_success_embed(
    *,
    title: str,
    series_url: str,
    ping_role: discord.Role | None,
    notif_channel: discord.abc.GuildChannel | discord.Thread | None,
    cover_url: str | None,
    is_dm: bool,
    bot: discord.Client | None,
) -> discord.Embed:
    """V1 'Subscribed to Series' embed."""
    if is_dm:
        description = (
            f"Successfully subscribed to **[{title}]({series_url})!**\n\n"
            "You will receive updates for this manhwa in your DMs."
        )
    else:
        ping_part = f" ({ping_role.mention})" if ping_role is not None else ""
        chan = notif_channel.mention if notif_channel is not None else "the configured channel"
        description = (
            f"Successfully subscribed to **[{title}]({series_url}){ping_part}!**\n\n"
            f"New updates for this manga will be sent in {chan}"
        )

    embed = discord.Embed(
        title="Subscribed to Series",
        colour=discord.Colour.green(),
        description=description,
    )
    if cover_url:
        embed.set_image(url=cover_url)
    _set_mu_footer(embed, bot)
    return embed


def grouped_list_embeds(
    items: Sequence[dict],
    *,
    title: str,
    bot: discord.Client | None,
    empty_title: str = "Nothing found",
    empty_description: str = "No entries.",
) -> list[discord.Embed]:
    """V1 scanlator-grouped numbered list (used by /track list and /subscribe list).

    Each item must have keys: ``title``, ``url``, ``website_key``, optional ``last_chapter``
    (text label) and optional ``last_chapter_url`` (renders the chapter as a hyperlink).
    Items are pre-sorted by the caller.
    """
    if not items:
        embed = discord.Embed(
            title=empty_title,
            colour=discord.Colour.red(),
            description=empty_description,
        )
        _set_mu_footer(embed, bot)
        return [embed]

    def _make_embed() -> discord.Embed:
        return discord.Embed(title=title, description="", colour=discord.Colour.blurple())

    embeds: list[discord.Embed] = []
    em = _make_embed()
    last_scanlator: str | None = None
    line_index = 0
    total = len(items)

    for item in items:
        line_index += 1
        scanlator = str(item.get("website_key") or "").strip() or "unknown"
        item_title = str(item.get("title") or "Unknown")
        url = str(item.get("url") or "")
        last_chapter = item.get("last_chapter")
        last_chapter_url = item.get("last_chapter_url")

        if last_chapter:
            chapter_part = (
                f"[{last_chapter}]({last_chapter_url})" if last_chapter_url else str(last_chapter)
            )
            line = f"**{line_index}.** [{item_title}]({url}) - {chapter_part}\n"
        else:
            line = f"**{line_index}.** [{item_title}]({url})\n"

        if scanlator != last_scanlator:
            header = f"\n**{scanlator.title()}**\n"
            if len(em.description or "") + len(header) > _DESC_MAX:
                embeds.append(em)
                em = _make_embed()
            em.description = (em.description or "") + header
            last_scanlator = scanlator

        if len(em.description or "") + len(line) > _DESC_MAX:
            embeds.append(em)
            em = _make_embed()
            em.description = f"\n**{scanlator.title()}**\n"

        em.description = (em.description or "") + line
        if line_index == total:
            embeds.append(em)

    total_pages = len(embeds)
    for i, e in enumerate(embeds, start=1):
        text, icon = mu_footer(bot)
        suffix = f" • Page {i}/{total_pages}" if total_pages > 1 else ""
        if icon:
            e.set_footer(text=f"{text}{suffix}", icon_url=icon)
        else:
            e.set_footer(text=f"{text}{suffix}")
    return embeds


def info_display_embed(
    data: dict,
    *,
    scanlator_icon_url: str | None,
    scanlator_base_url: str | None,
    bot: discord.Client | None = None,
    request_id: str | None = None,
) -> discord.Embed:
    """V1-style /info embed: cover via set_image, scanlator as set_author, structured description."""
    title = data.get("title") or "Unknown title"
    series_url = data.get("series_url") or data.get("url") or None
    cover_url = data.get("cover_url") or data.get("cover") or None
    website_key = data.get("website_key") or ""
    status = data.get("status") or "Unknown"
    synopsis = data.get("synopsis") or ""
    chapters = data.get("chapters") or data.get("latest_chapters") or []
    chapter_count = data.get("chapter_count")
    if chapter_count is None:
        chapter_count = len(chapters) if chapters else 0

    embed = discord.Embed(
        title=title,
        url=series_url,
        colour=_status_colour(str(status)),
    )
    if cover_url:
        embed.set_image(url=cover_url)
    if website_key:
        embed.set_author(
            name=website_key.title(),
            url=scanlator_base_url or None,
            icon_url=scanlator_icon_url or None,
        )

    if synopsis:
        synopsis_text = str(synopsis)
        if len(synopsis_text) > _FIELD_MAX:
            link = f"... [(read more)]({series_url})" if series_url else "..."
            synopsis_text = synopsis_text[: _FIELD_MAX - len(link)] + link
        embed.add_field(name="Synopsis:", value=synopsis_text, inline=False)

    def _ch_label(ch: object) -> str:
        if isinstance(ch, dict):
            return str(ch.get("name") or ch.get("chapter") or ch.get("text") or "?")
        return str(ch)

    latest = _ch_label(chapters[0]) if chapters else "N/A"
    first = _ch_label(chapters[-1]) if chapters else "N/A"
    scanlator_link = (
        f"[{website_key.title()}]({scanlator_base_url})"
        if (website_key and scanlator_base_url)
        else (website_key.title() if website_key else "Unknown")
    )
    desc = (
        f"**Num of Chapters:** {chapter_count}\n"
        f"**Status:** {status}\n"
        f"**Latest Chapter:** {latest}\n"
        f"**First Chapter:** {first}\n"
        f"**Scanlator:** {scanlator_link}"
    )
    embed.description = desc
    _set_mu_footer(embed, bot)
    return embed


def chapters_embeds_v1(
    chapters: list[dict],
    *,
    manga_title: str,
    manga_url: str | None,
    bot: discord.Client | None,
    page_size: int = 30,
) -> list[discord.Embed]:
    """V1-style chapter list. Series title is hyperlinked; chapters are
    1-based indexed and rendered in two columns per page."""
    if not chapters:
        embed = discord.Embed(
            title=f"Chapters for {manga_title}",
            description="No chapters found.",
            colour=discord.Colour.green(),
            url=manga_url or None,
        )
        _set_mu_footer(embed, bot)
        return [embed]

    pages: list[discord.Embed] = []
    total = len(chapters)
    total_pages = (total + page_size - 1) // page_size
    for start in range(0, total, page_size):
        chunk = chapters[start : start + page_size]
        lines: list[str] = []
        for offset, ch in enumerate(chunk):
            idx = start + offset + 1  # 1-based global index
            label = ch.get("chapter") or ch.get("name") or ch.get("text") or f"#{idx}"
            url = ch.get("url") or ch.get("chapter_url") or ""
            entry = f"[{label}]({url})" if url else str(label)
            lines.append(f"`{idx:>3}.` {entry}")

        half = (len(lines) + 1) // 2
        left_col = "\n".join(lines[:half])
        right_col = "\n".join(lines[half:])

        embed = discord.Embed(
            title=f"Chapters for {manga_title}",
            colour=discord.Colour.green(),
            url=manga_url or None,
        )
        embed.add_field(name="​", value=left_col or "​", inline=True)
        if right_col:
            embed.add_field(name="​", value=right_col, inline=True)
        page_num = start // page_size + 1
        text, icon = mu_footer(bot)
        suffix = (
            f" • Page {page_num}/{total_pages} • {total} chapters"
            if total_pages > 1
            else f" • {total} chapters"
        )
        if icon:
            embed.set_footer(text=f"{text}{suffix}", icon_url=icon)
        else:
            embed.set_footer(text=f"{text}{suffix}")
        pages.append(embed)
    return pages


def supported_websites_embeds_v1(
    websites: list[dict],
    *,
    bot: discord.Client | None,
    page_size: int = 10,
) -> list[discord.Embed]:
    """V1-style supported websites: '• [{name}]({base_url})\n   ↪ Format -> `{format_url}`'."""
    if not websites:
        embed = discord.Embed(
            title="Supported Websites (0)",
            description="None available.",
            colour=discord.Colour.green(),
        )
        _set_mu_footer(embed, bot)
        return [embed]

    sorted_sites = sorted(websites, key=lambda w: str(w.get("name") or w.get("key") or "").lower())
    enabled_sites = [w for w in sorted_sites if w.get("enabled", True)]
    total = len(enabled_sites)

    pages: list[discord.Embed] = []
    for start in range(0, total, page_size):
        chunk = enabled_sites[start : start + page_size]
        lines: list[str] = ["Manhwa Updates Bot currently supports the following websites:\n"]
        for w in chunk:
            key = w.get("key") or w.get("website_key") or ""
            name = w.get("name") or key
            base_url = w.get("base_url") or ""
            format_url = w.get("format_url") or ""
            if base_url:
                lines.append(f"• [{name}]({base_url})")
            else:
                lines.append(f"• **{name}**")
            if format_url:
                lines.append(f"​ ​ ​ ↪ Format -> `{format_url}`")

        embed = discord.Embed(
            title=f"Supported Websites ({total})",
            description="\n".join(lines),
            colour=discord.Colour.green(),
        )
        embed.add_field(
            name="__Note__",
            value=(
                "More websites will be added in the future. "
                "Don't forget to leave suggestions on websites I should add."
            ),
            inline=False,
        )
        page_num = start // page_size + 1
        total_pages = (total + page_size - 1) // page_size
        text, icon = mu_footer(bot)
        suffix = f" • Page {page_num}/{total_pages}" if total_pages > 1 else ""
        if icon:
            embed.set_footer(text=f"{text}{suffix}", icon_url=icon)
        else:
            embed.set_footer(text=f"{text}{suffix}")
        pages.append(embed)
    return pages


def stats_embed(
    *,
    bookmarks_count: int,
    tracks_count: int,
    subs_count: int,
    manhwa_count: int,
    websites_count: int,
    guilds_count: int,
    users_count: int,
    start_unix: int,
    bot_created_unix: int,
    bot: discord.Client | None,
) -> discord.Embed:
    """V1 9-field teal stats panel."""
    embed = discord.Embed(
        title="Manhwa Updates Bot Statistics",
        description="Here are the current statistics of the bot:",
        colour=discord.Colour(0x1ABC9C),
    )
    embed.add_field(name="🔖 Bookmarks", value=str(bookmarks_count), inline=True)
    embed.add_field(name="📚 Tracked Manhwas", value=str(tracks_count), inline=True)
    embed.add_field(name="👥 Users subbed to Manhwa", value=str(subs_count), inline=True)
    embed.add_field(name="📘 Total Manhwas", value=str(manhwa_count), inline=True)
    embed.add_field(name="🔍 Supported Websites", value=str(websites_count), inline=True)
    embed.add_field(name="🌐 Total Servers", value=str(guilds_count), inline=True)
    embed.add_field(name="👤 Total Users", value=str(users_count), inline=True)
    embed.add_field(name="⌛ Total Uptime", value=f"Since <t:{start_unix}:R>", inline=True)
    embed.add_field(name="🐣 Born", value=f"<t:{bot_created_unix}:R>", inline=True)
    embed.set_footer(text="Manhwa Updates Bot | Stats")
    if bot is not None and getattr(bot, "user", None) is not None:
        try:
            embed.set_thumbnail(url=bot.user.display_avatar.url)  # type: ignore[union-attr]
        except Exception:
            pass
    return embed


def patreon_embed(*, bot: discord.Client | None) -> discord.Embed:
    """V1 Patreon embed (gold, 3 tier fields)."""
    embed = discord.Embed(
        title="Patreon",
        url="https://www.patreon.com/mooshi69",
        colour=discord.Colour.gold(),
        description=(
            "You can donate to our [Patreon](https://www.patreon.com/mooshi69) or "
            "[Ko-fi](https://ko-fi.com/mooshi69) to support the server and the development. "
            "I have been working on the Manhwa Updates bot for just over 1 year now and have "
            "tried my best to make your manhwa reading experience the best that it can be. "
            "By becoming a Patreon you can support my work and pay for the server cost.\n\n"
            "Manage your Patreon subscription using this command to view your patreon status and "
            "change your custom embed color. Subscriptions may take up to `10 minutes` to refresh. "
            "Also make sure your Discord account is linked with Patreon."
        ),
    )
    embed.add_field(
        name='"Hello World" Supporter (£3/month)',
        value=(
            '• Get the `"Hello World" Supporter` role in the support server.\n'
            "• Get access to bot commands in DMs.\n"
            "• Help fund the server and the development."
        ),
        inline=False,
    )
    embed.add_field(
        name="Bot Whisperer (£5/month)",
        value=(
            "• Get the `Bot Whisperer` role in the support server.\n"
            "• Get access to bot commands in DMs.\n"
            "• Help fund the server and the development."
        ),
        inline=False,
    )
    embed.add_field(
        name="The Full Stack (£10/month)",
        value=(
            "• Get `The Full Stack` role in the support server.\n"
            "• Get access to bot commands in DMs.\n"
            "• Help fund the server and the development."
        ),
        inline=False,
    )
    embed.set_footer(text="Manhwa Updates Bot")
    if bot is not None and getattr(bot, "user", None) is not None:
        try:
            embed.set_footer(
                text="Manhwa Updates Bot",
                icon_url=bot.user.display_avatar.url,  # type: ignore[union-attr]
            )
        except Exception:
            pass
    return embed


def translation_embed(
    *,
    text: str,
    translated: str,
    lang_from: str,
    lang_to: str,
) -> discord.Embed:
    """V1 'Translation Complete 🈳' embed with code-block fields."""
    embed = discord.Embed(
        title="Translation Complete 🈳",
        description=f"Language: `{lang_from}` ⟶ `{lang_to}`",
    )
    embed.add_field(name="📥 Input", value=f"```{text[:1000]}```", inline=False)
    embed.add_field(name="📤 Result", value=f"```{translated[:1000]}```", inline=False)
    return embed


_DEFAULT_SUPPORT_URL = "https://discord.gg/TYkw8VBZkr"


def help_embed(*, bot: discord.Client | None, support_url: str | None = None) -> discord.Embed:
    if not support_url:
        support_url = _DEFAULT_SUPPORT_URL
    """V1-style /help embed."""
    description = (
        "**Getting Started:**\n"
        "- Before using the bot, you must configure it for your server:\n"
        "  - `/settings` - See and edit all the bot's settings for your server. *(Requires the `Manage Server` permission)*\n"
        "\n"
        "**Tracking Manhwa:**\n"
        '*(Requires the "Manage Roles" permission)*\n'
        "- Start receiving updates by tracking your favorite manhwa:\n"
        '  - `/track new` - Begin tracking a new manhwa. Optionally, specify a "ping_role" to determine which role gets notified for updates.\n'
        "  - `/track update` - Update the ping role for a tracked manhwa.\n"
        '  - `/track remove` - Stop tracking a manhwa. Use the "delete_role" option to decide if the associated role should also be deleted.\n'
        '  - `/track list` - View all manhwa being tracked on the server. *(Does not require "Manage Roles" permission)*\n'
        "\n"
        "**Subscribing to Manhwa:**\n"
        "- Once a manhwa is being tracked, users can subscribe to receive updates:\n"
        "  - `/subscribe new` - Subscribe to a tracked manhwa.\n"
        "  - `/subscribe delete` - Unsubscribe from a manhwa.\n"
        '  - `/subscribe list` - View your subscribed manhwa. Use the "global" option to see subscriptions across all servers or just the current one.\n'
        "\n"
        "**Bookmarking:**\n"
        "- Manage and view your manga bookmarks:\n"
        "  - `/bookmark new` - Bookmark a manga.\n"
        "  - `/bookmark view` - View your bookmarked manga.\n"
        "  - `/bookmark delete` - Delete a bookmark.\n"
        "  - `/bookmark update` - Update a bookmark.\n"
        "\n"
        "**General Commands:**\n"
        "- `/help` - Get started with Manhwa Updates Bot (this message).\n"
        "- `/search` - Search for a manga.\n"
        "- `/info` - Display info about a manhwa.\n"
        "- `/chapters` - Get a list of chapters of a manga.\n"
        "- `/next_update_check` - Get the time until the next update check.\n"
        "- `/supported_websites` - Get a list of websites supported by the bot.\n"
        "- `/translate` - Translate any text from one language to another.\n"
        "- `/stats` - View general bot statistics.\n"
        "- `/patreon` - View info about the benefits you get as a Patreon.\n"
        "\n"
        "**Permissions:**\n"
        "- The bot requires the following permissions for optimal functionality:\n"
        "  - Send Messages\n"
        "  - Embed Links\n"
        "  - Attach Files\n"
        "  - Manage Roles (for tracking commands)\n"
        "\n"
        "Ensure the bot has these permissions for smooth operation.\n"
        "\n"
        "**Support:**\n"
    )
    if support_url:
        description += f"- For further assistance or questions, join our [support server]({support_url}) and contact the bot developer."
    else:
        description += "- For further assistance or questions, contact the bot developer."

    embed = discord.Embed(
        title="Manhwa Updates Bot Help",
        colour=discord.Colour.green(),
        description=description,
    )
    _set_mu_footer(embed, bot)
    return embed


def next_update_check_embeds_v1(
    rows: Iterable[tuple[str, int | None]],
    *,
    bot: discord.Client | None,
    page_size: int = 30,
) -> list[discord.Embed]:
    """V1-style /next_update_check embeds, paginated to fit Discord's 4096-char description limit."""
    sorted_rows = sorted(rows, key=lambda r: r[0])
    lines: list[str] = []
    for key, ts in sorted_rows:
        if ts:
            lines.append(f"**{key.title()}** -> <t:{int(ts)}:R>")
        else:
            lines.append(f"**{key.title()}** -> *unknown*")

    if not lines:
        embed = discord.Embed(
            title="🕑 Updates check schedule (max 25 min)",
            description="*No tracked websites.*",
            colour=discord.Colour.green(),
        )
        _set_mu_footer(embed, bot)
        return [embed]

    pages: list[discord.Embed] = []
    total = len(lines)
    total_pages = (total + page_size - 1) // page_size
    for i in range(0, total, page_size):
        chunk = lines[i : i + page_size]
        embed = discord.Embed(
            title="🕑 Updates check schedule (max 25 min)",
            description="\n".join(chunk),
            colour=discord.Colour.green(),
        )
        page_num = i // page_size + 1
        text, icon = mu_footer(bot)
        suffix = f" • Page {page_num}/{total_pages}" if total_pages > 1 else ""
        if icon:
            embed.set_footer(text=f"{text}{suffix}", icon_url=icon)
        else:
            embed.set_footer(text=f"{text}{suffix}")
        pages.append(embed)
    return pages


def next_update_check_embed_v1(
    rows: Iterable[tuple[str, int | None]],
    *,
    bot: discord.Client | None,
) -> discord.Embed:
    """Backwards-compatible single-embed shim — returns the first page only.

    Prefer ``next_update_check_embeds_v1`` for full output (avoids the 4096
    description-length limit).
    """
    embed = discord.Embed(
        title="🕑 Updates check schedule (max 25 min)",
        colour=discord.Colour.green(),
    )
    sorted_rows = sorted(rows, key=lambda r: r[0])
    lines: list[str] = []
    for key, ts in sorted_rows:
        if ts:
            lines.append(f"**{key.title()}** -> <t:{int(ts)}:R>")
        else:
            lines.append(f"**{key.title()}** -> *unknown*")
    embed.description = "\n".join(lines) if lines else "*No tracked websites.*"
    _set_mu_footer(embed, bot)
    return embed


def bookmark_embed_v1(
    *,
    title: str,
    series_url: str,
    website_key: str,
    cover_url: str | None,
    scanlator_base_url: str | None,
    scanlator_icon_url: str | None,
    last_read_chapter: str,
    next_chapter: str | None,
    folder: str,
    available_chapters_label: str,
    chapter_count: int,
    status: str,
    is_completed: bool,
    bot: discord.Client | None,
) -> discord.Embed:
    """V1 'Bookmark: {title}' embed (blurple, set_author, set_image, structured description)."""
    embed = discord.Embed(
        title=f"Bookmark: {title}",
        colour=discord.Colour.blurple(),
        url=series_url,
    )

    if next_chapter:
        next_text = next_chapter
    elif is_completed:
        next_text = f"`None, manhwa is {status.lower() or 'completed'}`"
    else:
        next_text = "`Wait for updates!`"

    available = (
        f"{available_chapters_label} ({chapter_count})\n"
        if chapter_count
        else "`Wait for updates`\n"
    )

    embed.description = (
        f"**Scanlator:** {website_key.title()}\n"
        f"**Last Read Chapter:** {last_read_chapter}\n"
        f"**Next chapter:** {next_text}\n"
        f"**Folder Location:** {folder.title()}\n"
        f"**Available Chapters:** Up to {available}"
        f"**Status:** `{status}`\n"
    )
    embed.set_author(
        name=f"Read on {website_key.title()}",
        url=scanlator_base_url or None,
        icon_url=scanlator_icon_url or None,
    )
    if cover_url:
        embed.set_image(url=cover_url)
    if bot is not None and getattr(bot, "user", None) is not None:
        try:
            embed.set_footer(
                text=str(bot.user.display_name),  # type: ignore[union-attr]
                icon_url=bot.user.display_avatar.url,  # type: ignore[union-attr]
            )
        except Exception:
            pass
    return embed


def bookmark_update_success_embed(
    *,
    moved_folder: str | None,
    new_chapter_label: str | None,
    auto_subscribed_title: str | None,
    should_track: bool,
) -> discord.Embed:
    """V1 'Bookmark Updated' embed."""
    message = "Bookmark updated successfully!"
    if moved_folder:
        message += f"\n\n• Moved bookmark to {moved_folder}"
    if new_chapter_label:
        message += f"\n\n• Updated last read chapter to {new_chapter_label}"
    if auto_subscribed_title:
        message += f"\n\nYou have been subscribed to updates for {auto_subscribed_title}"
    elif should_track:
        message += (
            "\n\n*You should consider tracking and subscribing to this manga to get updates.*"
        )
    return discord.Embed(
        title="Bookmark Updated",
        description=message,
        colour=discord.Colour.green(),
    )
