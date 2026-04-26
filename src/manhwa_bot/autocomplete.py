"""App-command autocomplete handlers.

All handlers return ``[]`` on errors — Discord shows "no choices" rather than
surfacing an exception to the user.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)


async def tracked_manga_in_guild(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Manga tracked in the invoker's guild, filtered by *current* substring.

    Choice value: ``"{website_key}:{url_name}"``.
    Choice name:  ``"{title} ({website_key})"``.
    """
    if interaction.guild is None:
        return []
    try:
        bot: Any = interaction.client
        from .db.tracked import TrackedStore

        store = TrackedStore(bot.db)
        rows = await store.list_for_guild(interaction.guild.id, limit=100)
        choices: list[app_commands.Choice[str]] = []
        lower = current.lower()
        for row in rows:
            label = f"{row.title} ({row.website_key})"
            value = f"{row.website_key}:{row.url_name}"
            if lower and lower not in label.lower() and lower not in value.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=value[:100]))
            if len(choices) >= 25:
                break
        return choices
    except Exception:
        _log.exception("tracked_manga_in_guild autocomplete failed")
        return []


async def user_subscribed_manga(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Manga the invoker is subscribed to in this guild."""
    if interaction.guild is None:
        return []
    try:
        bot: Any = interaction.client
        from .db.subscriptions import SubscriptionStore

        store = SubscriptionStore(bot.db)
        rows = await store.list_for_user(
            interaction.user.id, guild_id=interaction.guild.id, limit=100
        )
        choices: list[app_commands.Choice[str]] = []
        lower = current.lower()
        for row in rows:
            website_key = row["website_key"]
            url_name = row["url_name"]
            label = f"{url_name} ({website_key})"
            value = f"{website_key}:{url_name}"
            if lower and lower not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=value[:100]))
            if len(choices) >= 25:
                break
        return choices
    except Exception:
        _log.exception("user_subscribed_manga autocomplete failed")
        return []


async def user_bookmarks(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Bookmarks belonging to the invoker."""
    try:
        bot: Any = interaction.client
        from .db.bookmarks import BookmarkStore

        store = BookmarkStore(bot.db)
        rows = await store.list_user_bookmarks(interaction.user.id, limit=100)
        choices: list[app_commands.Choice[str]] = []
        lower = current.lower()
        for bm in rows:
            label = f"{bm.url_name} ({bm.website_key})"
            value = f"{bm.website_key}:{bm.url_name}"
            if lower and lower not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=value[:100]))
            if len(choices) >= 25:
                break
        return choices
    except Exception:
        _log.exception("user_bookmarks autocomplete failed")
        return []


async def supported_website_keys(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Website keys from the crawler's ``supported_websites`` op (TTL-cached)."""
    try:
        bot: Any = interaction.client
        ttl = bot.config.supported_websites_cache.ttl_seconds

        async def _loader() -> list[str]:
            data = await bot.crawler.request("supported_websites")
            return [
                w.get("key") or w.get("website_key")
                for w in data.get("websites", [])
                if w.get("key") or w.get("website_key")
            ]

        keys: list[str] = await bot.websites_cache.get_or_set("websites", _loader, ttl)
        lower = current.lower()
        choices = [
            app_commands.Choice(name=k, value=k) for k in keys if not lower or lower in k.lower()
        ]
        return choices[:25]
    except Exception:
        _log.exception("supported_website_keys autocomplete failed")
        return []


async def track_new_url_or_search(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """When typing a URL, returns the URL itself; otherwise live-searches the crawler.

    Choice value format for search results: ``"{website_key}|{series_url}"``.
    """
    if not current:
        return []
    try:
        # If it looks like a URL, offer it as-is.
        if current.startswith("http://") or current.startswith("https://"):
            return [app_commands.Choice(name=current[:100], value=current[:100])]

        bot: Any = interaction.client
        data = await bot.crawler.request("search", query=current, limit=10)
        results: list[dict] = data.get("results") or []
        choices: list[app_commands.Choice[str]] = []
        for r in results:
            website_key = r.get("website_key") or ""
            series_url = r.get("series_url") or r.get("url") or ""
            title = r.get("title") or series_url
            if not website_key or not series_url:
                continue
            value = f"{website_key}|{series_url}"
            name = f"{title} ({website_key})"
            choices.append(app_commands.Choice(name=name[:100], value=value[:100]))
            if len(choices) >= 10:
                break
        return choices
    except Exception:
        _log.exception("track_new_url_or_search autocomplete failed")
        return []
