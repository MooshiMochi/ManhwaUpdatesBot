"""SettingsLayoutView._refresh must defer before doing DB work."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.ui.components.settings import SettingsLayoutView


def _interaction():
    response = SimpleNamespace(
        defer=AsyncMock(),
        edit_message=AsyncMock(),
        is_done=MagicMock(return_value=False),
    )
    interaction = SimpleNamespace(
        guild=None,
        response=response,
        edit_original_response=AsyncMock(),
    )
    return interaction


def test_refresh_defers_then_edits_original_response() -> None:
    async def _run() -> None:
        tmp = tempfile.TemporaryDirectory()
        pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
        try:
            await apply_pending(pool)
            bot = SimpleNamespace(db=pool)
            view = SettingsLayoutView(bot, guild_id=1, settings=None, scanlator_overrides=[])
            interaction = _interaction()
            await view._refresh(interaction)
            # Token-saving defer happens BEFORE any DB call.
            interaction.response.defer.assert_awaited_once()
            interaction.edit_original_response.assert_awaited_once()
            # The buggy code path called edit_message directly; we must not.
            interaction.response.edit_message.assert_not_called()
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())
