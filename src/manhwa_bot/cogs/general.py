"""General cog — /help, /stats, /get_lost_manga, /patreon,
/next_update_check, /translate, and Translate context menus.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from .. import formatting
from ..checks import PREMIUM_REQUIRED
from ..crawler.errors import CrawlerError, Disconnected, RequestTimeout
from ..i18n import google_translate
from ..i18n.google_translate import TranslateError
from ..ui.paginator import Paginator
from ..ui.support_view import PatreonView, SupportView

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
    except CrawlerError, RequestTimeout, Disconnected:
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


def _resolve_lang_label(code: str) -> str:
    """Return the human-readable language name for a Google Translate code."""
    if not code:
        return "Unknown"
    if code == "auto":
        return "Auto"
    name = google_translate._LANGUAGES.get(code.lower())  # type: ignore[attr-defined]
    return name or code


def _translate_embed(
    original: str,
    translated: str,
    source_lang: str,
    target_lang: str,
) -> discord.Embed:
    return formatting.translation_embed(
        text=original,
        translated=translated,
        lang_from=_resolve_lang_label(source_lang),
        lang_to=_resolve_lang_label(target_lang),
    )


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
        support_cfg = getattr(bot.config, "support", None)
        support_url = getattr(support_cfg, "invite_url", None) or None
        invite_url = getattr(support_cfg, "invite_bot_url", None) or None

        embed = formatting.help_embed(bot=bot, support_url=support_url)
        view = SupportView(
            support_url=support_url,
            invite_url=invite_url,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # -- /stats ----------------------------------------------------------

    @app_commands.command(name="stats", description="Get some basic info and stats about the bot.")
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        bot: Any = self.bot
        pool = bot.db

        bookmark_row = await pool.fetchone("SELECT COUNT(*) AS cnt FROM bookmarks")
        tracked_row = await pool.fetchone(
            "SELECT COUNT(DISTINCT website_key || '-' || url_name) AS cnt FROM tracked_in_guild"
        )
        manhwa_row = await pool.fetchone("SELECT COUNT(*) AS cnt FROM tracked_series")
        subs_row = await pool.fetchone("SELECT COUNT(*) AS cnt FROM subscriptions")
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
        manhwa_total = manhwa_row["cnt"] if manhwa_row else 0
        subs_total = subs_row["cnt"] if subs_row else 0
        users_total = user_row["cnt"] if user_row else 0
        guild_count = len(bot.guilds)

        try:
            ws_data = await bot.crawler.request("supported_websites")
            websites_count = len(ws_data.get("websites") or [])
        except CrawlerError, RequestTimeout, Disconnected:
            websites_count = 0

        bot_user = bot.user
        bot_created_unix = (
            int(bot_user.created_at.timestamp()) if bot_user and bot_user.created_at else 0
        )
        start_unix = int(bot.started_at.timestamp())

        embed = formatting.stats_embed(
            bookmarks_count=bookmarks_total,
            tracks_count=tracked_total,
            subs_count=subs_total,
            manhwa_count=manhwa_total,
            websites_count=websites_count,
            guilds_count=guild_count,
            users_count=users_total,
            start_unix=start_unix,
            bot_created_unix=bot_created_unix,
            bot=bot,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

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

    @app_commands.command(
        name="translate", description="Translate any text from one language to another"
    )
    @app_commands.describe(
        text="The text to translate",
        to="The language to translate to",
        from_="The language to translate from",
    )
    @app_commands.autocomplete(to=_autocomplete_lang, from_=_autocomplete_lang)
    @app_commands.rename(from_="from")
    async def translate(
        self,
        interaction: discord.Interaction,
        text: str,
        to: str = "en",
        from_: str = "auto",
    ) -> None:
        if len(text) > 2000:
            await interaction.response.send_message(
                "The text is too long to translate. Max character limit is 2000.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
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
        await interaction.followup.send(embed=embed, ephemeral=True)

    # -- /patreon --------------------------------------------------------

    @app_commands.command(
        name="patreon",
        description="Help fund the server and manage your current patreon subscription",
    )
    async def patreon(self, interaction: discord.Interaction) -> None:
        bot: Any = self.bot
        pledge_url: str = (
            bot.config.premium.patreon.pledge_url or "https://www.patreon.com/mooshi69"
        )
        embed = formatting.patreon_embed(bot=bot)
        if pledge_url:
            embed.url = pledge_url
        view = PatreonView(patreon_url=pledge_url)
        await interaction.response.send_message(embed=embed, view=view)

    # -- /next_update_check ----------------------------------------------

    @app_commands.command(
        name="next_update_check",
        description="Get the time of the next update check.",
    )
    @app_commands.describe(
        show_all="Whether to show the next update check for all scanlators supported by the bot."
    )
    async def next_update_check(
        self,
        interaction: discord.Interaction,
        show_all: bool = False,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        bot: Any = self.bot

        website_keys: list[str] | None = None
        if not show_all and interaction.guild is not None:
            try:
                pool = bot.db
                rows = await pool.fetchall(
                    """
                    SELECT DISTINCT ts.website_key
                    FROM tracked_in_guild tig
                    JOIN tracked_series ts USING (website_key, url_name)
                    WHERE tig.guild_id = ?
                    """,
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

        rows_for_embed: list[tuple[str, int | None]] = []
        for site in websites:
            key = str(site.get("website_key") or "").strip()
            if not key:
                continue
            next_iso = site.get("next_check_at")
            ts: int | None = None
            if next_iso:
                try:
                    dt = datetime.fromisoformat(str(next_iso).replace("Z", "+00:00"))
                    ts = int(dt.timestamp())
                except ValueError:
                    ts = None
            rows_for_embed.append((key, ts))

        embeds = formatting.next_update_check_embeds_v1(rows_for_embed, bot=bot)
        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0], ephemeral=True)
        else:
            paginator = Paginator(embeds, invoker_id=interaction.user.id)
            await interaction.followup.send(embed=embeds[0], view=paginator, ephemeral=True)

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
