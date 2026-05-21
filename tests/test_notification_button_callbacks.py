"""DynamicItem callbacks for the chapter update view."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from manhwa_bot.db.bookmarks import BookmarkStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.subscriptions import SubscriptionStore
from manhwa_bot.db.tracked import TrackedStore
from manhwa_bot.ui.components.notification_buttons import (
    BookmarkButton,
    MarkReadButton,
    SubscribeToggleButton,
)


async def _open() -> tuple[DbPool, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
    await apply_pending(pool)
    return pool, tmp


def _interaction(*, db: DbPool, user_id: int = 42, guild_id: int | None = 1):
    response = SimpleNamespace(
        defer=AsyncMock(),
        send_message=AsyncMock(),
        is_done=MagicMock(return_value=False),
    )
    followup = SimpleNamespace(send=AsyncMock())
    bot = SimpleNamespace(db=db)
    return SimpleNamespace(
        client=bot,
        user=SimpleNamespace(id=user_id),
        guild_id=guild_id,
        response=response,
        followup=followup,
    )


def test_bookmark_button_creates_reading_bookmark() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            interaction = _interaction(db=pool)
            button = BookmarkButton("comick", "demo")
            await button.callback(interaction)
            store = BookmarkStore(pool)
            bm = await store.get_bookmark(42, "comick", "demo")
            assert bm is not None
            assert bm.folder == "Reading"
            interaction.followup.send.assert_awaited()
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_subscribe_button_toggles_subscription() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            # Seed a tracked-in-guild row so the user has a mutual guild.
            tracked = TrackedStore(pool)
            await tracked.upsert_series(
                "comick", "demo", "https://example.com/demo", "Demo", None, None
            )
            await tracked.add_to_guild(1, "comick", "demo")

            interaction = _interaction(db=pool, user_id=42, guild_id=1)
            button = SubscribeToggleButton("comick", "demo")
            await button.callback(interaction)

            subs = SubscriptionStore(pool)
            assert await subs.is_subscribed(42, 1, "comick", "demo") is True

            # Second click unsubscribes.
            interaction2 = _interaction(db=pool, user_id=42, guild_id=1)
            await button.callback(interaction2)
            assert await subs.is_subscribed(42, 1, "comick", "demo") is False
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_mark_read_creates_bookmark_and_sets_last_read() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            interaction = _interaction(db=pool, user_id=42)
            button = MarkReadButton("comick", "demo", 7)
            await button.callback(interaction)
            store = BookmarkStore(pool)
            bm = await store.get_bookmark(42, "comick", "demo")
            assert bm is not None
            assert bm.folder == "Reading"
            assert bm.last_read_index == 7
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_subscribe_without_mutual_guild_replies_only() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            # No tracked_in_guild rows — clicker has no mutual guild.
            interaction = _interaction(db=pool, user_id=42, guild_id=None)
            button = SubscribeToggleButton("comick", "demo")
            await button.callback(interaction)
            subs = SubscriptionStore(pool)
            assert await subs.list_for_user(42) == []
            interaction.followup.send.assert_awaited()
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())
