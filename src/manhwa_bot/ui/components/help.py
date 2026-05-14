"""General-cog layouts: /help, /stats, /patreon, /next_update_check, /translate.

Also exposes link-button action rows (``support_action_rows`` / ``patreon_action_row``)
that replace the legacy ``SupportView`` and ``PatreonView`` classes.
"""

from __future__ import annotations

from collections.abc import Iterable

import discord

from .. import emojis
from .base import (
    LIST_MAX,
    BaseLayoutView,
    footer_section,
    large_separator,
    safe_truncate,
    small_separator,
)

DEFAULT_SUPPORT_URL = "https://discord.gg/TYkw8VBZkr"
DEFAULT_INVITE_URL = (
    "https://discord.com/api/oauth2/authorize?client_id=1031998059447590955"
    "&permissions=412854111296&scope=bot%20applications.commands"
)
DEFAULT_GITHUB_URL = "https://github.com/MooshiMochi/ManhwaUpdatesBot"
DEFAULT_TOS_URL = "https://github.com/MooshiMochi/ManhwaUpdatesBot/blob/master/.discord/terms.md"
DEFAULT_PRIVACY_URL = (
    "https://github.com/MooshiMochi/ManhwaUpdatesBot/blob/master/.discord/privacy.md"
)
DEFAULT_PATREON_URL = "https://www.patreon.com/mooshi69"
DEFAULT_KOFI_URL = "https://ko-fi.com/mooshi69"


# ---------------------------------------------------------------------------
# Link rows
# ---------------------------------------------------------------------------


def support_action_rows(
    *,
    support_url: str | None = DEFAULT_SUPPORT_URL,
    invite_url: str | None = DEFAULT_INVITE_URL,
    github_url: str | None = DEFAULT_GITHUB_URL,
    tos_url: str | None = DEFAULT_TOS_URL,
    privacy_url: str | None = DEFAULT_PRIVACY_URL,
    patreon_url: str | None = DEFAULT_PATREON_URL,
    kofi_url: str | None = DEFAULT_KOFI_URL,
) -> list[discord.ui.ActionRow]:
    rows: list[discord.ui.ActionRow] = []
    primary = discord.ui.ActionRow()
    if support_url:
        primary.add_item(discord.ui.Button(label="Support Server", url=support_url, emoji="💬"))
    if invite_url:
        primary.add_item(discord.ui.Button(label="Invite", url=invite_url, emoji="➕"))
    if github_url:
        primary.add_item(discord.ui.Button(label="GitHub", url=github_url, emoji="🐙"))
    if tos_url:
        primary.add_item(discord.ui.Button(label="ToS", url=tos_url))
    if privacy_url:
        primary.add_item(discord.ui.Button(label="Privacy", url=privacy_url))
    if list(primary.children):
        rows.append(primary)
    donate = discord.ui.ActionRow()
    if patreon_url:
        donate.add_item(discord.ui.Button(label="Patreon", url=patreon_url, emoji="🟧"))
    if kofi_url:
        donate.add_item(discord.ui.Button(label="Ko-fi", url=kofi_url, emoji="☕"))
    if list(donate.children):
        rows.append(donate)
    return rows


def patreon_action_row(
    *,
    patreon_url: str = DEFAULT_PATREON_URL,
    kofi_url: str = DEFAULT_KOFI_URL,
) -> discord.ui.ActionRow:
    row = discord.ui.ActionRow()
    row.add_item(discord.ui.Button(label="Patreon", url=patreon_url, emoji="🟧"))
    row.add_item(discord.ui.Button(label="Ko-fi", url=kofi_url, emoji="☕"))
    return row


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


