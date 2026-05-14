"""Integration tests for tracking cog refcount logic.

Verifies the invariant: the bot calls untrack_series on the crawler exactly
once — only when the last guild removes a series.  Uses a stub crawler and a
real aiosqlite in-memory DB with applied migrations.
"""

import asyncio
import tempfile
from pathlib import Path

from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.tracked import TrackedStore


class _StubCrawler:
    """Records crawler.request() calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def request(self, type_: str, **kwargs: object) -> dict:
        self.calls.append((type_, dict(kwargs)))
        return {}

    def untrack_calls(self) -> list[dict]:
        return [kw for t, kw in self.calls if t == "untrack_series"]


async def _make_store(tmp: str) -> tuple[DbPool, TrackedStore]:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    return pool, TrackedStore(pool)


async def _simulate_remove(
    store: TrackedStore,
    crawler: _StubCrawler,
    guild_id: int,
    website_key: str,
    url_name: str,
) -> tuple[bool, int]:
    """Mirrors the logic in TrackingCog.track_remove (without Discord interaction)."""
    was_last, remaining = await store.remove_from_guild(guild_id, website_key, url_name)
    if was_last:
        await crawler.request("untrack_series", website_key=website_key, url_name=url_name)
        await store.delete_series(website_key, url_name)
    return was_last, remaining


def test_untrack_series_called_only_on_last_guild() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            crawler = _StubCrawler()
            try:
                await store.upsert_series(
                    "asura", "solo-leveling", "https://example.com/solo-leveling", "Solo Leveling"
                )
                await store.add_to_guild(111, "asura", "solo-leveling")
                await store.add_to_guild(222, "asura", "solo-leveling")

                # First removal — not last guild.
                was_last, remaining = await _simulate_remove(
                    store, crawler, 111, "asura", "solo-leveling"
                )
                assert not was_last
                assert remaining == 1
                assert len(crawler.untrack_calls()) == 0, "untrack_series must not be called yet"

                # Second removal — last guild.
                was_last, remaining = await _simulate_remove(
                    store, crawler, 222, "asura", "solo-leveling"
                )
                assert was_last
                assert remaining == 0
                calls = crawler.untrack_calls()
                assert len(calls) == 1, "untrack_series must be called exactly once"
                assert calls[0]["website_key"] == "asura"
                assert calls[0]["url_name"] == "solo-leveling"
            finally:
                await pool.close()

    asyncio.run(_run())


def test_no_crawler_call_on_non_last_removal() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            crawler = _StubCrawler()
            try:
                await store.upsert_series(
                    "asura", "tower-of-god", "https://example.com/tower-of-god", "Tower of God"
                )
                await store.add_to_guild(333, "asura", "tower-of-god")
                await store.add_to_guild(444, "asura", "tower-of-god")

                # Only remove from one guild.
                was_last, remaining = await _simulate_remove(
                    store, crawler, 333, "asura", "tower-of-god"
                )
                assert not was_last
                assert remaining == 1
                assert len(crawler.untrack_calls()) == 0
            finally:
                await pool.close()

    asyncio.run(_run())


def test_series_deleted_when_last_guild_removes() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            crawler = _StubCrawler()
            try:
                await store.upsert_series(
                    "asura", "nano-machine", "https://example.com/nano-machine", "Nano Machine"
                )
                await store.add_to_guild(555, "asura", "nano-machine")

                was_last, remaining = await _simulate_remove(
                    store, crawler, 555, "asura", "nano-machine"
                )
                assert was_last
                assert remaining == 0

                # Master row should be gone.
                found = await store.find("asura", "nano-machine")
                assert found is None, "tracked_series row must be deleted after last guild removes"

                # Guild row should be gone (cascade).
                count = await store.count_for_guild(555)
                assert count == 0
            finally:
                await pool.close()

    asyncio.run(_run())
