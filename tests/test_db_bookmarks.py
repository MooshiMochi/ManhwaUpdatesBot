"""Tests for BookmarkStore."""

import asyncio
import tempfile
from pathlib import Path

from manhwa_bot.db.bookmarks import BookmarkStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool


async def _make_store(tmp: str) -> tuple[DbPool, BookmarkStore]:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    return pool, BookmarkStore(pool)


def test_upsert_and_get() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.upsert_bookmark(1, "asura", "solo-leveling", folder="Reading")
                bm = await store.get_bookmark(1, "asura", "solo-leveling")
                assert bm is not None
                assert bm.folder == "Reading"
                assert bm.last_read_chapter is None
            finally:
                await pool.close()

    asyncio.run(_run())


def test_update_last_read() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.upsert_bookmark(2, "asura", "tower-of-god")
                await store.update_last_read(
                    2, "asura", "tower-of-god", chapter_text="Chapter 100", chapter_index=100
                )
                bm = await store.get_bookmark(2, "asura", "tower-of-god")
                assert bm is not None
                assert bm.last_read_chapter == "Chapter 100"
                assert bm.last_read_index == 100
            finally:
                await pool.close()

    asyncio.run(_run())


def test_list_by_folder() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.upsert_bookmark(3, "asura", "series-a", folder="Reading")
                await store.upsert_bookmark(3, "asura", "series-b", folder="On Hold")
                await store.upsert_bookmark(3, "asura", "series-c", folder="Reading")

                reading = await store.list_user_bookmarks(3, folder="Reading")
                assert len(reading) == 2

                all_bm = await store.list_user_bookmarks(3)
                assert len(all_bm) == 3
            finally:
                await pool.close()

    asyncio.run(_run())


def test_delete_bookmark() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.upsert_bookmark(4, "asura", "solo-leveling")
                await store.delete_bookmark(4, "asura", "solo-leveling")
                bm = await store.get_bookmark(4, "asura", "solo-leveling")
                assert bm is None
                count = await store.count_for_user(4)
                assert count == 0
            finally:
                await pool.close()

    asyncio.run(_run())


def test_folder_index_used() -> None:
    """Verify the (user_id, folder) index exists and is used by the query planner."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.upsert_bookmark(5, "asura", "series-x", folder="Completed")
                rows = await pool.fetchall(
                    "EXPLAIN QUERY PLAN SELECT * FROM bookmarks WHERE user_id=5 AND folder='Completed'"
                )
                plan = " ".join(r["detail"] or "" for r in rows).lower()
                assert "idx_bookmarks_user_folder" in plan, f"index not used in plan: {plan}"
            finally:
                await pool.close()

    asyncio.run(_run())