def build_help_view(
    *,
    bot: discord.Client | None,
    support_url: str | None = None,
    invite_url: str | None = None,
) -> discord.ui.LayoutView:
    """Section-grouped help view (no embed fields — Sections per topic)."""
    support_url = support_url or DEFAULT_SUPPORT_URL

    container = discord.ui.Container(accent_colour=discord.Colour.green())
    container.add_item(discord.ui.TextDisplay("# 📚  Manhwa Updates Bot — Help"))
    container.add_item(small_separator())

    container.add_item(
        discord.ui.TextDisplay(
            "**🚀  Getting Started**\n"
            "• `/settings` — Configure the bot for your server. *(Requires Manage Server)*"
        )
    )
    container.add_item(small_separator())
    container.add_item(
        discord.ui.TextDisplay(
            "**📌  Tracking** *(Requires Manage Roles)*\n"
            "• `/track new` — Begin tracking a manga. Optional `ping_role`.\n"
            "• `/track update` — Update the ping role for a tracked manga.\n"
            "• `/track remove` — Stop tracking; optionally delete the role.\n"
            "• `/track list` — View all tracked manga on the server."
        )
    )
    container.add_item(small_separator())
    container.add_item(
        discord.ui.TextDisplay(
            "**🔔  Subscribing**\n"
            "• `/subscribe new` — Subscribe to a tracked manga.\n"
            "• `/subscribe delete` — Unsubscribe from a manga.\n"
            "• `/subscribe list` — View your subscriptions."
        )
    )
    container.add_item(small_separator())
    container.add_item(
        discord.ui.TextDisplay(
            "**🔖  Bookmarks**\n"
            "• `/bookmark new` · `view` · `update` · `delete` — Manage your reading list."
        )
    )
    container.add_item(small_separator())
    container.add_item(
        discord.ui.TextDisplay(
            "**🔎  Discovery & Info**\n"
            "• `/search` — Search a manga by title.\n"
            "• `/info` — Show series info.\n"
            "• `/chapters` — List chapters.\n"
            "• `/supported_websites` — Browse supported sites.\n"
            "• `/next_update_check` — Next scheduled update check.\n"
            "• `/translate` — Translate text.\n"
            "• `/stats` · `/patreon` — Bot info."
        )
    )
    container.add_item(small_separator())
    container.add_item(
        discord.ui.TextDisplay(
            "**🛡️  Permissions Needed**\n"
            "Send Messages • Embed Links • Attach Files • Manage Roles (for tracking)"
        )
    )
    if support_url:
        container.add_item(small_separator())
        container.add_item(
            discord.ui.TextDisplay(
                f"**🤝  Support**\nJoin the [support server]({support_url}) for help."
            )
        )
    container.add_item(small_separator())
    container.add_item(footer_section(bot))

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    for row in support_action_rows(support_url=support_url, invite_url=invite_url):
        view.add_item(row)
    return view


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------


def build_stats_view(
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
) -> discord.ui.LayoutView:
    """V2 stats panel — grid-style Section list inside a teal Container."""
    rows = [
        ("🔖  Bookmarks", bookmarks_count),
        ("📚  Tracked Manhwas", tracks_count),
        ("👥  Users subbed to Manhwa", subs_count),
        ("📘  Total Manhwas", manhwa_count),
        ("🔍  Supported Websites", websites_count),
        ("🌐  Total Servers", guilds_count),
        ("👤  Total Users", users_count),
    ]
    grid = "\n".join(f"**{name}:** `{value}`" for name, value in rows)
    grid += f"\n**⌛  Total Uptime:** <t:{start_unix}:R>\n**🐣  Born:** <t:{bot_created_unix}:R>"

    container = discord.ui.Container(
        discord.ui.TextDisplay("# 📊  Manhwa Updates Bot Statistics"),
        small_separator(),
        discord.ui.TextDisplay(grid),
        small_separator(),
        footer_section(bot, extra="Stats"),
        accent_colour=discord.Colour(0x1ABC9C),
    )

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


# ---------------------------------------------------------------------------
# /patreon
# ---------------------------------------------------------------------------


def build_patreon_view(*, bot: discord.Client | None) -> discord.ui.LayoutView:
    body = (
        "You can donate to our [Patreon](https://www.patreon.com/mooshi69) or "
        "[Ko-fi](https://ko-fi.com/mooshi69) to support the server and the development. "
        "I have been working on the Manhwa Updates bot for just over 1 year now and have "
        "tried my best to make your manhwa reading experience the best that it can be. "
        "By becoming a Patreon you can support my work and pay for the server cost.\n\n"
        "Manage your Patreon subscription using this command to view your patreon status and "
        "change your custom embed color. Subscriptions may take up to `10 minutes` to refresh. "
        "Also make sure your Discord account is linked with Patreon."
    )

    tiers = [
        (
            '"Hello World" Supporter (£3/month)',
            (
                '• Get the `"Hello World" Supporter` role in the support server.\n'
                "• Get access to bot commands in DMs.\n"
                "• Help fund the server and the development."
            ),
        ),
        (
            "Bot Whisperer (£5/month)",
            (
                "• Get the `Bot Whisperer` role in the support server.\n"
                "• Get access to bot commands in DMs.\n"
                "• Help fund the server and the development."
            ),
        ),
        (
            "The Full Stack (£10/month)",
            (
                "• Get `The Full Stack` role in the support server.\n"
                "• Get access to bot commands in DMs.\n"
                "• Help fund the server and the development."
            ),
        ),
    ]

    container = discord.ui.Container(
        discord.ui.TextDisplay("# 🟧  Patreon"),
        small_separator(),
        discord.ui.TextDisplay(body),
        accent_colour=discord.Colour.gold(),
    )
    for name, value in tiers:
        container.add_item(small_separator())
        container.add_item(discord.ui.TextDisplay(f"**{name}**\n{value}"))
    container.add_item(small_separator())
    container.add_item(footer_section(bot))

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    view.add_item(patreon_action_row())
    return view


