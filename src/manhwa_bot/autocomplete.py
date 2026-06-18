"""App-command autocomplete handlers.

All handlers return ``[]`` on errors — Discord shows "no choices" rather than
surfacing an exception to the user.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)
TRACK_NEW_AUTOCOMPLETE_CACHE_TTL_SECONDS = 20.0
CHAPTER_AUTOCOMPLETE_CACHE_TTL_SECONDS = 120.0
# Empty/failed fetches are cached only briefly so a transient miss (crawler busy
# during an update check, or a series whose chapters aren't stored yet) doesn't
# blackhole the field for the full TTL — it retries on the next keystroke.
CHAPTER_AUTOCOMPLETE_EMPTY_CACHE_TTL_SECONDS = 8.0
CHAPTER_AUTOCOMPLETE_WAIT_SECONDS = 1.5
_track_new_autocomplete_cache: dict[str, tuple[float, list[app_commands.Choice[str]]]] = {}
_track_new_autocomplete_inflight: dict[str, asyncio.Task[list[app_commands.Choice[str]]]] = {}
_ChapterAutocompleteKey = tuple[int, int, str, str]
_chapter_autocomplete_cache: dict[
    _ChapterAutocompleteKey, tuple[float, list[app_commands.Choice[str]]]
] = {}
_chapter_autocomplete_inflight: dict[
    _ChapterAutocompleteKey, asyncio.Task[list[app_commands.Choice[str]]]
] = {}

# The ``chapter`` option is a *string* option: Discord rejects integer choice
# values for it ("Could not interpret \"0\" as string"), so the chapter list
# index is carried as a string and parsed back in the command.
#
# Shown in the chapter field before a series has been chosen in the sibling
# ``manga`` option — the chapter list is derived entirely from that selection,
# so there is nothing to offer until it is set. ``"-1"`` can never collide with
# a real (0-based) chapter index, so a stray submission is rejected cleanly.
NO_SERIES_SELECTED_VALUE = "-1"
NO_SERIES_SELECTED_CHOICE = app_commands.Choice(
    name="You must select a series first", value=NO_SERIES_SELECTED_VALUE
)


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


def clear_chapter_autocomplete_cache() -> None:
    _chapter_autocomplete_cache.clear()
    for task in _chapter_autocomplete_inflight.values():
        task.cancel()
    _chapter_autocomplete_inflight.clear()


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
            value = series_choice_value(row.website_key, row.url_name)
            if not _matches_manga_autocomplete(row.website_key, row.title, current):
                continue
            choices.append(app_commands.Choice(name=label[:100], value=value[:100]))
            if len(choices) >= 25:
                break
        return choices
    except Exception:
        _log.exception("tracked_manga_in_guild autocomplete failed")
        return []


async def tracked_manga_in_guild_with_all(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Like :func:`tracked_manga_in_guild` but prepends an ``All`` option.

    The first choice carries value ``"*"`` and represents "get the default ping
    role" for the guild. Hidden when the input is non-empty and doesn't match.
    """
    if interaction.guild is None:
        return []
    base = await tracked_manga_in_guild(interaction, current)
    query = str(current or "").strip().lower()
    show_all = not query or query in "all" or query.startswith("*")
    if not show_all:
        return base
    all_choice = app_commands.Choice(
        name="All - Get the default ping role",
        value="*",
    )
    return [all_choice, *base[:24]]


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
            value = series_choice_value(website_key, url_name)
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
    """Bookmarks belonging to the invoker, labelled with the real series title."""
    try:
        bot: Any = interaction.client
        from .db.bookmarks import BookmarkStore

        store = BookmarkStore(bot.db)
        # Fetch the user's full bookmark list — a small page here silently hid
        # whole folders (the old folder-ordered query cut 'Subscribed' off).
        rows = await store.list_user_bookmarks_with_titles(interaction.user.id, limit=2000)
        choices: list[app_commands.Choice[str]] = []
        for bm, title in rows:
            if not _matches_manga_autocomplete(bm.website_key, title, current):
                continue
            label = _manga_choice_name(bm.website_key, title)
            value = series_choice_value(bm.website_key, bm.url_name)
            choices.append(app_commands.Choice(name=label[:100], value=value[:100]))
            if len(choices) >= 25:
                break
        return choices
    except Exception:
        _log.exception("user_bookmarks autocomplete failed")
        return []


