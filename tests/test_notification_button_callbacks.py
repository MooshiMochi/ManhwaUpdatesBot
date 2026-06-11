"""DynamicItem callbacks for the chapter update view."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from manhwa_bot.db.bookmarks import BookmarkStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.subscriptions import SubscriptionStore
from manhwa_bot.db.tracked import TrackedStore
from manhwa_bot.ui.components.notification_buttons import (
    BookmarkButton,
    LastReadChapterButton,
    MarkReadButton,
    SubscribeToggleButton,
)


async def _open() -> tuple[DbPool, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
    await apply_pending(pool)
    return pool, tmp


class _Crawler:
    def __init__(self, chapters: list[dict]) -> None:
        self.chapters = chapters
        self.calls: list[tuple[str, dict]] = []

    async def request(self, op: str, **kwargs) -> dict:
        self.calls.append((op, kwargs))
        return {"chapters": self.chapters}


def _interaction(
    *,
    db: DbPool,
    user_id: int = 42,
    guild_id: int | None = 1,
    crawler: object | None = None,
):
    response = SimpleNamespace(
        defer=AsyncMock(),
        send_message=AsyncMock(),
        is_done=MagicMock(return_value=False),
    )
    followup = SimpleNamespace(send=AsyncMock())
    bot = SimpleNamespace(db=db, crawler=crawler)
    return SimpleNamespace(
        client=bot,
        user=SimpleNamespace(id=user_id),
        guild_id=guild_id,
        response=response,
        followup=followup,
    )


def _sent_component_v2_view(interaction) -> discord.ui.LayoutView:
    interaction.followup.send.assert_awaited()
    args, kwargs = interaction.followup.send.await_args
    assert args == ()
    assert kwargs["ephemeral"] is True
    view = kwargs["view"]
    assert isinstance(view, discord.ui.LayoutView)
    return view


def _view_text(view: discord.ui.LayoutView) -> str:
    return "\n".join(
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    )


def test_bookmark_button_creates_reading_bookmark() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            tracked = TrackedStore(pool)
            await tracked.upsert_series(
                "comick", "demo", "https://example.com/demo", "Demo", None, None
            )

            interaction = _interaction(db=pool)
            button = BookmarkButton("comick", "demo")
            await button.callback(interaction)
            store = BookmarkStore(pool)
            bm = await store.get_bookmark(42, "comick", "demo")
            assert bm is not None
            assert bm.folder == "Reading"
            text = _view_text(_sent_component_v2_view(interaction))
            assert "[Demo](https://example.com/demo)" in text
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
            text = _view_text(_sent_component_v2_view(interaction))
            assert "[Demo](https://example.com/demo)" in text

            # Second click unsubscribes.
            interaction2 = _interaction(db=pool, user_id=42, guild_id=1)
            await button.callback(interaction2)
            assert await subs.is_subscribed(42, 1, "comick", "demo") is False
            _sent_component_v2_view(interaction2)
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
            _sent_component_v2_view(interaction)
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_mark_read_button_toggles_back_to_previous_last_read() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            tracked = TrackedStore(pool)
            await tracked.upsert_series(
                "comick", "demo", "https://example.com/demo", "Demo", None, None
            )
            store = BookmarkStore(pool)
            await store.upsert_bookmark(
                42,
                "comick",
                "demo",
                folder="Reading",
                last_read_chapter="Chapter 15",
                last_read_index=15,
            )

            button = MarkReadButton("comick", "demo", 58)
            crawler = _Crawler(
                [
                    {"index": 15, "name": "Chapter 15", "url": "https://example.com/demo/15"},
                    {"index": 58, "name": "Chapter 58", "url": "https://example.com/demo/58"},
                ]
            )
            interaction = _interaction(db=pool, user_id=42, crawler=crawler)
            await button.callback(interaction)
            bm = await store.get_bookmark(42, "comick", "demo")
            assert bm is not None
            assert bm.last_read_chapter == "Chapter 58"
            assert bm.last_read_index == 58
            text = _view_text(_sent_component_v2_view(interaction))
            assert "[Demo](https://example.com/demo)" in text
            assert (
                "[Demo](https://example.com/demo) - [Chapter 58](https://example.com/demo/58)"
                in text
            )
            assert "[Chapter 58](https://example.com/demo/58)" in text
            assert "index" not in text.lower()

            interaction2 = _interaction(db=pool, user_id=42, crawler=crawler)
            await button.callback(interaction2)
            bm = await store.get_bookmark(42, "comick", "demo")
            assert bm is not None
            assert bm.last_read_chapter == "Chapter 15"
            assert bm.last_read_index == 15
            text = _view_text(_sent_component_v2_view(interaction2))
            assert "[Chapter 15](https://example.com/demo/15)" in text
            assert "index" not in text.lower()
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_last_read_chapter_button_reports_existing_chapter_name() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            tracked = TrackedStore(pool)
            await tracked.upsert_series(
                "comick", "demo", "https://example.com/demo", "Demo", None, None
            )
            await BookmarkStore(pool).upsert_bookmark(
                42,
                "comick",
                "demo",
                folder="Reading",
                last_read_chapter="Chapter 15",
                last_read_index=14,
            )

            interaction = _interaction(db=pool, user_id=42)
            await LastReadChapterButton("comick", "demo").callback(interaction)

            text = _view_text(_sent_component_v2_view(interaction))
            assert "[Demo](https://example.com/demo)" in text
            assert "Chapter 15" in text
            assert "14" not in text
            assert "index" not in text.lower()
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_last_read_chapter_button_does_not_show_index_when_name_is_missing() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            await BookmarkStore(pool).upsert_bookmark(
                42,
                "comick",
                "demo",
                folder="Reading",
                last_read_chapter=None,
                last_read_index=14,
            )

            interaction = _interaction(db=pool, user_id=42)
            await LastReadChapterButton("comick", "demo").callback(interaction)

            text = _view_text(_sent_component_v2_view(interaction))
            assert "No last read chapter name is available" in text
            assert "14" not in text
            assert "index" not in text.lower()
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
            _sent_component_v2_view(interaction)
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())
