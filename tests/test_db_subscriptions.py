"""Tests for SubscriptionStore."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.subscriptions import SubscriptionStore
from manhwa_bot.db.tracked import TrackedStore


async def _make_store(tmp: str) -> tuple[DbPool, SubscriptionStore]:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    return pool, SubscriptionStore(pool)


def test_list_for_user_includes_series_title_and_url() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                tracked = TrackedStore(pool)
                await tracked.upsert_series(
                    "asura",
                    "solo-leveling",
                    "https://example.test/solo-leveling",
                    "Solo Leveling",
                )
                await store.subscribe(42, 100, "asura", "solo-leveling")

                rows = await store.list_for_user(42, guild_id=100)

                assert rows == [
                    {
                        "user_id": 42,
                        "guild_id": 100,
                        "website_key": "asura",
                        "url_name": "solo-leveling",
                        "title": "Solo Leveling",
                        "series_url": "https://example.test/solo-leveling",
                        "subscribed_at": rows[0]["subscribed_at"],
                    }
                ]
            finally:
                await pool.close()

    asyncio.run(_run())


def test_unsubscribe_all_for_series_removes_only_target_series() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.subscribe(42, 100, "asura", "solo-leveling")
                await store.subscribe(43, 100, "asura", "solo-leveling")
                await store.subscribe(42, 100, "asura", "other-series")

                await store.unsubscribe_all_for_series("asura", "solo-leveling")

                assert await store.list_subscribers_for_series("asura", "solo-leveling") == []
                assert await store.list_subscribers_for_series("asura", "other-series") == [42]
            finally:
                await pool.close()

    asyncio.run(_run())
