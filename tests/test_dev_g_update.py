"""Regression coverage for owner system-alert broadcasts."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from manhwa_bot.cogs import dev as dev_module
from manhwa_bot.cogs.dev import DevCog
from manhwa_bot.db.guild_settings import GuildSettingsStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool


async def _open() -> tuple[DbPool, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
    await apply_pending(pool)
    return pool, tmp


def test_g_update_fetches_uncached_configured_channel_before_broadcast(monkeypatch) -> None:
    """Removing a valid channel from cache must not silently drop its broadcast."""

    async def _run() -> None:
        pool, tmp = await _open()
        try:
            guild_id = 123
            channel_id = 456
            await GuildSettingsStore(pool).set_system_alerts_channel(guild_id, channel_id)

            guild = SimpleNamespace(id=guild_id, name="Test Guild", me=object())
            channel = MagicMock(spec=discord.TextChannel)
            channel.guild = guild
            channel.name = "system-alerts"
            channel.permissions_for.return_value = SimpleNamespace(send_messages=True)
            channel.send = AsyncMock()

            bot = SimpleNamespace(
                db=pool,
                get_channel=MagicMock(return_value=None),
                fetch_channel=AsyncMock(return_value=channel),
                get_guild=MagicMock(return_value=guild),
            )
            cog = object.__new__(DevCog)
            cog.bot = bot

            class _Confirm:
                def __init__(self, **_kwargs) -> None:
                    self.value = True

                def bind_message(self, _message) -> None:
                    return None

                async def wait(self) -> None:
                    return None

            monkeypatch.setattr(dev_module, "ConfirmLayoutView", _Confirm)

            preview = SimpleNamespace(delete=AsyncMock())
            confirmation = SimpleNamespace(edit=AsyncMock())
            ctx = SimpleNamespace(
                author=SimpleNamespace(id=99),
                send=AsyncMock(side_effect=[preview, confirmation]),
            )

            await DevCog.g_update.callback(cog, ctx, message="Maintenance complete")

            bot.fetch_channel.assert_awaited_once_with(channel_id)
            channel.send.assert_awaited_once()
            confirmation.edit.assert_any_await(content="Sent to 1/1.")
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())
