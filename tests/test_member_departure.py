from __future__ import annotations

import asyncio
import gc
import weakref
from types import SimpleNamespace

import discord
import pytest

from manhwa_bot.cogs.subscriptions import SubscriptionsCog
from manhwa_bot.db.bookmarks import BookmarkStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.ui.components.bookmark import BookmarkBrowserView


def make_view(bot, user_id):
    return BookmarkBrowserView(
        [],
        store=None,
        tracked=None,
        subscriptions=None,
        guild_settings=None,
        crawler=None,
        invoker_id=user_id,
        bot=bot,
    )


def test_departure_deletes_only_member_server_subscriptions(tmp_path):
    async def run():
        pool = await DbPool.open(str(tmp_path / "departure.db"))
        await apply_pending(pool)
        try:
            bot = SimpleNamespace(db=pool)
            cog = SubscriptionsCog(bot)
            assert "on_raw_member_remove" in dict(cog.get_listeners())
            store = cog._subs
            for user, guild, series in [
                (20, 10, "a"),
                (20, 10, "b"),
                (20, 11, "a"),
                (20, 0, "a"),
                (21, 10, "a"),
            ]:
                await store.subscribe(user, guild, "asura", series)
            bookmarks = BookmarkStore(pool)
            await bookmarks.upsert_bookmark(20, "asura", "a", folder="Reading")
            # Deliberately no guild/member cache or role API on the bot/payload.
            payload = SimpleNamespace(user=SimpleNamespace(id=20), guild_id=10)
            for _ in range(2):
                await cog.on_raw_member_remove(payload)
            rows = await pool.fetchall(
                "SELECT user_id, guild_id, url_name FROM subscriptions ORDER BY user_id, guild_id"
            )
            assert [tuple(row) for row in rows] == [(20, 0, "a"), (20, 11, "a"), (21, 10, "a")]
            assert await bookmarks.get_bookmark(20, "asura", "a") is not None
            await cog.on_raw_member_remove(
                SimpleNamespace(user=SimpleNamespace(id=99), guild_id=10)
            )
        finally:
            await pool.close()

    asyncio.run(run())


def test_departure_invalidates_only_affected_views_even_on_database_failure(tmp_path):
    async def run():
        pool = await DbPool.open(str(tmp_path / "failure.db"))
        await apply_pending(pool)
        bot = SimpleNamespace(db=pool)
        cog = SubscriptionsCog(bot)
        affected = make_view(bot, 20)
        other_user = make_view(bot, 21)
        other_bot = make_view(SimpleNamespace(), 20)
        for view in (affected, other_user, other_bot):
            view._member_memo[10] = "old member"
            view._member_memo[11] = "other server"
            view._tracking_cache[("asura", "a")] = "old tracking"
            view._track_button_cache[("asura", "a")] = "old button"
        await pool.close()
        with pytest.raises(ValueError, match="no active connection"):
            await cog.on_raw_member_remove(
                SimpleNamespace(user=SimpleNamespace(id=20), guild_id=10)
            )
        assert 10 not in affected._member_memo
        assert affected._member_memo[11] == "other server"
        assert not affected._tracking_cache
        assert not affected._track_button_cache
        for view in (other_user, other_bot):
            assert view._member_memo[10] == "old member"
            assert view._tracking_cache
            assert view._track_button_cache

    asyncio.run(run())


def test_departure_during_member_fetch_cannot_restore_stale_membership():
    async def run():
        bot = SimpleNamespace()
        view = make_view(bot, 20)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def fetch_member(user_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()
                return SimpleNamespace(id=user_id)
            raise discord.NotFound(
                SimpleNamespace(status=404, reason="Not Found"), "Unknown Member"
            )

        guild = SimpleNamespace(id=10, get_member=lambda uid: None, fetch_member=fetch_member)
        lookup = asyncio.create_task(view._resolve_invoker_member(guild))
        await started.wait()
        BookmarkBrowserView.invalidate_membership(bot, 20, 10)
        release.set()
        assert await lookup is None
        assert await view._resolve_invoker_member(guild) is None

    asyncio.run(run())


def test_view_registry_does_not_keep_discarded_views_alive():
    async def run():
        view = make_view(SimpleNamespace(), 20)
        reference = weakref.ref(view)
        del view
        gc.collect()
        assert reference() is None

    asyncio.run(run())


def test_track_button_uses_refreshed_status_after_departure():
    async def run():
        view = make_view(SimpleNamespace(), 20)
        bookmark = SimpleNamespace(website_key="asura", url_name="a")
        stale = SimpleNamespace(mutual_guild=SimpleNamespace(id=10), channel_visible=True)
        view._tracking_cache[("asura", "a")] = SimpleNamespace(
            mutual_guild=None, channel_visible=False
        )
        state = await view._track_button_state(bookmark, stale)
        assert state.show is True
        assert state.enabled is False

    asyncio.run(run())
