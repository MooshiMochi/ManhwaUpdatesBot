"""Tests for TrackedStore refcount semantics."""

import asyncio
import tempfile
from pathlib import Path

from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.tracked import TrackedStore


async def _make_store(tmp: str) -> tuple[DbPool, TrackedStore]:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    return pool, TrackedStore(pool)


def test_refcount_two_guilds() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.upsert_series(
                    "asura", "solo-leveling", "https://example.com/solo-leveling", "Solo Leveling"
                )
                await store.add_to_guild(111, "asura", "solo-leveling")
                await store.add_to_guild(222, "asura", "solo-leveling")

                was_last, remaining = await store.remove_from_guild(111, "asura", "solo-leveling")
                assert not was_last, "first removal should not be last"
                assert remaining == 1

                was_last, remaining = await store.remove_from_guild(222, "asura", "solo-leveling")
                assert was_last, "second removal should be last"
                assert remaining == 0
            finally:
                await pool.close()

    asyncio.run(_run())


def test_delete_series_cascades() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.upsert_series(
                    "asura", "tower-of-god", "https://example.com/tower-of-god", "Tower of God"
                )
                await store.add_to_guild(333, "asura", "tower-of-god")
                await store.delete_series("asura", "tower-of-god")

                # Cascade should have removed the guild row too.
                count = await store.count_for_guild(333)
                assert count == 0, "tracked_in_guild rows should cascade-delete"
            finally:
                await pool.close()

    asyncio.run(_run())


def test_list_for_guild_and_find() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.upsert_series(
                    "asura",
                    "nano-machine",
                    "https://example.com/nano-machine",
                    "Nano Machine",
                    cover_url="https://example.com/cover.jpg",
                )
                await store.add_to_guild(500, "asura", "nano-machine", ping_role_id=9999)

                rows = await store.list_for_guild(500)
                assert len(rows) == 1
                assert rows[0].title == "Nano Machine"
                assert rows[0].ping_role_id == 9999

                series = await store.find("asura", "nano-machine")
                assert series is not None
                assert series.cover_url == "https://example.com/cover.jpg"

                guilds = await store.list_guilds_tracking("asura", "nano-machine")
                assert len(guilds) == 1
                assert guilds[0].guild_id == 500
            finally:
                await pool.close()

    asyncio.run(_run())
