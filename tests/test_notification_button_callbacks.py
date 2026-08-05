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
        edit_message=AsyncMock(),
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


def _view_button(view: discord.ui.LayoutView, label: str) -> discord.ui.Button:
    return next(
        item
        for item in view.walk_children()
        if isinstance(item, discord.ui.Button) and item.label == label
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


def test_mark_read_creates_hidden_subscribed_bookmark_and_sets_last_read() -> None:
    # V1 parity: mark-read on an update notification was the main "subscribe"
    # flow — it created a hidden bookmark in the Subscribed folder, not a
    # visible Reading one.
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            interaction = _interaction(
                db=pool,
                user_id=42,
                crawler=_Crawler(
                    [{"index": 7, "name": "Chapter 7", "url": "https://example.com/7"}]
                ),
            )
            button = MarkReadButton("comick", "demo", 7)
            await button.callback(interaction)
            store = BookmarkStore(pool)
            bm = await store.get_bookmark(42, "comick", "demo")
            assert bm is not None
            assert bm.folder == "Subscribed"
            assert bm.last_read_index == 7
            _sent_component_v2_view(interaction)
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_mark_read_keeps_existing_folder() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = BookmarkStore(pool)
            await store.upsert_bookmark(
                user_id=42, website_key="comick", url_name="demo", folder="Planned"
            )
            interaction = _interaction(
                db=pool,
                user_id=42,
                crawler=_Crawler(
                    [{"index": 7, "name": "Chapter 7", "url": "https://example.com/7"}]
                ),
            )
            button = MarkReadButton("comick", "demo", 7)
            await button.callback(interaction)
            bm = await store.get_bookmark(42, "comick", "demo")
            assert bm is not None
            assert bm.folder == "Planned"
            assert bm.last_read_index == 7
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


def test_mark_read_expected_next_chapter_writes_without_confirmation() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = BookmarkStore(pool)
            await store.upsert_bookmark(
                42,
                "comick",
                "demo",
                folder="Reading",
                last_read_chapter="Chapter 22",
                last_read_index=22,
            )
            crawler = _Crawler(
                [
                    {
                        "index": index,
                        "name": f"Chapter {index}",
                        "url": f"https://example.com/demo/{index}",
                    }
                    for index in (22, 23, 24, 25)
                ]
            )
            interaction = _interaction(db=pool, user_id=42, crawler=crawler)

            await MarkReadButton("comick", "demo", 23).callback(interaction)

            bookmark = await store.get_bookmark(42, "comick", "demo")
            assert bookmark is not None
            assert bookmark.last_read_index == 23
            view = _sent_component_v2_view(interaction)
            assert "Marked read" in _view_text(view)
            assert not any(
                isinstance(item, discord.ui.Button) and item.label == "Proceed"
                for item in view.walk_children()
            )
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_mark_read_skipped_chapter_requires_hyperlinked_confirmation() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = BookmarkStore(pool)
            await store.upsert_bookmark(
                42,
                "comick",
                "demo",
                folder="Reading",
                last_read_chapter="Chapter 22",
                last_read_index=22,
            )
            crawler = _Crawler(
                [
                    {
                        "index": index,
                        "name": f"Chapter {index}",
                        "url": f"https://example.com/demo/{index}",
                    }
                    for index in (22, 23, 24, 25)
                ]
            )
            interaction = _interaction(db=pool, user_id=42, crawler=crawler)

            await MarkReadButton("comick", "demo", 25).callback(interaction)

            bookmark = await store.get_bookmark(42, "comick", "demo")
            assert bookmark is not None
            assert bookmark.last_read_index == 22
            view = _sent_component_v2_view(interaction)
            text = _view_text(view)
            assert "[Chapter 23](https://example.com/demo/23)" in text
            assert "[Chapter 25](https://example.com/demo/25)" in text
            assert _view_button(view, "Proceed")
            assert _view_button(view, "Discard")
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_mark_read_confirmation_proceed_advances_to_clicked_chapter() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = BookmarkStore(pool)
            await store.upsert_bookmark(
                42,
                "comick",
                "demo",
                folder="Reading",
                last_read_chapter="Chapter 22",
                last_read_index=22,
            )
            crawler = _Crawler(
                [
                    {
                        "index": index,
                        "name": f"Chapter {index}",
                        "url": f"https://example.com/demo/{index}",
                    }
                    for index in (22, 23, 24, 25)
                ]
            )
            first = _interaction(db=pool, user_id=42, crawler=crawler)
            await MarkReadButton("comick", "demo", 25).callback(first)
            view = _sent_component_v2_view(first)

            proceed_interaction = _interaction(db=pool, user_id=42, crawler=crawler)
            await _view_button(view, "Proceed").callback(proceed_interaction)

            bookmark = await store.get_bookmark(42, "comick", "demo")
            assert bookmark is not None
            assert bookmark.last_read_index == 25
            proceed_interaction.response.edit_message.assert_awaited_once()
            result_view = proceed_interaction.response.edit_message.await_args.kwargs["view"]
            assert "[Chapter 25](https://example.com/demo/25)" in _view_text(result_view)
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_mark_read_confirmation_discard_keeps_previous_chapter() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = BookmarkStore(pool)
            await store.upsert_bookmark(
                42,
                "comick",
                "demo",
                folder="Reading",
                last_read_chapter="Chapter 22",
                last_read_index=22,
            )
            crawler = _Crawler(
                [
                    {
                        "index": index,
                        "name": f"Chapter {index}",
                        "url": f"https://example.com/demo/{index}",
                    }
                    for index in (22, 23, 24, 25)
                ]
            )
            first = _interaction(db=pool, user_id=42, crawler=crawler)
            await MarkReadButton("comick", "demo", 25).callback(first)
            view = _sent_component_v2_view(first)

            discard_interaction = _interaction(db=pool, user_id=42, crawler=crawler)
            await _view_button(view, "Discard").callback(discard_interaction)

            bookmark = await store.get_bookmark(42, "comick", "demo")
            assert bookmark is not None
            assert bookmark.last_read_index == 22
            result_view = discard_interaction.response.edit_message.await_args.kwargs["view"]
            assert "No changes were made" in _view_text(result_view)
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_mark_read_confirmation_rejects_changed_bookmark_snapshot() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = BookmarkStore(pool)
            await store.upsert_bookmark(
                42,
                "comick",
                "demo",
                folder="Reading",
                last_read_chapter="Chapter 22",
                last_read_index=22,
            )
            crawler = _Crawler(
                [
                    {
                        "index": index,
                        "name": f"Chapter {index}",
                        "url": f"https://example.com/demo/{index}",
                    }
                    for index in (22, 23, 24, 25)
                ]
            )
            first = _interaction(db=pool, user_id=42, crawler=crawler)
            await MarkReadButton("comick", "demo", 25).callback(first)
            view = _sent_component_v2_view(first)
            await store.upsert_bookmark(
                42,
                "comick",
                "demo",
                folder="Reading",
                last_read_chapter="Chapter 23",
                last_read_index=23,
            )

            proceed_interaction = _interaction(db=pool, user_id=42, crawler=crawler)
            await _view_button(view, "Proceed").callback(proceed_interaction)

            bookmark = await store.get_bookmark(42, "comick", "demo")
            assert bookmark is not None
            assert bookmark.last_read_index == 23
            result_view = proceed_interaction.response.edit_message.await_args.kwargs["view"]
            assert "changed" in _view_text(result_view).lower()
            assert "try again" in _view_text(result_view).lower()
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_mark_read_unknown_sequence_warns_and_timeout_keeps_progress() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = BookmarkStore(pool)
            await store.upsert_bookmark(
                42,
                "comick",
                "demo",
                folder="Reading",
                last_read_chapter="Chapter 22",
                last_read_index=22,
            )
            interaction = _interaction(db=pool, user_id=42, crawler=_Crawler([]))

            await MarkReadButton("comick", "demo", 25).callback(interaction)

            view = _sent_component_v2_view(interaction)
            assert "couldn't reliably determine" in _view_text(view)
            await view.on_timeout()
            bookmark = await store.get_bookmark(42, "comick", "demo")
            assert bookmark is not None
            assert bookmark.last_read_index == 22
            assert all(
                item.disabled
                for item in view.walk_children()
                if isinstance(item, discord.ui.Button)
            )
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


def test_last_read_chapter_button_links_current_and_next_chapter() -> None:
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
                last_read_chapter="Chapter 2",
                last_read_index=1,
            )
            crawler = _Crawler(
                [
                    {"name": "Chapter 1", "url": "https://example.com/demo/1"},
                    {"name": "Chapter 2", "url": "https://example.com/demo/2"},
                    {"name": "Chapter 3", "url": "https://example.com/demo/3"},
                ]
            )
            interaction = _interaction(db=pool, user_id=42, crawler=crawler)
            await LastReadChapterButton("comick", "demo").callback(interaction)

            text = _view_text(_sent_component_v2_view(interaction))
            assert "[Demo](https://example.com/demo)" in text
            # Current last-read chapter rendered as a hyperlink.
            assert "[Chapter 2](https://example.com/demo/2)" in text
            # Next chapter to read rendered as a hyperlink.
            assert "[Chapter 3](https://example.com/demo/3)" in text
            assert "index" not in text.lower()
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_last_read_chapter_button_caught_up_has_no_next_link() -> None:
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
                last_read_chapter="Chapter 3",
                last_read_index=2,
            )
            crawler = _Crawler(
                [
                    {"name": "Chapter 1", "url": "https://example.com/demo/1"},
                    {"name": "Chapter 2", "url": "https://example.com/demo/2"},
                    {"name": "Chapter 3", "url": "https://example.com/demo/3"},
                ]
            )
            interaction = _interaction(db=pool, user_id=42, crawler=crawler)
            await LastReadChapterButton("comick", "demo").callback(interaction)

            text = _view_text(_sent_component_v2_view(interaction))
            assert "[Chapter 3](https://example.com/demo/3)" in text
            # On the latest chapter — no next link, just a caught-up note.
            assert "caught up" in text.lower()
            assert "https://example.com/demo/4" not in text
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())
