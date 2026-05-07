"""App-command autocomplete handlers.

All handlers return ``[]`` on errors — Discord shows "no choices" rather than
surfacing an exception to the user.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)
TRACK_NEW_AUTOCOMPLETE_CACHE_TTL_SECONDS = 20.0
_track_new_autocomplete_cache: dict[str, tuple[float, list[app_commands.Choice[str]]]] = {}
_track_new_autocomplete_inflight: dict[str, asyncio.Task[list[app_commands.Choice[str]]]] = {}


@dataclass(frozen=True)
class _ParsedAutocompleteInput:
    website_key_prefix: str | None
    title_query: str


def _parse_autocomplete_input(current: str) -> _ParsedAutocompleteInput:
    clean = str(current or "").strip()
    if not clean.startswith("("):
        return _ParsedAutocompleteInput(website_key_prefix=None, title_query=clean)
    raw_prefix, _, title_query = clean[1:].partition(" ")
    return _ParsedAutocompleteInput(
        website_key_prefix=raw_prefix.rstrip(")").strip() or None,
        title_query=title_query.strip(),
    )


def _manga_choice_name(website_key: str, title: str) -> str:
    return f"({website_key}) {title}"


def _matches_manga_autocomplete(website_key: str, title: str, current: str) -> bool:
    parsed = _parse_autocomplete_input(current)
    if parsed.website_key_prefix and not website_key.startswith(parsed.website_key_prefix):
        return False
    if parsed.title_query and parsed.title_query.lower() not in title.lower():
        return False
    return True


def clear_track_new_autocomplete_cache() -> None:
    _track_new_autocomplete_cache.clear()
    _track_new_autocomplete_inflight.clear()


def _normalize_track_new_query(current: str) -> tuple[str, str]:
    query = str(current or "").strip()
    return query, query.casefold()


async def _fetch_track_new_choices(bot: Any, query: str) -> list[app_commands.Choice[str]]:
    data = await bot.crawler.request("autocomplete", query=query, limit=10)
    results: list[dict] = data.get("results") or []
    choices: list[app_commands.Choice[str]] = []
    for r in results:
        website_key = r.get("website_key") or ""
        series_url = r.get("series_url") or r.get("url") or ""
        title = r.get("title") or series_url
        if not website_key or not series_url:
            continue
        value = f"{website_key}|{series_url}"
        name = _manga_choice_name(website_key, title)
        choices.append(app_commands.Choice(name=name[:100], value=value[:100]))
        if len(choices) >= 10:
            break
    return choices


async def _track_new_choices_from_cache_or_crawler(
    bot: Any,
    *,
    query: str,
    cache_key: str,
) -> list[app_commands.Choice[str]]:
    now = time.monotonic()
    cached = _track_new_autocomplete_cache.get(cache_key)
    if cached is not None:
        expires_at, choices = cached
        if expires_at > now:
            return choices
        _track_new_autocomplete_cache.pop(cache_key, None)

    task = _track_new_autocomplete_inflight.get(cache_key)
    if task is None:
        task = asyncio.create_task(_fetch_track_new_choices(bot, query))
        _track_new_autocomplete_inflight[cache_key] = task
    try:
        choices = await task
    finally:
        if _track_new_autocomplete_inflight.get(cache_key) is task:
            _track_new_autocomplete_inflight.pop(cache_key, None)

    _track_new_autocomplete_cache[cache_key] = (
        time.monotonic() + TRACK_NEW_AUTOCOMPLETE_CACHE_TTL_SECONDS,
        choices,
    )
    return choices


async def tracked_manga_in_guild(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Manga tracked in the invoker's guild, filtered by *current* substring.

    Choice value: ``"{website_key}:{url_name}"``.
    Choice name:  ``"({website_key}) {title}"``.
    """
    if interaction.guild is None:
        return []
    try:
        bot: Any = interaction.client
        from .db.tracked import TrackedStore

        store = TrackedStore(bot.db)
        rows = await store.list_for_guild(interaction.guild.id, limit=100)
        choices: list[app_commands.Choice[str]] = []
        for row in rows:
            label = _manga_choice_name(row.website_key, row.title)
            value = f"{row.website_key}:{row.url_name}"
            if not _matches_manga_autocomplete(row.website_key, row.title, current):
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
        for row in rows:
            website_key = row["website_key"]
            url_name = row["url_name"]
            label = _manga_choice_name(website_key, url_name)
            value = f"{website_key}:{url_name}"
            if not _matches_manga_autocomplete(website_key, url_name, current):
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
        for bm in rows:
            label = _manga_choice_name(bm.website_key, bm.url_name)
            value = f"{bm.website_key}:{bm.url_name}"
            if not _matches_manga_autocomplete(bm.website_key, bm.url_name, current):
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
    """Autocomplete for /track new.

    Order of detection (no backend call when shape matches):
      1. Bare URL (``http(s)://...``) → return as-is.
      2. ``website_key|https://...`` shape → return as-is.
      3. Otherwise → query the crawler's local-DB ``autocomplete`` op immediately,
         with a short in-process cache and in-flight request coalescing.

    Choice value format for autocomplete suggestions: ``"{website_key}|{series_url}"``.
    """
    try:
        if current.startswith("http://") or current.startswith("https://"):
            return [app_commands.Choice(name=current[:100], value=current[:100])]

        if "|" in current:
            _, _, after_pipe = current.partition("|")
            after_pipe = after_pipe.strip()
            if after_pipe.startswith("http://") or after_pipe.startswith("https://"):
                return [app_commands.Choice(name=current[:100], value=current[:100])]

        bot: Any = interaction.client
        query, cache_key = _normalize_track_new_query(current)
        return await _track_new_choices_from_cache_or_crawler(
            bot,
            query=query,
            cache_key=cache_key,
        )
    except Exception:
        _log.exception("track_new_url_or_search autocomplete failed")
        return []