def _split_series_id(series_id: str) -> tuple[str, str] | None:
    """Parse ``"website_key:url_name"`` autocomplete values."""
    if (
        not series_id
        or ":" not in series_id
        or series_id.startswith("http")
        or series_id.startswith(_SERIES_TOKEN_PREFIX)
    ):
        return None
    website_key, _, url_name = series_id.partition(":")
    website_key = website_key.strip()
    url_name = url_name.strip()
    if not website_key or not url_name:
        return None
    return (website_key, url_name)


# Discord caps app-command choice values at 100 characters. A handful of series
# have url_name slugs long enough that "{website_key}:{url_name}" overflows that
# cap; the old code truncated with ``value[:100]``, so the picked value no longer
# round-tripped and the command failed with "Invalid series id". For those we
# emit a compact, deterministic content token instead and resolve it back against
# the invoker's own rows (which always contain the series they just picked).
SERIES_VALUE_MAX_LEN = 100
_SERIES_TOKEN_PREFIX = "#"


def _series_token(website_key: str, url_name: str) -> str:
    digest = hashlib.sha1(f"{website_key}:{url_name}".encode()).hexdigest()[:24]
    return f"{_SERIES_TOKEN_PREFIX}{website_key}:{digest}"


def series_choice_value(website_key: str, url_name: str) -> str:
    """Build a round-trip-safe Discord choice value for a series.

    Short ids keep the historical ``"{website_key}:{url_name}"`` form (full
    backward compatibility); only over-long slugs fall back to a ``#``-token.
    """
    raw = f"{website_key}:{url_name}"
    if len(raw) <= SERIES_VALUE_MAX_LEN:
        return raw
    return _series_token(website_key, url_name)


def is_series_selection(value: str) -> bool:
    """True if *value* names a series (either short id or ``#``-token form)."""
    value = str(value or "")
    return value.startswith(_SERIES_TOKEN_PREFIX) or _split_series_id(value) is not None


def resolve_series_value(
    value: str, candidates: Iterable[tuple[str, str]]
) -> tuple[str, str] | None:
    """Resolve a choice *value* to ``(website_key, url_name)``.

    *candidates* (the invoker's accessible ``(website_key, url_name)`` pairs) is
    consulted only for the ``#``-token form; short values parse directly.
    """
    value = str(value or "")
    if value.startswith(_SERIES_TOKEN_PREFIX):
        for website_key, url_name in candidates:
            if value == _series_token(website_key, url_name):
                return (website_key, url_name)
        return None
    return _split_series_id(value)


async def resolve_series_value_async(
    value: str,
    candidates_provider: Callable[[], Awaitable[Iterable[tuple[str, str]]]],
) -> tuple[str, str] | None:
    """Like :func:`resolve_series_value` but fetches candidates lazily.

    *candidates_provider* is awaited only for the ``#``-token form, so short
    values never trigger a database read.
    """
    value = str(value or "")
    if not value.startswith(_SERIES_TOKEN_PREFIX):
        return _split_series_id(value)
    return resolve_series_value(value, await candidates_provider())


def _namespace_value(interaction: discord.Interaction, *names: str) -> str:
    namespace = getattr(interaction, "namespace", None)
    for name in names:
        value = getattr(namespace, name, None)
        if value is not None:
            return str(value)
    return ""


def _chapter_choice_matches(index: int, label: str, current: object) -> bool:
    query = str(current or "").strip().casefold()
    if not query:
        return True
    return str(index).startswith(query) or query in label.casefold()


def _filter_chapter_choices(
    choices: list[app_commands.Choice[str]], current: object
) -> list[app_commands.Choice[str]]:
    matched = [
        choice
        for choice in choices
        if _chapter_choice_matches(int(choice.value), str(choice.name), current)
    ]
    # Surface the newest chapters first: the cached list is ascending (index 0 =
    # oldest), so reverse before truncating so the latest matches sit at the top.
    matched.reverse()
    return matched[:25]


