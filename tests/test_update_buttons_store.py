"""GuildSettingsStore and DmSettingsStore update_buttons round-trip."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from manhwa_bot.db.dm_settings import DmSettingsStore
from manhwa_bot.db.guild_settings import GuildSettingsStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool


async def _open() -> tuple[DbPool, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
    await apply_pending(pool)
    return pool, tmp


def test_guild_update_buttons_default_is_full_set() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = GuildSettingsStore(pool)
            await store.set_notifications_channel(1, 100)  # creates row
            settings = await store.get(1)
            assert settings is not None
            assert settings.update_buttons == frozenset(
                {"mark_read", "bookmark", "subscribe", "open_chapter"}
            )
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_guild_update_buttons_round_trip_empty() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = GuildSettingsStore(pool)
            await store.set_notifications_channel(1, 100)
            await store.set_update_buttons(1, [])
            settings = await store.get(1)
            assert settings is not None
            assert settings.update_buttons == frozenset()
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_guild_update_buttons_round_trip_subset() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = GuildSettingsStore(pool)
            await store.set_notifications_channel(1, 100)
            await store.set_update_buttons(1, ["mark_read", "subscribe"])
            settings = await store.get(1)
            assert settings is not None
            assert settings.update_buttons == frozenset({"mark_read", "subscribe"})
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_guild_update_buttons_filters_unknown_keys() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = GuildSettingsStore(pool)
            await store.set_notifications_channel(1, 100)
            await store.set_update_buttons(1, ["mark_read", "bogus", "subscribe"])
            settings = await store.get(1)
            assert settings is not None
            assert settings.update_buttons == frozenset({"mark_read", "subscribe"})
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_dm_update_buttons_default_when_no_row() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = DmSettingsStore(pool)
            settings = await store.get(42)
            assert settings is None  # default-when-missing handled by the caller
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_dm_update_buttons_round_trip_subset() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = DmSettingsStore(pool)
            await store.set_notifications_enabled(42, True)  # creates row
            await store.set_update_buttons(42, ["bookmark", "open_chapter"])
            settings = await store.get(42)
            assert settings is not None
            assert settings.update_buttons == frozenset({"bookmark", "open_chapter"})
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_dm_update_buttons_default_after_creation() -> None:
    async def _run() -> None:
        pool, tmp = await _open()
        try:
            store = DmSettingsStore(pool)
            await store.set_notifications_enabled(42, True)
            settings = await store.get(42)
            assert settings is not None
            assert settings.update_buttons == frozenset(
                {"mark_read", "bookmark", "subscribe", "open_chapter"}
            )
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())