# ---------------------------------------------------------------------------
# /next_update_check
# ---------------------------------------------------------------------------


def build_next_update_check_views(
    rows: Iterable[tuple[str, int | None]],
    *,
    bot: discord.Client | None,
    page_size: int = 30,
    invoker_id: int | None = None,
) -> list[discord.ui.LayoutView]:
    sorted_rows = sorted(rows, key=lambda r: r[0])
    lines: list[str] = []
    for key, ts in sorted_rows:
        if ts:
            lines.append(f"**{key.title()}** → <t:{int(ts)}:R>")
        else:
            lines.append(f"**{key.title()}** → *unknown*")

    title = "# 🕑  Update check schedule (max 25 min)"

    if not lines:
        container = discord.ui.Container(
            discord.ui.TextDisplay(title),
            small_separator(),
            discord.ui.TextDisplay("*No tracked websites.*"),
            large_separator(),
            footer_section(bot),
            accent_colour=discord.Colour.green(),
        )
        view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
        view.add_item(container)
        return [view]

    pages: list[discord.ui.LayoutView] = []
    total = len(lines)
    total_pages = (total + page_size - 1) // page_size
    for i in range(0, total, page_size):
        chunk = lines[i : i + page_size]
        page_num = i // page_size + 1
        body = safe_truncate("\n".join(chunk), LIST_MAX)
        container = discord.ui.Container(
            discord.ui.TextDisplay(title),
            small_separator(),
            discord.ui.TextDisplay(body),
            small_separator(),
            footer_section(
                bot, extra=(f"Page {page_num}/{total_pages}" if total_pages > 1 else None)
            ),
            accent_colour=discord.Colour.green(),
        )
        view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
        view.add_item(container)
        pages.append(view)
    return pages


# ---------------------------------------------------------------------------
# /translate
# ---------------------------------------------------------------------------


def build_translation_view(
    *,
    text: str,
    translated: str,
    lang_from: str,
    lang_to: str,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    head = f"## 🈳  Translation\n`{lang_from}` ⟶ `{lang_to}`"
    inp = safe_truncate(text, 1000)
    out = safe_truncate(translated, 1000)

    container = discord.ui.Container(
        discord.ui.TextDisplay(head),
        small_separator(),
        discord.ui.TextDisplay(f"**📥 Input**\n```{inp}```"),
        small_separator(),
        discord.ui.TextDisplay(f"**📤 Result**\n```{out}```"),
        small_separator(),
        footer_section(bot),
        accent_colour=discord.Colour.blurple(),
    )

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


# ---------------------------------------------------------------------------
# /get_lost_manga
# ---------------------------------------------------------------------------


def build_lost_manga_view(
    *,
    entries_count: int,
    lost_websites: int,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    plural_e = "y" if entries_count == 1 else "ies"
    plural_w = "" if lost_websites == 1 else "s"
    body = (
        f"**{entries_count}** entr{plural_e} from **{lost_websites}** lost website{plural_w}."
        "\nDownload the TSV attached above to see the full list."
    )
    container = discord.ui.Container(
        discord.ui.TextDisplay("## 🗺️  Lost Manga Export"),
        small_separator(),
        discord.ui.TextDisplay(body),
        small_separator(),
        footer_section(bot),
        accent_colour=discord.Colour.orange(),
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def build_no_lost_manga_view(*, bot: discord.Client | None = None) -> discord.ui.LayoutView:
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {emojis.CHECK}  All clear"),
        small_separator(),
        discord.ui.TextDisplay(
            "No lost entries found — all your series are on supported websites."
        ),
        small_separator(),
        footer_section(bot),
        accent_colour=discord.Colour.green(),
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view