async def _fetch_chapter_choices(
    bot: Any,
    key: _ChapterAutocompleteKey,
    website_key: str,
    url_name: str,
) -> list[app_commands.Choice[str]]:
    from .crawler.chapter import Chapter

    try:
        # Read the crawler's stored (deduped, ascending) chapter list rather than
        # triggering a live scrape. ``chapters``/``info`` can take 30-60s, which
        # always blows past the autocomplete budget and leaves the field empty;
        # ``series_data`` with ``allow_live=False`` is a fast local-DB read keyed
        # by url_name, so it works for tracked and untracked bookmarks alike.
        data = await bot.crawler.request(
            "series_data",
            website_key=website_key,
            url_name=url_name,
            allow_live=False,
        )
        payload = data if isinstance(data, dict) else {}
        chapters = Chapter.list_from_payload(payload)
        # Value is the list index as a *string* — the ``chapter`` option is a
        # string option, so Discord rejects integer choice values.
        choices = [
            app_commands.Choice(name=f"{index} - {chapter.name}"[:100], value=str(index))
            for index, chapter in enumerate(chapters)
        ]
    except Exception:
        _log.debug("chapter autocomplete fetch failed", exc_info=True)
        choices = []

    ttl = (
        CHAPTER_AUTOCOMPLETE_CACHE_TTL_SECONDS
        if choices
        else CHAPTER_AUTOCOMPLETE_EMPTY_CACHE_TTL_SECONDS
    )
    _chapter_autocomplete_cache[key] = (time.monotonic() + ttl, choices)
    return choices


def _forget_chapter_inflight(
    key: _ChapterAutocompleteKey,
) -> Callable[[asyncio.Task[list[app_commands.Choice[str]]]], None]:
    def _done(task: asyncio.Task[list[app_commands.Choice[str]]]) -> None:
        if _chapter_autocomplete_inflight.get(key) is task:
            _chapter_autocomplete_inflight.pop(key, None)
        try:
            task.result()
        except asyncio.CancelledError:
            pass

    return _done


async def _user_bookmark_pairs(store: Any, user_id: int) -> list[tuple[str, str]]:
    """``(website_key, url_name)`` pairs for the invoker's bookmarks.

    Only fetched to resolve a ``#``-token chapter selection back to its series.
    """
    rows = await store.list_user_bookmarks(user_id, limit=2000)
    return [(row.website_key, row.url_name) for row in rows]


async def user_bookmark_chapters(
    interaction: discord.Interaction,
    current: int | str,
) -> list[app_commands.Choice[str]]:
    """Chapters for the bookmark selected in the sibling ``series``/``manga`` option.

    Choice value is the zero-based chapter list index consumed by
    ``/bookmark update``'s ``chapter`` option.
    """
    try:
        selected_series = _namespace_value(interaction, "manga", "series")
        if not is_series_selection(selected_series):
            # No series picked yet — prompt instantly without touching the DB or
            # crawler (the chapter list is keyed off the manga selection).
            return [NO_SERIES_SELECTED_CHOICE]

        bot: Any = interaction.client
        from .db.bookmarks import BookmarkStore

        bookmarks = BookmarkStore(bot.db)
        parsed = await resolve_series_value_async(
            selected_series,
            lambda: _user_bookmark_pairs(bookmarks, interaction.user.id),
        )
        if parsed is None:
            return []
        website_key, url_name = parsed
        bookmark = await bookmarks.get_bookmark(interaction.user.id, website_key, url_name)
        if bookmark is None:
            return []

        key = (id(bot), int(interaction.user.id), website_key, url_name)
        cached = _chapter_autocomplete_cache.get(key)
        now = time.monotonic()
        if cached is not None:
            expires_at, choices = cached
            if expires_at > now:
                return _filter_chapter_choices(choices, current)
            _chapter_autocomplete_cache.pop(key, None)

        task = _chapter_autocomplete_inflight.get(key)
        if task is None:
            task = asyncio.create_task(_fetch_chapter_choices(bot, key, website_key, url_name))
            task.add_done_callback(_forget_chapter_inflight(key))
            _chapter_autocomplete_inflight[key] = task

        try:
            choices = await asyncio.wait_for(
                asyncio.shield(task), timeout=CHAPTER_AUTOCOMPLETE_WAIT_SECONDS
            )
        except TimeoutError:
            return []
        return _filter_chapter_choices(choices, current)
    except Exception:
        _log.exception("user_bookmark_chapters autocomplete failed")
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


async def all_manga(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete across all series known to the crawler catalog."""
    try:
        if current.startswith("http://") or current.startswith("https://"):
            return [app_commands.Choice(name=current[:100], value=current[:100])]

        bot: Any = interaction.client
        query, cache_key = _normalize_track_new_query(current)
        return await _track_new_choices_from_cache_or_crawler(
            bot,
            query=query,
            cache_key=f"all:{cache_key}",
        )
    except Exception:
        _log.exception("all_manga autocomplete failed")
        return []
