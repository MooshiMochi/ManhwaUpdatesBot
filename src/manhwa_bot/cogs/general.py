"""General cog — /help, /stats, /get_lost_manga, /patreon,
/next_update_check, /translate, and Translate context menus.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ..checks import PREMIUM_REQUIRED
from ..crawler.errors import CrawlerError, Disconnected, RequestTimeout
from ..i18n import google_translate
from ..i18n.google_translate import TranslateError

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)


async def _premium_dm_only_predicate(interaction: discord.Interaction) -> bool:
    """Predicate for context-menu premium gate (dm_only=True semantics)."""
    bot: Any = interaction.client
    ok, _ = await bot.premium.is_premium(
        user_id=interaction.user.id,
        guild_id=interaction.guild.id if interaction.guild else None,
        interaction=interaction,
        dm_only=True,
    )
    if not ok:
        raise app_commands.CheckFailure(PREMIUM_REQUIRED)
    return True


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(title="Error", description=message, colour=discord.Colour.red())


def _format_uptime(delta: Any) -> str:
    total_seconds = int(delta.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts) or "0m"


async def _get_lost_entries(bot: Any) -> list[dict]:
    """Return a list of dicts representing series/bookmarks on unsupported websites.

    Each dict has keys: kind, website_key, url_name, title, series_url, last_read_chapter.
    """
    ttl = bot.config.supported_websites_cache.ttl_seconds

    async def _loader() -> list[dict]:
        d = await bot.crawler.request("supported_websites")
        return d.get("websites") or []

    try:
        websites: list[dict] = await bot.websites_cache.get_or_set("websites_full", _loader, ttl)
    except (CrawlerError, RequestTimeout, Disconnected):
        websites = []

    supported: set[str] = {w["key"] for w in websites if w.get("key")}

    pool = bot.db

    tracked_keys_rows = await pool.fetchall("SELECT DISTINCT website_key FROM tracked_series")
    bookmark_keys_rows = await pool.fetchall("SELECT DISTINCT website_key FROM bookmarks")

    all_keys: set[str] = {r["website_key"] for r in tracked_keys_rows} | {
        r["website_key"] for r in bookmark_keys_rows
    }
    lost_keys = all_keys - supported

    if not lost_keys:
        return []

    placeholders = ",".join("?" * len(lost_keys))
    lost_list = list(lost_keys)

    entries: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    # Tracked series on lost websites
    tracked_rows = await pool.fetchall(
        f"SELECT website_key, url_name, title, series_url FROM tracked_series"
        f" WHERE website_key IN ({placeholders})",
        tuple(lost_list),
    )
    for r in tracked_rows:
        key = ("tracked", r["website_key"], r["url_name"])
        if key not in seen:
            seen.add(key)
            entries.append(
                {
                    "kind": "tracked",
                    "website_key": r["website_key"],
                    "url_name": r["url_name"],
                    "title": r["title"],
                    "series_url": r["series_url"],
                    "last_read_chapter": "",
                }
            )

    # Bookmarks on lost websites (LEFT JOIN tracked_series for title/series_url)
    bookmark_rows = await pool.fetchall(
        f"""
        SELECT b.website_key, b.url_name, b.last_read_chapter,
               ts.title, ts.series_url
        FROM bookmarks b
        LEFT JOIN tracked_series ts USING (website_key, url_name)
        WHERE b.website_key IN ({placeholders})
        """,
        tuple(lost_list),
    )
    for r in bookmark_rows:
        key = ("bookmark", r["website_key"], r["url_name"])
        if key not in seen:
            seen.add(key)
            entries.append(
                {
                    "kind": "bookmark",
                    "website_key": r["website_key"],
                    "url_name": r["url_name"],
                    "title": r["title"] or r["url_name"],
                    "series_url": r["series_url"] or "",
                    "last_read_chapter": r["last_read_chapter"] or "",
                }
            )

    return entries


def _build_tsv(entries: list[dict]) -> bytes:
    header = "kind\twebsite_key\turl_name\ttitle\tseries_url\tlast_read_chapter\n"
    rows = [
        "\t".join(
            [
                e["kind"],
                e["website_key"],
                e["url_name"],
                e["title"],
                e["series_url"],
                e["last_read_chapter"],
            ]
        )
        for e in entries
    ]
    return (header + "\n".join(rows)).encode("utf-8")


class _TranslateToModal(discord.ui.Modal, title="Translate to…"):
    target_lang: discord.ui.TextInput = discord.ui.TextInput(
        label="Target language",
        placeholder="e.g. fr, de, ja, Spanish",
        max_length=20,
        required=True,
    )

    def __init__(self, message_content: str, session_getter: Any) -> None:
        super().__init__()
        self._content = message_content
        self._session_getter = session_getter

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        target = self.target_lang.value.strip() or "en"
        try:
            translated, detected = await google_translate.translate(
                self._content,
                target=target,
                session=self._session_getter(),
            )
        except TranslateError as exc:
            await interaction.followup.send(embed=_error_embed(str(exc)), ephemeral=True)
            return

        embed = _translate_embed(
            original=self._content,
            translated=translated,
            source_lang=detected,
            target_lang=target,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


def _translate_embed(
    original: str,
    translated: str,
    source_lang: str,
    target_lang: str,
) -> discord.Embed:
    embed = discord.Embed(title="Translation", colour=discord.Colour.blurple())
    embed.add_field(name="From", value=source_lang, inline=True)
    embed.add_field(name="To", value=target_lang, inline=True)
    embed.add_field(name="Original", value=original[:1024], inline=False)
    embed.add_field(name="Translation", value=translated[:1024], inline=False)
    return embed


class GeneralCog(commands.Cog, name="General"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._http_session: aiohttp.ClientSession | None = None

        # Context menus must be registered on the tree manually (not via cog commands)
        self._translate_ctx = app_commands.ContextMenu(
            name="Translate",
            callback=self._translate_message_ctx,
        )
        self._translate_to_ctx = app_commands.ContextMenu(
            name="Translate to…",
            callback=self._translate_to_ctx_handler,
        )
        # Apply premium gate to both context menus
        for cm in (self._translate_ctx, self._translate_to_ctx):
            cm.add_check(_premium_dm_only_predicate)
            bot.tree.add_command(cm)

    async def cog_unload(self) -> None:
        for cm in (self._translate_ctx, self._translate_to_ctx):
            self.bot.tree.remove_command(cm.name, type=cm.type)
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    def _session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    # -- /help -----------------------------------------------------------

    @app_commands.command(name="help", description="Get started with Manhwa Updates Bot.")
    async def help(self, interaction: discord.Interaction) -> None:
        bot: Any = self.bot
        support_url: str | None = getattr(
            getattr(bot.config, "support", None), "invite_url", None
        )
        invite_url: str | None = getattr(getattr(bot.config, "support", None), "invite_bot_url", None)

        description = (
            "**Getting Started:**\n"
            "- Before using the bot, configure it for your server:\n"
            "  - `/settings` — See and edit all the bot's settings for your server. "
            "*(Requires the `Manage Server` permission)*\n"
            "\n"
            "**Tracking Manhwa:**\n"
            "*(Requires the `Manage Roles` permission)*\n"
            "- Start receiving updates by tracking your favourite manhwa:\n"
            "  - `/track new` — Begin tracking a new manhwa. Paste a URL, use the "
            "`website_key|url` format, or pick a suggestion from autocomplete. "
            "Optionally specify a `ping_role` to be notified.\n"
            "  - `/track update` — Change the ping role for a tracked manhwa.\n"
            "  - `/track remove` — Stop tracking a manhwa. Use `delete_role` to also "
            "remove the associated role.\n"
            "  - `/track list` — View all tracked manhwa in this server.\n"
            "\n"
            "**Subscribing to Manhwa:**\n"
            "- Once a manhwa is being tracked, users can subscribe to update pings:\n"
            "  - `/subscribe new` — Subscribe to a tracked manhwa.\n"
            "  - `/subscribe delete` — Unsubscribe from a manhwa.\n"
            "  - `/subscribe list` — View your subscriptions.\n"
            "\n"
            "**Bookmarking:**\n"
            "- Personal bookmarks (works in DMs for premium users):\n"
            "  - `/bookmark new` — Bookmark a manga at a specific chapter.\n"
            "  - `/bookmark view` — View one of your bookmarks.\n"
            "  - `/bookmark update` — Update a bookmark's last-read chapter.\n"
            "  - `/bookmark delete` — Delete a bookmark.\n"
            "\n"
            "**General Commands:**\n"
            "- `/help` — This message.\n"
            "- `/search` — Search for a manga across supported websites.\n"
            "- `/info` — Display detailed info about a manga.\n"
            "- `/chapters` — Get a list of chapters for a manga.\n"
            "- `/supported_websites` — List the websites the crawler currently supports.\n"
            "- `/next_update_check` — Show when each website is next checked for updates.\n"
            "- `/get_lost_manga` — Export your tracked / bookmarked entries on websites that "
            "are no longer supported.\n"
            "- `/translate` — Translate any text from one language to another.\n"
            "- `/stats` — View general bot statistics.\n"
            "- `/patreon` — Support the bot and unlock premium features.\n"
            "\n"
            "**Permissions:**\n"
            "- The bot needs these permissions for smooth operation:\n"
            "  - Send Messages, Embed Links, Attach Files, Use External Emojis\n"
            "  - Manage Roles *(for `/track` commands)*\n"
        )
        if support_url:
            description += (
                f"\n**Support:**\n"
                f"- For further assistance or questions, join our "
                f"[support server]({support_url}) and contact the bot developer.\n"
            )

        embed = discord.Embed(
            title="Manhwa Updates Bot Help",
            description=description.strip(),
            colour=discord.Colour.green(),
        )
        avatar_url = bot.user.display_avatar.url if bot.user else None
        embed.set_footer(
            text="Manhwa Updates",
            icon_url=avatar_url,
        )

        view: discord.ui.View | None = None
        if support_url or invite_url:
            view = discord.ui.View(timeout=None)
            if support_url:
                view.add_item(discord.ui.Button(label="Support Server", url=support_url))
            if invite_url:
                view.add_item(discord.ui.Button(label="Invite", url=invite_url))

        if view is not None:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # -- /stats ----------------------------------------------------------

    @app_commands.command(name="stats", description="Show bot statistics and uptime")
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)

        bot: Any = self.bot
        pool = bot.db

        bookmark_row = await pool.fetchone("SELECT COUNT(*) AS cnt FROM bookmarks")
        tracked_row = await pool.fetchone("SELECT COUNT(*) AS cnt FROM tracked_series")
        user_row = await pool.fetchone(
            """
            SELECT COUNT(DISTINCT user_id) AS cnt FROM (
                SELECT user_id FROM bookmarks
                UNION
                SELECT user_id FROM subscriptions
            )
            """
        )

        bookmarks_total = bookmark_row["cnt"] if bookmark_row else 0
        tracked_total = tracked_row["cnt"] if tracked_row else 0
        users_total = user_row["cnt"] if user_row else 0
        guild_count = len(bot.guilds)
        uptime = _format_uptime(datetime.now(UTC) - bot.started_at)

        embed = discord.Embed(title="Bot Statistics", colour=discord.Colour.blurple())
        embed.add_field(name="Guilds", value=str(guild_count), inline=True)
        embed.add_field(name="Tracked Series", value=str(tracked_total), inline=True)
        embed.add_field(name="Bookmarks", value=str(bookmarks_total), inline=True)
        embed.add_field(name="Users (est.)", value=str(users_total), inline=True)
        embed.add_field(name="Uptime", value=uptime, inline=True)
        await interaction.followup.send(embed=embed)

    # -- /get_lost_manga -------------------------------------------------

    @app_commands.command(
        name="get_lost_manga",
        description="Export series/bookmarks from websites no longer supported by the crawler",
    )
    async def get_lost_manga(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        entries = await _get_lost_entries(self.bot)

        if not entries:
            await interaction.followup.send(
                embed=discord.Embed(
                    description="No lost entries found — all your series are on supported websites.",
                    colour=discord.Colour.green(),
                ),
                ephemeral=True,
            )
            return

        lost_websites = len({e["website_key"] for e in entries})
        tsv_bytes = _build_tsv(entries)

        embed = discord.Embed(
            title="Lost Manga Export",
            description=(
                f"**{len(entries)}** entr{'y' if len(entries) == 1 else 'ies'}"
                f" from **{lost_websites}** lost website{'s' if lost_websites != 1 else ''}."
                "\nDownload the TSV below to see the full list."
            ),
            colour=discord.Colour.orange(),
        )
        await interaction.followup.send(
            embed=embed,
            file=discord.File(io.BytesIO(tsv_bytes), filename="lost_manga.tsv"),
            ephemeral=True,
        )

    # -- /translate ------------------------------------------------------

    async def _autocomplete_lang(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return _lang_autocomplete(current)

    @app_commands.command(name="translate", description="Translate text using Google Translate")
    @app_commands.describe(
        text="The text to translate",
        to="Target language code or name (default: en)",
        from_="Source language code or name (default: auto-detect)",
    )
    @app_commands.autocomplete(to=_autocomplete_lang, from_=_autocomplete_lang)
    async def translate(
        self,
        interaction: discord.Interaction,
        text: str,
        to: str = "en",
        from_: str = "auto",
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            translated, detected = await google_translate.translate(
                text, target=to, source=from_, session=self._session()
            )
        except TranslateError as exc:
            await interaction.followup.send(embed=_error_embed(str(exc)), ephemeral=True)
            return

        embed = _translate_embed(
            original=text,
            translated=translated,
            source_lang=detected,
            target_lang=to,
        )
        await interaction.followup.send(embed=embed)

    # -- /patreon --------------------------------------------------------

    @app_commands.command(name="patreon", description="Support the bot on Patreon")
    async def patreon(self, interaction: discord.Interaction) -> None:
        bot: Any = self.bot
        pledge_url: str = bot.config.premium.patreon.pledge_url

        embed = discord.Embed(
            title="Support on Patreon",
            colour=discord.Colour.from_str("#FF424D"),
        )
        if pledge_url:
            embed.description = (
                f"Support the bot and unlock premium features!\n\n"
                f"[**Become a Patron →**]({pledge_url})"
            )
            embed.url = pledge_url
        else:
            embed.description = (
                "Support the bot on Patreon to unlock premium features!\n"
                "Ask the bot owner for the Patreon link."
            )
        embed.add_field(
            name="What you get",
            value=(
                "• Access to premium commands in DMs\n"
                "• Early access to new features\n"
                "• Support ongoing development"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    # -- /next_update_check ----------------------------------------------

    @app_commands.command(
        name="next_update_check",
        description="Show the next update-check time for each website.",
    )
    @app_commands.describe(
        show_all=(
            "Show all supported websites instead of only the ones tracked in this server."
        )
    )
    async def next_update_check(
        self,
        interaction: discord.Interaction,
        show_all: bool = False,
    ) -> None:
        await interaction.response.defer(thinking=True)
        bot: Any = self.bot

        website_keys: list[str] | None = None
        if not show_all and interaction.guild is not None:
            try:
                pool = bot.db
                rows = await pool.fetchall(
                    "SELECT DISTINCT website_key FROM tracked_series WHERE guild_id = ?",
                    (interaction.guild.id,),
                )
                guild_keys = sorted({r["website_key"] for r in rows if r["website_key"]})
                if guild_keys:
                    website_keys = guild_keys
                else:
                    show_all = True  # nothing tracked yet — fall through to global view
            except Exception:
                _log.exception("Failed to load tracked website keys for guild")
                website_keys = None

        try:
            if website_keys is not None:
                data = await bot.crawler.request("next_update_check", website_keys=website_keys)
            else:
                data = await bot.crawler.request("next_update_check")
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await interaction.followup.send(
                embed=_error_embed(f"Couldn't reach the crawler: {exc}"),
                ephemeral=True,
            )
            return

        websites: list[dict] = data.get("websites") or []
        interval_minutes = int(data.get("interval_minutes") or 25)
        backup_hours = int(data.get("backup_interval_hours") or 4)

        if not websites:
            embed = discord.Embed(
                title="🕑 Update check schedule",
                description=(
                    "No websites are tracked in this server yet."
                    " Use `/track new` to start tracking — or run this command with `show_all: True`."
                ),
                colour=discord.Colour.greyple(),
            )
            await interaction.followup.send(embed=embed)
            return

        sorted_sites = sorted(websites, key=lambda w: str(w.get("website_key") or ""))
        lines: list[str] = []
        for idx, site in enumerate(sorted_sites, start=1):
            key = site.get("website_key") or "?"
            next_iso = site.get("next_check_at")
            if next_iso:
                try:
                    next_dt = datetime.fromisoformat(next_iso.replace("Z", "+00:00"))
                    unix = int(next_dt.timestamp())
                    line = f"`{idx:>2}. {key}:` <t:{unix}:R>"
                except ValueError:
                    line = f"`{idx:>2}. {key}:` *unknown*"
            else:
                line = f"`{idx:>2}. {key}:` *unknown*"
            lines.append(line)

        # Two-column layout when ≥ 8 entries.
        if len(lines) >= 8:
            mid = (len(lines) + 1) // 2
            col_left = "\n".join(lines[:mid])
            col_right = "\n".join(lines[mid:])
            embed = discord.Embed(
                title="🕑 Update check schedule",
                colour=discord.Colour.green(),
            )
            embed.add_field(name="Websites", value=col_left or "—", inline=True)
            embed.add_field(name="​", value=col_right or "—", inline=True)
        else:
            embed = discord.Embed(
                title="🕑 Update check schedule",
                description="\n".join(lines),
                colour=discord.Colour.green(),
            )

        embed.set_footer(
            text=(
                f"Main check: every {interval_minutes} min  •  "
                f"Backup: every {backup_hours} h"
            )
        )
        await interaction.followup.send(embed=embed)

    # -- Context menus ---------------------------------------------------

    async def _translate_message_ctx(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> None:
        content = message.content.strip()
        if not content:
            await interaction.response.send_message(
                embed=_error_embed("That message has no text content to translate."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            translated, detected = await google_translate.translate(
                content, target="en", session=self._session()
            )
        except TranslateError as exc:
            await interaction.followup.send(embed=_error_embed(str(exc)), ephemeral=True)
            return

        embed = _translate_embed(
            original=content,
            translated=translated,
            source_lang=detected,
            target_lang="en",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _translate_to_ctx_handler(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> None:
        content = message.content.strip()
        if not content:
            await interaction.response.send_message(
                embed=_error_embed("That message has no text content to translate."),
                ephemeral=True,
            )
            return

        modal = _TranslateToModal(content, self._session)
        await interaction.response.send_modal(modal)


def _lang_autocomplete(current: str) -> list[app_commands.Choice[str]]:
    choices = google_translate.language_choices(current)
    return [app_commands.Choice(name=f"{name} ({code})", value=code) for code, name in choices]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GeneralCog(bot))
