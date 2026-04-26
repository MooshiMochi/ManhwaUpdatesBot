"""Tests for the lost-manga export logic in GeneralCog."""

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.manhwa_bot.cogs.general import _build_tsv, _get_lost_entries
from src.manhwa_bot.db.migrate import apply_pending
from src.manhwa_bot.db.pool import DbPool
from src.manhwa_bot.db.tracked import TrackedStore


async def _make_pool(tmp: str) -> DbPool:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    return pool


def _make_bot(pool: DbPool, supported_keys: list[str]) -> SimpleNamespace:
    """Minimal bot stand-in with the attributes _get_lost_entries touches."""
    websites = [{"key": k} for k in supported_keys]

    async def _get_or_set(key: str, loader: object, ttl: object) -> list:
        return websites

    cache = SimpleNamespace(get_or_set=AsyncMock(side_effect=_get_or_set))
    config = SimpleNamespace(
        supported_websites_cache=SimpleNamespace(ttl_seconds=3600),
        premium=SimpleNamespace(patreon=SimpleNamespace(pledge_url="")),
    )
    return SimpleNamespace(db=pool, websites_cache=cache, config=config)


def test_lost_entries_tracked() -> None:
    """Tracked series on an unsupported website appear in the export."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                store = TrackedStore(pool)
                await store.upsert_series("alive", "series-a", "http://alive/a", "Alive Series")
                await store.upsert_series("dead", "series-b", "http://dead/b", "Dead Series")
                await store.add_to_guild(1, "alive", "series-a")
                await store.add_to_guild(1, "dead", "series-b")

                bot = _make_bot(pool, supported_keys=["alive"])
                entries = await _get_lost_entries(bot)

                website_keys = {e["website_key"] for e in entries}
                assert "dead" in website_keys, "dead website must appear in export"
                assert "alive" not in website_keys, "alive website must NOT appear in export"

                kinds = {e["kind"] for e in entries}
                assert "tracked" in kinds
            finally:
                await pool.close()

    asyncio.run(_run())


def test_lost_entries_bookmark() -> None:
    """Bookmarks on an unsupported website appear in the export."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                # Insert bookmark directly (no tracked_series row — simulates orphaned bookmark)
                await pool.execute(
                    """
                    INSERT INTO bookmarks (user_id, website_key, url_name, folder)
                    VALUES (?, ?, ?, ?)
                    """,
                    (42, "dead", "orphan-series", "Reading"),
                )

                bot = _make_bot(pool, supported_keys=["alive"])
                entries = await _get_lost_entries(bot)

                assert any(
                    e["website_key"] == "dead" and e["kind"] == "bookmark" for e in entries
                )
            finally:
                await pool.close()

    asyncio.run(_run())


def test_lost_entries_both_kinds() -> None:
    """When the same website has both tracked and bookmarked series, both appear."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                store = TrackedStore(pool)
                await store.upsert_series("dead", "series-x", "http://dead/x", "Series X")
                await store.add_to_guild(1, "dead", "series-x")

                # Bookmark for a *different* series on the same dead website
                await pool.execute(
                    "INSERT INTO bookmarks (user_id, website_key, url_name, folder) VALUES (?,?,?,?)",
                    (99, "dead", "series-y", "Reading"),
                )

                bot = _make_bot(pool, supported_keys=[])
                entries = await _get_lost_entries(bot)

                tracked = [e for e in entries if e["kind"] == "tracked"]
                bookmarks = [e for e in entries if e["kind"] == "bookmark"]
                assert len(tracked) >= 1
                assert len(bookmarks) >= 1
            finally:
                await pool.close()

    asyncio.run(_run())


def test_no_lost_entries_when_all_supported() -> None:
    """Nothing is returned when every website key is still supported."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                store = TrackedStore(pool)
                await store.upsert_series("alive", "s1", "http://alive/s1", "S1")
                await store.add_to_guild(1, "alive", "s1")

                bot = _make_bot(pool, supported_keys=["alive"])
                entries = await _get_lost_entries(bot)
                assert entries == []
            finally:
                await pool.close()

    asyncio.run(_run())


def test_build_tsv_format() -> None:
    """TSV output has the correct header and columns."""
    entries = [
        {
            "kind": "tracked",
            "website_key": "dead",
            "url_name": "my-manga",
            "title": "My Manga",
            "series_url": "http://dead/my-manga",
            "last_read_chapter": "",
        }
    ]
    tsv = _build_tsv(entries).decode("utf-8")
    lines = tsv.strip().splitlines()
    assert lines[0] == "kind\twebsite_key\turl_name\ttitle\tseries_url\tlast_read_chapter"
    cols = lines[1].split("\t")
    assert cols[0] == "tracked"
    assert cols[1] == "dead"
    assert cols[2] == "my-manga"
