"""Tests for the auto-subscribe-on-final-chapter behavior in BookmarksCog."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

from manhwa_bot.cogs.bookmarks import BookmarksCog
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.subscriptions import SubscriptionStore
from manhwa_bot.db.tracked import TrackedStore


async def _make_cog(tmp: str) -> tuple[DbPool, BookmarksCog]:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    bot = SimpleNamespace(db=pool, crawler=SimpleNamespace())
    cog = BookmarksCog(bot)  # type: ignore[arg-type]
    return pool, cog


async def _seed_tracked(
    pool: DbPool,
    *,
    guild_id: int,
    website_key: str,
    url_name: str,
    status: str | None = None,
) -> None:
    tracked = TrackedStore(pool)
    await tracked.upsert_series(
        website_key,
        url_name,
        series_url=f"https://example.test/{url_name}",
        title=f"Title {url_name}",
        cover_url=None,
        status=status,
    )
    await tracked.add_to_guild(guild_id, website_key, url_name)


def test_auto_subscribe_fires_on_final_chapter() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, cog = await _make_cog(tmp)
            try:
                guild_id, user_id = 100, 200
                wk, un = "asura", "solo-leveling"
                await _seed_tracked(
                    pool, guild_id=guild_id, website_key=wk, url_name=un, status="ongoing"
                )

                suffix = await cog._maybe_auto_subscribe(
                    user_id=user_id,
                    guild_id=guild_id,
                    website_key=wk,
                    url_name=un,
                    chapter_index=9,
                    total_chapters=10,
                    status="ongoing",
                )

                assert suffix is not None
                assert "Auto-subscribed" in suffix

                subs = SubscriptionStore(pool)
                assert await subs.is_subscribed(user_id, guild_id, wk, un)
            finally:
                await pool.close()

    asyncio.run(_run())


def test_auto_subscribe_idempotent_on_repeat() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, cog = await _make_cog(tmp)
            try:
                guild_id, user_id = 101, 201
                wk, un = "asura", "tower-of-god"
                await _seed_tracked(
                    pool, guild_id=guild_id, website_key=wk, url_name=un, status=None
                )

                kwargs = dict(
                    user_id=user_id,
                    guild_id=guild_id,
                    website_key=wk,
                    url_name=un,
                    chapter_index=4,
                    total_chapters=5,
                    status=None,
                )
                first = await cog._maybe_auto_subscribe(**kwargs)
                second = await cog._maybe_auto_subscribe(**kwargs)

                assert first is not None and "Auto-subscribed" in first
                # Already subscribed → no suffix on second invocation.
                assert second is None
            finally:
                await pool.close()

    asyncio.run(_run())


def test_no_subscribe_for_non_final_chapter() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, cog = await _make_cog(tmp)
            try:
                guild_id, user_id = 102, 202
                wk, un = "asura", "omniscient-reader"
                await _seed_tracked(
                    pool, guild_id=guild_id, website_key=wk, url_name=un, status="ongoing"
                )

                suffix = await cog._maybe_auto_subscribe(
                    user_id=user_id,
                    guild_id=guild_id,
                    website_key=wk,
                    url_name=un,
                    chapter_index=3,
                    total_chapters=10,
                    status="ongoing",
                )
                assert suffix is None

                subs = SubscriptionStore(pool)
                assert not await subs.is_subscribed(user_id, guild_id, wk, un)
            finally:
                await pool.close()

    asyncio.run(_run())


def test_no_subscribe_when_status_completed() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, cog = await _make_cog(tmp)
            try:
                guild_id, user_id = 103, 203
                wk, un = "asura", "berserk"
                await _seed_tracked(
                    pool,
                    guild_id=guild_id,
                    website_key=wk,
                    url_name=un,
                    status="Completed",
                )

                suffix = await cog._maybe_auto_subscribe(
                    user_id=user_id,
                    guild_id=guild_id,
                    website_key=wk,
                    url_name=un,
                    chapter_index=49,
                    total_chapters=50,
                    status=None,  # falls back to tracked.status="Completed"
                )
                assert suffix is None

                subs = SubscriptionStore(pool)
                assert not await subs.is_subscribed(user_id, guild_id, wk, un)
            finally:
                await pool.close()

    asyncio.run(_run())


def test_hint_when_not_tracked_in_guild() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, cog = await _make_cog(tmp)
            try:
                guild_id, user_id = 104, 204
                # No tracking row inserted.
                suffix = await cog._maybe_auto_subscribe(
                    user_id=user_id,
                    guild_id=guild_id,
                    website_key="asura",
                    url_name="unknown-series",
                    chapter_index=9,
                    total_chapters=10,
                    status="ongoing",
                )
                assert suffix is not None
                assert "Ask a server admin" in suffix

                subs = SubscriptionStore(pool)
                assert not await subs.is_subscribed(user_id, guild_id, "asura", "unknown-series")
            finally:
                await pool.close()

    asyncio.run(_run())


def test_no_subscribe_in_dm() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, cog = await _make_cog(tmp)
            try:
                # No guild → DM context.
                suffix = await cog._maybe_auto_subscribe(
                    user_id=999,
                    guild_id=None,
                    website_key="asura",
                    url_name="anything",
                    chapter_index=9,
                    total_chapters=10,
                    status="ongoing",
                )
                assert suffix is None
            finally:
                await pool.close()

    asyncio.run(_run())
