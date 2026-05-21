"""SettingsLayoutView renders update_buttons as a multi-select."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from manhwa_bot.db.guild_settings import GuildSettingsStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.ui.components.settings import SettingsLayoutView


def _interaction():
    return SimpleNamespace(
        guild=None,
        guild_id=1,
        response=SimpleNamespace(
            defer=AsyncMock(),
            edit_message=AsyncMock(),
            is_done=MagicMock(return_value=False),
        ),
        edit_original_response=AsyncMock(),
    )


def test_build_update_buttons_select_reflects_current_set() -> None:
    async def _run() -> None:
        tmp = tempfile.TemporaryDirectory()
        pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
        try:
            await apply_pending(pool)
            store = GuildSettingsStore(pool)
            await store.set_notifications_channel(1, 100)
            await store.set_update_buttons(1, ["mark_read", "bookmark"])
            settings = await store.get(1)
            bot = SimpleNamespace(db=pool)
            view = SettingsLayoutView(bot, guild_id=1, settings=settings, scanlator_overrides=[])

            select = view._build_update_buttons_select(  # type: ignore[attr-defined]
                settings.update_buttons
            )
            assert isinstance(select, discord.ui.Select)
            assert select.min_values == 0
            assert select.max_values == 4
            default_values = {opt.value for opt in select.options if opt.default}
            assert default_values == {"mark_read", "bookmark"}
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_on_buttons_picked_persists_partial_selection() -> None:
    class _FakeSelect(discord.ui.Select):
        def __init__(self, values: list[str]) -> None:
            super().__init__(
                placeholder="x",
                options=[discord.SelectOption(label="x", value="x")],
            )
            self._patched_values = values

        @property  # type: ignore[override]
        def values(self) -> list[str]:
            return self._patched_values

    async def _run() -> None:
        tmp = tempfile.TemporaryDirectory()
        pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
        try:
            await apply_pending(pool)
            store = GuildSettingsStore(pool)
            await store.set_notifications_channel(1, 100)
            settings = await store.get(1)
            bot = SimpleNamespace(db=pool)
            view = SettingsLayoutView(bot, guild_id=1, settings=settings, scanlator_overrides=[])

            fake = _FakeSelect(["mark_read", "open_chapter", "junk"])
            view._current_dynamic_item = lambda: fake  # type: ignore[assignment]
            view._refresh = AsyncMock()  # type: ignore[assignment]

            await view._on_buttons_picked(_interaction())  # type: ignore[attr-defined]

            persisted = await store.get(1)
            assert persisted is not None
            assert persisted.update_buttons == frozenset({"mark_read", "open_chapter"})
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_on_buttons_picked_persists_empty_selection() -> None:
    class _FakeSelect(discord.ui.Select):
        def __init__(self) -> None:
            super().__init__(
                placeholder="x",
                options=[discord.SelectOption(label="x", value="x")],
            )

        @property  # type: ignore[override]
        def values(self) -> list[str]:
            return []

    async def _run() -> None:
        tmp = tempfile.TemporaryDirectory()
        pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
        try:
            await apply_pending(pool)
            store = GuildSettingsStore(pool)
            await store.set_notifications_channel(1, 100)
            settings = await store.get(1)
            bot = SimpleNamespace(db=pool)
            view = SettingsLayoutView(bot, guild_id=1, settings=settings, scanlator_overrides=[])

            fake = _FakeSelect()
            view._current_dynamic_item = lambda: fake  # type: ignore[assignment]
            view._refresh = AsyncMock()  # type: ignore[assignment]

            await view._on_buttons_picked(_interaction())  # type: ignore[attr-defined]

            persisted = await store.get(1)
            assert persisted is not None
            assert persisted.update_buttons == frozenset()
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_dm_settings_renders_update_buttons_multi_select() -> None:
    from manhwa_bot.db.dm_settings import DmSettingsStore
    from manhwa_bot.ui.components.settings import DmSettingsLayoutView

    async def _run() -> None:
        tmp = tempfile.TemporaryDirectory()
        pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
        try:
            await apply_pending(pool)
            await DmSettingsStore(pool).set_update_buttons(42, ["subscribe"])
            bot = SimpleNamespace(db=pool)
            view = DmSettingsLayoutView(bot, user_id=42)
            await view.initialize()

            selects = [c for c in view.walk_children() if isinstance(c, discord.ui.Select)]
            buttons_select = next(
                s for s in selects if s.placeholder and "buttons" in s.placeholder.lower()
            )
            default_values = {opt.value for opt in buttons_select.options if opt.default}
            assert default_values == {"subscribe"}
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())
