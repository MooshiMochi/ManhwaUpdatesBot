# Chapter Update Persistent Buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `/settings` channel-picker 404, convert `show_update_buttons` into a four-key multi-select stored as a CSV column, and add four persistent buttons (Mark Read, Bookmark, Subscribe, Open Chapter) to the chapter update LayoutView using `discord.ui.DynamicItem`.

**Architecture:** A new SQLite migration swaps the `show_update_buttons` boolean for an `update_buttons TEXT` CSV on `guild_settings` and `dm_settings`. The chapter update view is rebuilt around an optional ActionRow whose contents come from the per-scope `update_buttons` set. The three writable buttons are `DynamicItem` subclasses registered once in `setup_hook`, so click callbacks survive bot restarts. The settings view gets a new multi-select branch for the buttons setting; `_refresh()` is updated to defer-then-edit so DB queries can't expire the interaction token.

**Tech Stack:** Python 3.14, discord.py 2.7.1 (Components V2 + `DynamicItem`), SQLite via the bot's `DbPool`, pytest with `asyncio.run` wrappers.

**Spec:** [`docs/superpowers/specs/2026-05-21-chapter-update-persistent-buttons-design.md`](../specs/2026-05-21-chapter-update-persistent-buttons-design.md)

---

## File Structure

**New files:**
- `src/manhwa_bot/db/migrations/012_update_buttons_multiselect.sql` — Column swap migration.
- `src/manhwa_bot/ui/components/notification_buttons.py` — Four `DynamicItem` button classes + `UPDATE_BUTTON_KEYS` / `UPDATE_BUTTON_LABELS` constants.
- `tests/test_settings_refresh_defer.py` — Regression test for the 404 fix.
- `tests/test_update_buttons_store.py` — `update_buttons` CSV round-trip on both stores.
- `tests/test_chapter_update_buttons.py` — View factory renders the right buttons for each `allowed_buttons` permutation.
- `tests/test_notification_buttons_dynamic.py` — `DynamicItem.template` regex round-trip + custom_id length ceiling.
- `tests/test_settings_update_buttons_multiselect.py` — Settings view multi-select rendering + save.

**Modified files:**
- `src/manhwa_bot/db/guild_settings.py` — Swap `show_update_buttons: bool` for `update_buttons: frozenset[str]`; new setter.
- `src/manhwa_bot/db/dm_settings.py` — Same swap on the DM dataclass + setter.
- `src/manhwa_bot/ui/components/notifications.py` — Drop accent_colour, accept `allowed_buttons`, append button row.
- `src/manhwa_bot/ui/components/settings.py` — Defer-then-edit in `_refresh`; multi-select branch; summary line formatting.
- `src/manhwa_bot/cogs/updates.py` — Pass `allowed_buttons` from the resolved settings into `build_chapter_update_view`.
- `src/manhwa_bot/bot.py` — Register the three dynamic item classes in `setup_hook`.
- `tests/test_notification_dispatch.py` — Adapt the existing `show_update_buttons` references.
- `tests/test_component_button_layout.py` — Adapt assertions about update-view buttons.

---

## Task 1: SQLite migration — `update_buttons` column

**Files:**
- Create: `src/manhwa_bot/db/migrations/012_update_buttons_multiselect.sql`

- [ ] **Step 1: Write the migration file**

```sql
ALTER TABLE guild_settings ADD COLUMN update_buttons TEXT NOT NULL DEFAULT 'mark_read,bookmark,subscribe,open_chapter';
UPDATE guild_settings SET update_buttons = '' WHERE show_update_buttons = 0;
ALTER TABLE guild_settings DROP COLUMN show_update_buttons;
ALTER TABLE dm_settings ADD COLUMN update_buttons TEXT NOT NULL DEFAULT 'mark_read,bookmark,subscribe,open_chapter';
UPDATE dm_settings SET update_buttons = '' WHERE show_update_buttons = 0;
ALTER TABLE dm_settings DROP COLUMN show_update_buttons;
```

- [ ] **Step 2: Confirm the runner accepts the new file**

The migrate runner (`src/manhwa_bot/db/migrate.py`) splits on `;` and runs each statement in one transaction. There are no embedded semicolons in strings, so the split is safe. No code change needed.

- [ ] **Step 3: Commit**

```bash
git add src/manhwa_bot/db/migrations/012_update_buttons_multiselect.sql
git commit -m "Add 012 migration: replace show_update_buttons with update_buttons CSV"
```

---

## Task 2: `GuildSettings` dataclass + store update

**Files:**
- Modify: `src/manhwa_bot/db/guild_settings.py`
- Create: `tests/test_update_buttons_store.py`

- [ ] **Step 1: Write the failing test (guild store CSV round-trip)**

Create `tests/test_update_buttons_store.py`:

```python
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
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `python -m pytest tests/test_update_buttons_store.py -v`
Expected: FAIL — `AttributeError: 'GuildSettings' object has no attribute 'update_buttons'` (or similar for the missing setter).

- [ ] **Step 3: Modify `GuildSettings` dataclass + parser**

In `src/manhwa_bot/db/guild_settings.py`:

```python
"""Store for guild_settings and guild_scanlator_channels tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .pool import DbPool

_VALID_UPDATE_BUTTONS: frozenset[str] = frozenset(
    {"mark_read", "bookmark", "subscribe", "open_chapter"}
)


def _parse_update_buttons(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    return frozenset(
        token.strip()
        for token in raw.split(",")
        if token.strip() in _VALID_UPDATE_BUTTONS
    )


def _serialize_update_buttons(keys: Iterable[str]) -> str:
    valid = [k for k in keys if k in _VALID_UPDATE_BUTTONS]
    # Keep canonical insertion order for stable storage.
    order = ("mark_read", "bookmark", "subscribe", "open_chapter")
    valid_sorted = [k for k in order if k in valid]
    return ",".join(valid_sorted)


@dataclass(frozen=True)
class GuildSettings:
    guild_id: int
    notifications_channel_id: int | None
    system_alerts_channel_id: int | None
    default_ping_role_id: int | None
    bot_manager_role_id: int | None
    paid_chapter_notifs: bool
    auto_create_role: bool
    update_buttons: frozenset[str]
    updated_at: str


def _row_to_settings(row: Any) -> GuildSettings:
    return GuildSettings(
        guild_id=row["guild_id"],
        notifications_channel_id=row["notifications_channel_id"],
        system_alerts_channel_id=row["system_alerts_channel_id"],
        default_ping_role_id=row["default_ping_role_id"],
        bot_manager_role_id=row["bot_manager_role_id"],
        paid_chapter_notifs=bool(row["paid_chapter_notifs"]),
        auto_create_role=bool(row["auto_create_role"]),
        update_buttons=_parse_update_buttons(row["update_buttons"]),
        updated_at=row["updated_at"],
    )
```

Replace the `set_show_update_buttons` method with:

```python
    async def set_update_buttons(self, guild_id: int, keys: Iterable[str]) -> None:
        encoded = _serialize_update_buttons(keys)
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, update_buttons)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              update_buttons = excluded.update_buttons,
              updated_at     = CURRENT_TIMESTAMP
            """,
            (guild_id, encoded),
        )
```

And update the `upsert` method's column list / VALUES / SET clauses: replace `show_update_buttons` with `update_buttons`, and replace the `int(settings.show_update_buttons)` parameter with `_serialize_update_buttons(settings.update_buttons)`.

- [ ] **Step 4: Run the guild tests to confirm they pass**

Run: `python -m pytest tests/test_update_buttons_store.py -v -k guild`
Expected: PASS on three guild tests.

- [ ] **Step 5: Commit**

```bash
git add src/manhwa_bot/db/guild_settings.py tests/test_update_buttons_store.py
git commit -m "Replace guild show_update_buttons bool with update_buttons set"
```

---

## Task 3: `DmSettings` dataclass + store update

**Files:**
- Modify: `src/manhwa_bot/db/dm_settings.py`
- Modify: `tests/test_update_buttons_store.py`

- [ ] **Step 1: Add the failing DM round-trip tests**

Append to `tests/test_update_buttons_store.py`:

```python
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
```

- [ ] **Step 2: Run the DM tests to confirm they fail**

Run: `python -m pytest tests/test_update_buttons_store.py -v -k dm`
Expected: FAIL — DmSettings has no `update_buttons`.

- [ ] **Step 3: Update `DmSettings` dataclass + setter**

Replace the contents of `src/manhwa_bot/db/dm_settings.py`:

```python
"""Store for the dm_settings table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .guild_settings import _parse_update_buttons, _serialize_update_buttons
from .pool import DbPool


@dataclass(frozen=True)
class DmSettings:
    user_id: int
    notifications_enabled: bool
    paid_chapter_notifs: bool
    update_buttons: frozenset[str]
    updated_at: str


def _row_to_dm_settings(row: Any) -> DmSettings:
    return DmSettings(
        user_id=row["user_id"],
        notifications_enabled=bool(row["notifications_enabled"]),
        paid_chapter_notifs=bool(row["paid_chapter_notifs"]),
        update_buttons=_parse_update_buttons(row["update_buttons"]),
        updated_at=row["updated_at"],
    )


class DmSettingsStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def get(self, user_id: int) -> DmSettings | None:
        row = await self._pool.fetchone(
            "SELECT * FROM dm_settings WHERE user_id = ?", (user_id,)
        )
        return _row_to_dm_settings(row) if row else None

    async def upsert(self, settings: DmSettings) -> None:
        await self._pool.execute(
            """
            INSERT INTO dm_settings
              (user_id, notifications_enabled, paid_chapter_notifs, update_buttons)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              notifications_enabled = excluded.notifications_enabled,
              paid_chapter_notifs   = excluded.paid_chapter_notifs,
              update_buttons        = excluded.update_buttons,
              updated_at            = CURRENT_TIMESTAMP
            """,
            (
                settings.user_id,
                int(settings.notifications_enabled),
                int(settings.paid_chapter_notifs),
                _serialize_update_buttons(settings.update_buttons),
            ),
        )

    async def set_notifications_enabled(self, user_id: int, enabled: bool) -> None:
        await self._pool.execute(
            """
            INSERT INTO dm_settings (user_id, notifications_enabled)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              notifications_enabled = excluded.notifications_enabled,
              updated_at            = CURRENT_TIMESTAMP
            """,
            (user_id, int(enabled)),
        )

    async def set_paid_chapter_notifs(self, user_id: int, enabled: bool) -> None:
        await self._pool.execute(
            """
            INSERT INTO dm_settings (user_id, paid_chapter_notifs)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              paid_chapter_notifs = excluded.paid_chapter_notifs,
              updated_at          = CURRENT_TIMESTAMP
            """,
            (user_id, int(enabled)),
        )

    async def set_update_buttons(self, user_id: int, keys: Iterable[str]) -> None:
        encoded = _serialize_update_buttons(keys)
        await self._pool.execute(
            """
            INSERT INTO dm_settings (user_id, update_buttons)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              update_buttons = excluded.update_buttons,
              updated_at     = CURRENT_TIMESTAMP
            """,
            (user_id, encoded),
        )
```

- [ ] **Step 4: Run all store tests**

Run: `python -m pytest tests/test_update_buttons_store.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwa_bot/db/dm_settings.py tests/test_update_buttons_store.py
git commit -m "Replace dm show_update_buttons bool with update_buttons set"
```

---

## Task 4: Update notification dispatch + existing tests

**Files:**
- Modify: `src/manhwa_bot/cogs/updates.py`
- Modify: `tests/test_notification_dispatch.py`
- Modify: `tests/test_component_button_layout.py`

- [ ] **Step 1: Run the existing dispatch tests to confirm they're now broken**

Run: `python -m pytest tests/test_notification_dispatch.py tests/test_component_button_layout.py -v`
Expected: FAIL with `TypeError: GuildSettings.__init__() got an unexpected keyword argument 'show_update_buttons'` (and the same for DmSettings).

- [ ] **Step 2: Update both test files**

In `tests/test_notification_dispatch.py` line ~308, replace:

```python
                DmSettings(
                    user_id=42,
                    notifications_enabled=False,
                    paid_chapter_notifs=True,
                    show_update_buttons=True,
                    updated_at="",
                )
```

with:

```python
                DmSettings(
                    user_id=42,
                    notifications_enabled=False,
                    paid_chapter_notifs=True,
                    update_buttons=frozenset(
                        {"mark_read", "bookmark", "subscribe", "open_chapter"}
                    ),
                    updated_at="",
                )
```

In `tests/test_component_button_layout.py`, find every `paid_chapter_notifs=True` GuildSettings literal and replace `show_update_buttons=...` with:

```python
update_buttons=frozenset(
    {"mark_read", "bookmark", "subscribe", "open_chapter"}
),
```

(The three call sites at the original lines 132, 193, 231 — adapt to wherever they land after Task 2's changes.)

- [ ] **Step 3: Run the existing test files**

Run: `python -m pytest tests/test_notification_dispatch.py tests/test_component_button_layout.py -v`
Expected: PASS (the dispatch still calls `build_chapter_update_view` with the old signature — we'll wire `allowed_buttons` in Task 8, but the existing tests don't inspect buttons so they pass).

- [ ] **Step 4: Commit**

```bash
git add tests/test_notification_dispatch.py tests/test_component_button_layout.py
git commit -m "Update existing tests for update_buttons rename"
```

---

## Task 5: `notification_buttons.py` — DynamicItem button classes

**Files:**
- Create: `src/manhwa_bot/ui/components/notification_buttons.py`
- Create: `tests/test_notification_buttons_dynamic.py`

- [ ] **Step 1: Write the failing template-regex round-trip test**

Create `tests/test_notification_buttons_dynamic.py`:

```python
"""DynamicItem custom_id templates parse the same data they encode."""

from __future__ import annotations

import re

from manhwa_bot.ui.components.notification_buttons import (
    BookmarkButton,
    MarkReadButton,
    SubscribeToggleButton,
)


def test_mark_read_template_round_trips() -> None:
    button = MarkReadButton("comick", "solo-leveling", 137)
    cid = button.item.custom_id
    assert cid == "mu:upd:mr:comick:solo-leveling:137"
    match = re.fullmatch(MarkReadButton.template, cid)
    assert match is not None
    assert match["wk"] == "comick"
    assert match["un"] == "solo-leveling"
    assert int(match["idx"]) == 137


def test_bookmark_template_round_trips() -> None:
    button = BookmarkButton("mangadex", "tower-of-god")
    cid = button.item.custom_id
    assert cid == "mu:upd:bm:mangadex:tower-of-god"
    match = re.fullmatch(BookmarkButton.template, cid)
    assert match is not None
    assert match["wk"] == "mangadex"
    assert match["un"] == "tower-of-god"


def test_subscribe_template_round_trips() -> None:
    button = SubscribeToggleButton("asurascans", "the-beginning-after-the-end")
    cid = button.item.custom_id
    assert cid == "mu:upd:sub:asurascans:the-beginning-after-the-end"
    match = re.fullmatch(SubscribeToggleButton.template, cid)
    assert match is not None
    assert match["wk"] == "asurascans"
    assert match["un"] == "the-beginning-after-the-end"


def test_mark_read_custom_id_under_100_chars_for_realistic_inputs() -> None:
    # Worst-case realistic slug lengths.
    button = MarkReadButton("a" * 24, "b" * 60, 9999)
    assert len(button.item.custom_id) <= 100
```

- [ ] **Step 2: Run to confirm import failure**

Run: `python -m pytest tests/test_notification_buttons_dynamic.py -v`
Expected: FAIL with `ImportError: cannot import name 'BookmarkButton' from 'manhwa_bot.ui.components.notification_buttons'`.

- [ ] **Step 3: Create the dynamic-item module (skeleton only — callbacks land in Task 6)**

Create `src/manhwa_bot/ui/components/notification_buttons.py`:

```python
"""Persistent DynamicItem buttons for the chapter update notification view."""

from __future__ import annotations

import logging
import re
from typing import Any

import discord

from ...db.bookmarks import BookmarkStore
from ...db.dm_settings import DmSettingsStore
from ...db.guild_settings import GuildSettingsStore
from ...db.subscriptions import SubscriptionStore
from ...db.tracked import TrackedStore

_log = logging.getLogger(__name__)

# Canonical key order for storage + UI rendering.
UPDATE_BUTTON_KEYS: tuple[str, ...] = (
    "mark_read",
    "bookmark",
    "subscribe",
    "open_chapter",
)
ALL_UPDATE_BUTTONS: frozenset[str] = frozenset(UPDATE_BUTTON_KEYS)

# (label, emoji, description) — used by settings select + buttons.
UPDATE_BUTTON_LABELS: dict[str, tuple[str, str, str]] = {
    "mark_read": (
        "Mark Read",
        "✅",
        "Marks the chapter as read in your bookmark.",
    ),
    "bookmark": (
        "Bookmark",
        "🔖",
        "Adds this series to your Reading bookmarks.",
    ),
    "subscribe": (
        "Subscribe",
        "🔔",
        "Toggles your subscription for this series.",
    ),
    "open_chapter": (
        "Open Chapter",
        "🔗",
        "Opens the chapter URL in your browser.",
    ),
}

# Slug guard — website_key and url_name come from the schema and must never
# contain a literal `:` (custom_id delimiter).
_SLUG_RE = re.compile(r"^[^:]+$")


def _assert_slug(value: str, *, field: str) -> str:
    if not _SLUG_RE.fullmatch(value):
        raise ValueError(f"{field}={value!r} contains a ':' which breaks custom_id parsing")
    return value


class MarkReadButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"mu:upd:mr:(?P<wk>[^:]+):(?P<un>[^:]+):(?P<idx>-?\d+)",
):
    def __init__(self, website_key: str, url_name: str, chapter_index: int) -> None:
        wk = _assert_slug(website_key, field="website_key")
        un = _assert_slug(url_name, field="url_name")
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["mark_read"][0],
                emoji=UPDATE_BUTTON_LABELS["mark_read"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:upd:mr:{wk}:{un}:{int(chapter_index)}",
            )
        )
        self.website_key = wk
        self.url_name = un
        self.chapter_index = int(chapter_index)

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "MarkReadButton":
        return cls(match["wk"], match["un"], int(match["idx"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        # Wired in Task 6.
        await interaction.response.send_message("Not yet implemented.", ephemeral=True)


class BookmarkButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"mu:upd:bm:(?P<wk>[^:]+):(?P<un>[^:]+)",
):
    def __init__(self, website_key: str, url_name: str) -> None:
        wk = _assert_slug(website_key, field="website_key")
        un = _assert_slug(url_name, field="url_name")
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["bookmark"][0],
                emoji=UPDATE_BUTTON_LABELS["bookmark"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:upd:bm:{wk}:{un}",
            )
        )
        self.website_key = wk
        self.url_name = un

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "BookmarkButton":
        return cls(match["wk"], match["un"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Not yet implemented.", ephemeral=True)


class SubscribeToggleButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"mu:upd:sub:(?P<wk>[^:]+):(?P<un>[^:]+)",
):
    def __init__(self, website_key: str, url_name: str) -> None:
        wk = _assert_slug(website_key, field="website_key")
        un = _assert_slug(url_name, field="url_name")
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["subscribe"][0],
                emoji=UPDATE_BUTTON_LABELS["subscribe"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:upd:sub:{wk}:{un}",
            )
        )
        self.website_key = wk
        self.url_name = un

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "SubscribeToggleButton":
        return cls(match["wk"], match["un"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Not yet implemented.", ephemeral=True)


# Re-exports referenced by stores when Task 6 wires the callbacks.
__all__ = [
    "ALL_UPDATE_BUTTONS",
    "BookmarkButton",
    "BookmarkStore",
    "DmSettingsStore",
    "GuildSettingsStore",
    "MarkReadButton",
    "SubscribeToggleButton",
    "SubscriptionStore",
    "TrackedStore",
    "UPDATE_BUTTON_KEYS",
    "UPDATE_BUTTON_LABELS",
]
```

- [ ] **Step 4: Run the dynamic-item tests**

Run: `python -m pytest tests/test_notification_buttons_dynamic.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwa_bot/ui/components/notification_buttons.py tests/test_notification_buttons_dynamic.py
git commit -m "Add DynamicItem button skeletons for chapter update view"
```

---

## Task 6: Wire DynamicItem button callbacks

**Files:**
- Modify: `src/manhwa_bot/ui/components/notification_buttons.py`
- Create: `tests/test_notification_button_callbacks.py`

- [ ] **Step 1: Write the failing callback tests**

Create `tests/test_notification_button_callbacks.py`:

```python
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
            interaction.response.send_message.assert_awaited()
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
            interaction.response.send_message.assert_awaited()
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())
```

- [ ] **Step 2: Run the callback tests to confirm they fail**

Run: `python -m pytest tests/test_notification_button_callbacks.py -v`
Expected: FAIL — placeholder callbacks reply "Not yet implemented." and don't touch the DB.

- [ ] **Step 3: Implement the callbacks**

Replace the three callback bodies in `src/manhwa_bot/ui/components/notification_buttons.py`:

```python
    # --- MarkReadButton.callback ----------------------------------------
    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        pool = interaction.client.db  # type: ignore[attr-defined]
        store = BookmarkStore(pool)
        existing = await store.get_bookmark(
            interaction.user.id, self.website_key, self.url_name
        )
        chapter_index = self.chapter_index
        # The encoded index is a hint; we don't have a live chapters lookup
        # here, so trust it for the write. The bookmark browser re-resolves
        # against current series_data when the user opens it.
        chapter_text = f"Chapter index {chapter_index}"
        await store.upsert_bookmark(
            user_id=interaction.user.id,
            website_key=self.website_key,
            url_name=self.url_name,
            folder=existing.folder if existing else "Reading",
            last_read_chapter=chapter_text,
            last_read_index=chapter_index,
        )
        msg = (
            f"✅ Marked **{self.url_name}** chapter index `{chapter_index}` as read."
            if existing
            else f"✅ Bookmarked **{self.url_name}** in *Reading* and marked chapter "
            f"index `{chapter_index}` as read."
        )
        await interaction.followup.send(msg, ephemeral=True)

    # --- BookmarkButton.callback ----------------------------------------
    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        pool = interaction.client.db  # type: ignore[attr-defined]
        store = BookmarkStore(pool)
        existing = await store.get_bookmark(
            interaction.user.id, self.website_key, self.url_name
        )
        if existing is None:
            await store.upsert_bookmark(
                user_id=interaction.user.id,
                website_key=self.website_key,
                url_name=self.url_name,
                folder="Reading",
            )
            msg = f"🔖 Bookmarked **{self.url_name}** in *Reading*."
        else:
            msg = (
                f"🔖 You already have **{self.url_name}** bookmarked in "
                f"*{existing.folder}*."
            )
        await interaction.followup.send(msg, ephemeral=True)

    # --- SubscribeToggleButton.callback ---------------------------------
    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        pool = interaction.client.db  # type: ignore[attr-defined]
        tracked_store = TrackedStore(pool)
        guild_rows = await tracked_store.list_guilds_tracking(
            self.website_key, self.url_name
        )
        if not guild_rows:
            await interaction.followup.send(
                "This series isn't tracked in any server yet — ask a server admin "
                "to `/track new` it before subscribing.",
                ephemeral=True,
            )
            return
        # Prefer the guild the click came from, otherwise the first tracking row.
        chosen_guild_id: int | None = None
        for row in guild_rows:
            if interaction.guild_id is not None and int(row.guild_id) == int(
                interaction.guild_id
            ):
                chosen_guild_id = int(row.guild_id)
                break
        if chosen_guild_id is None:
            chosen_guild_id = int(guild_rows[0].guild_id)

        subs = SubscriptionStore(pool)
        already = await subs.is_subscribed(
            interaction.user.id,
            chosen_guild_id,
            self.website_key,
            self.url_name,
        )
        if already:
            await subs.unsubscribe(
                interaction.user.id,
                chosen_guild_id,
                self.website_key,
                self.url_name,
            )
            msg = f"🔔 Unsubscribed from **{self.url_name}**."
        else:
            await subs.subscribe(
                interaction.user.id,
                chosen_guild_id,
                self.website_key,
                self.url_name,
            )
            msg = f"🔔 Subscribed to **{self.url_name}**."
        await interaction.followup.send(msg, ephemeral=True)
```

- [ ] **Step 4: Run the callback tests**

Run: `python -m pytest tests/test_notification_button_callbacks.py tests/test_notification_buttons_dynamic.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwa_bot/ui/components/notification_buttons.py tests/test_notification_button_callbacks.py
git commit -m "Wire MarkRead, Bookmark, Subscribe DynamicItem callbacks"
```

---

## Task 7: Update notification view factory (`notifications.py`)

**Files:**
- Modify: `src/manhwa_bot/ui/components/notifications.py`
- Create: `tests/test_chapter_update_buttons.py`

- [ ] **Step 1: Write the failing view-shape tests**

Create `tests/test_chapter_update_buttons.py`:

```python
"""build_chapter_update_view honours `allowed_buttons`."""

from __future__ import annotations

import discord

from manhwa_bot.ui.components.notifications import (
    ALL_UPDATE_BUTTONS,
    build_chapter_update_view,
)
from manhwa_bot.ui.components.notification_buttons import (
    BookmarkButton,
    MarkReadButton,
    SubscribeToggleButton,
)


def _payload() -> dict:
    return {
        "website_key": "comick",
        "url_name": "demo",
        "series_title": "Demo Series",
        "series_url": "https://example.com/demo",
        "chapter": {
            "index": 7,
            "name": "Chapter 7",
            "url": "https://example.com/demo/7",
            "is_premium": False,
        },
        "cover_url": "https://example.com/cover.png",
    }


def _action_rows(view: discord.ui.LayoutView) -> list[discord.ui.ActionRow]:
    return [
        item
        for item in view.walk_children()
        if isinstance(item, discord.ui.ActionRow)
        and any(isinstance(c, discord.ui.Button) for c in item.children)
    ]


def _buttons(view: discord.ui.LayoutView) -> list[discord.ui.Button]:
    return [c for c in view.walk_children() if isinstance(c, discord.ui.Button)]


def test_no_buttons_when_allowed_empty() -> None:
    view = build_chapter_update_view(_payload(), bot=None, allowed_buttons=frozenset())
    assert _action_rows(view) == []
    assert _buttons(view) == []


def test_only_open_chapter_renders_link_button() -> None:
    view = build_chapter_update_view(
        _payload(), bot=None, allowed_buttons=frozenset({"open_chapter"})
    )
    buttons = _buttons(view)
    assert len(buttons) == 1
    assert buttons[0].style is discord.ButtonStyle.link
    assert buttons[0].url == "https://example.com/demo/7"


def test_all_buttons_appear_in_canonical_order() -> None:
    view = build_chapter_update_view(_payload(), bot=None, allowed_buttons=ALL_UPDATE_BUTTONS)
    buttons = _buttons(view)
    assert len(buttons) == 4
    # mark_read, bookmark, subscribe come from DynamicItem.item; open_chapter is a link button.
    assert buttons[0].custom_id == "mu:upd:mr:comick:demo:7"
    assert buttons[1].custom_id == "mu:upd:bm:comick:demo"
    assert buttons[2].custom_id == "mu:upd:sub:comick:demo"
    assert buttons[3].style is discord.ButtonStyle.link
    assert buttons[3].url == "https://example.com/demo/7"


def test_container_has_no_accent_colour() -> None:
    view = build_chapter_update_view(_payload(), bot=None, allowed_buttons=ALL_UPDATE_BUTTONS)
    containers = [c for c in view.children if isinstance(c, discord.ui.Container)]
    assert containers
    for c in containers:
        assert c.accent_colour is None


def test_mark_read_falls_back_to_index_when_missing() -> None:
    payload = _payload()
    payload["chapter"].pop("index")
    view = build_chapter_update_view(
        payload, bot=None, allowed_buttons=frozenset({"mark_read"})
    )
    buttons = _buttons(view)
    assert len(buttons) == 1
    # -1 sentinel encodes "unknown index" — handler upserts as last_read_index=-1.
    assert buttons[0].custom_id == "mu:upd:mr:comick:demo:-1"


def test_view_has_no_timeout() -> None:
    view = build_chapter_update_view(_payload(), bot=None, allowed_buttons=ALL_UPDATE_BUTTONS)
    assert view.timeout is None
```

- [ ] **Step 2: Run to confirm failures**

Run: `python -m pytest tests/test_chapter_update_buttons.py -v`
Expected: FAIL — `build_chapter_update_view` doesn't accept `allowed_buttons`.

- [ ] **Step 3: Rewrite `notifications.py`**

Replace contents of `src/manhwa_bot/ui/components/notifications.py`:

```python
"""Chapter update push-notification LayoutView factory."""

from __future__ import annotations

import discord

from ...crawler.chapter import Chapter
from .base import (
    BaseLayoutView,
    chapter_markdown,
    footer_section,
    hero_cover_gallery,
    small_separator,
)
from .notification_buttons import (
    ALL_UPDATE_BUTTONS,
    UPDATE_BUTTON_KEYS,
    UPDATE_BUTTON_LABELS,
    BookmarkButton,
    MarkReadButton,
    SubscribeToggleButton,
)


def build_chapter_update_view(
    payload: dict,
    *,
    bot: discord.Client | None = None,
    allowed_buttons: frozenset[str] = ALL_UPDATE_BUTTONS,
) -> discord.ui.LayoutView:
    """Build a fresh push-notification LayoutView for a new chapter.

    Must be called per delivery — views can't be shared across messages. The
    view has `timeout=None` so interactive buttons survive bot restarts
    (callbacks are routed through `DynamicItem` classes registered in
    `ManhwaBot.setup_hook`).
    """
    series_title = payload.get("series_title") or payload.get("url_name") or "New chapter"
    series_url = payload.get("series_url") or None
    raw_chapter = payload.get("chapter") or {}
    chapter = raw_chapter if isinstance(raw_chapter, Chapter) else Chapter.from_dict(raw_chapter)
    is_premium = chapter.is_premium
    cover_url = payload.get("cover_url")
    website_key = str(payload.get("website_key") or "")
    url_name = str(payload.get("url_name") or "")

    glyph = "🥇" if is_premium else "📖"
    header = (
        f"## {glyph}  [{series_title}]({series_url})"
        if series_url
        else f"## {glyph}  {series_title}"
    )
    chapter_display = chapter_markdown(chapter)
    body = f"**New chapter:** {chapter_display}"

    container = discord.ui.Container()  # no accent_colour
    gallery = hero_cover_gallery(cover_url)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(header))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(body))

    button_row = _build_button_row(
        allowed_buttons=allowed_buttons,
        website_key=website_key,
        url_name=url_name,
        chapter=chapter,
    )
    if button_row is not None:
        container.add_item(small_separator())
        container.add_item(button_row)

    container.add_item(small_separator())
    container.add_item(footer_section(bot, extra=website_key or None))

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


def _build_button_row(
    *,
    allowed_buttons: frozenset[str],
    website_key: str,
    url_name: str,
    chapter: Chapter,
) -> discord.ui.ActionRow | None:
    if not allowed_buttons or not website_key or not url_name:
        return None

    row = discord.ui.ActionRow()

    # Iterate in canonical order so the visual layout is stable.
    chapter_index = chapter.index if chapter.index is not None else -1
    for key in UPDATE_BUTTON_KEYS:
        if key not in allowed_buttons:
            continue
        if key == "mark_read":
            row.add_item(
                MarkReadButton(website_key, url_name, chapter_index)
            )
        elif key == "bookmark":
            row.add_item(BookmarkButton(website_key, url_name))
        elif key == "subscribe":
            row.add_item(SubscribeToggleButton(website_key, url_name))
        elif key == "open_chapter":
            chapter_url = (chapter.url or "").strip()
            if not chapter_url:
                continue
            label, emoji, _ = UPDATE_BUTTON_LABELS["open_chapter"]
            row.add_item(
                discord.ui.Button(
                    label=label,
                    emoji=emoji,
                    style=discord.ButtonStyle.link,
                    url=chapter_url,
                )
            )

    if len(list(row.children)) == 0:
        return None
    return row


__all__ = [
    "ALL_UPDATE_BUTTONS",
    "UPDATE_BUTTON_KEYS",
    "UPDATE_BUTTON_LABELS",
    "build_chapter_update_view",
]
```

- [ ] **Step 4: Verify `Chapter` has an `index` attribute, or add an inline fallback**

Run: `python -c "from manhwa_bot.crawler.chapter import Chapter; print(hasattr(Chapter, 'index') or 'index' in Chapter.__dataclass_fields__)"`

If `Chapter` does not expose `index`, replace the `chapter_index = chapter.index if chapter.index is not None else -1` line with:

```python
    chapter_index_raw = raw_chapter.get("index") if isinstance(raw_chapter, dict) else None
    chapter_index = int(chapter_index_raw) if chapter_index_raw is not None else -1
```

- [ ] **Step 5: Run all view tests**

Run: `python -m pytest tests/test_chapter_update_buttons.py tests/test_component_button_layout.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add src/manhwa_bot/ui/components/notifications.py tests/test_chapter_update_buttons.py
git commit -m "Render chapter update view with optional button row"
```

---

## Task 8: Dispatch passes `allowed_buttons` from settings

**Files:**
- Modify: `src/manhwa_bot/cogs/updates.py`
- Modify: `tests/test_notification_dispatch.py`

- [ ] **Step 1: Add the failing dispatch test**

Append to `tests/test_notification_dispatch.py`:

```python
def test_guild_with_no_buttons_setting_sends_view_without_buttons() -> None:
    from manhwa_bot.cogs.updates import build_chapter_update_view
    import discord

    async def _run() -> None:
        bot, cog, tmp = await _setup()
        try:
            await _seed_tracked(bot.db, guild_ids=[1])
            settings_store = GuildSettingsStore(bot.db)
            await settings_store.set_notifications_channel(1, 100)
            await settings_store.set_update_buttons(1, [])

            channel = _make_channel()
            bot.get_channel.side_effect = lambda cid: channel if cid == 100 else None

            await cog.dispatch(_payload())
            assert channel.send.await_count == 1
            view = channel.send.await_args.kwargs["view"]
            buttons = [
                c for c in view.walk_children() if isinstance(c, discord.ui.Button)
            ]
            assert buttons == []
        finally:
            await bot.db.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_guild_default_settings_sends_view_with_all_buttons() -> None:
    import discord

    async def _run() -> None:
        bot, cog, tmp = await _setup()
        try:
            await _seed_tracked(bot.db, guild_ids=[1])
            settings_store = GuildSettingsStore(bot.db)
            await settings_store.set_notifications_channel(1, 100)
            # Don't touch update_buttons — default = all four.

            channel = _make_channel()
            bot.get_channel.side_effect = lambda cid: channel if cid == 100 else None

            await cog.dispatch(_payload())
            view = channel.send.await_args.kwargs["view"]
            buttons = [
                c for c in view.walk_children() if isinstance(c, discord.ui.Button)
            ]
            assert len(buttons) == 4
        finally:
            await bot.db.close()
            tmp.cleanup()

    asyncio.run(_run())
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_notification_dispatch.py -v -k "buttons"`
Expected: FAIL — dispatch currently ignores `update_buttons`.

- [ ] **Step 3: Update dispatch to pass `allowed_buttons`**

In `src/manhwa_bot/cogs/updates.py`, locate the two `build_chapter_update_view(payload, bot=self.bot)` calls and change them.

In `_dispatch_to_guild` (around line 137):

```python
                allowed = settings.update_buttons if settings is not None else ALL_UPDATE_BUTTONS
                view = build_chapter_update_view(payload, bot=self.bot, allowed_buttons=allowed)
```

In `_dispatch_to_user` (around line 214):

```python
                allowed = (
                    dm_settings.update_buttons if dm_settings is not None else ALL_UPDATE_BUTTONS
                )
                await user.send(
                    view=build_chapter_update_view(
                        payload, bot=self.bot, allowed_buttons=allowed
                    )
                )
```

Add to the imports at the top:

```python
from ..ui.components.notifications import ALL_UPDATE_BUTTONS, build_chapter_update_view
```

- [ ] **Step 4: Run dispatch tests**

Run: `python -m pytest tests/test_notification_dispatch.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwa_bot/cogs/updates.py tests/test_notification_dispatch.py
git commit -m "UpdatesCog: pass update_buttons from settings into view factory"
```

---

## Task 9: Register DynamicItem classes in `setup_hook`

**Files:**
- Modify: `src/manhwa_bot/bot.py`

- [ ] **Step 1: Add the registration**

At the top of `src/manhwa_bot/bot.py`, near the other ui imports:

```python
from .ui.components.notification_buttons import (
    BookmarkButton,
    MarkReadButton,
    SubscribeToggleButton,
)
```

In `setup_hook`, after the cog-loading loop, add:

```python
        self.add_dynamic_items(MarkReadButton, BookmarkButton, SubscribeToggleButton)
        _log.info(
            "Registered persistent chapter-update buttons: MarkRead, Bookmark, SubscribeToggle"
        )
```

- [ ] **Step 2: Smoke-test the imports**

Run: `python -c "from manhwa_bot.bot import ManhwaBot; print('ok')"`
Expected: prints `ok` with no import errors.

- [ ] **Step 3: Commit**

```bash
git add src/manhwa_bot/bot.py
git commit -m "Register chapter-update DynamicItem buttons in setup_hook"
```

---

## Task 10: Settings 404 fix — defer + edit_original_response

**Files:**
- Modify: `src/manhwa_bot/ui/components/settings.py`
- Create: `tests/test_settings_refresh_defer.py`

- [ ] **Step 1: Write the failing regression test**

Create `tests/test_settings_refresh_defer.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_settings_refresh_defer.py -v`
Expected: FAIL — current `_refresh` calls `interaction.response.edit_message(...)`.

- [ ] **Step 3: Patch `_refresh`**

In `src/manhwa_bot/ui/components/settings.py`, replace `_refresh`:

```python
    async def _refresh(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        self._settings = await self._store.get(self._guild_id)
        self._scanlator_overrides = await self._store.list_scanlator_channels(self._guild_id)
        guild = interaction.guild
        me = guild.me if guild else None
        self._warnings = collect_warnings(self._settings, guild, me) if guild and me else []
        self._rebuild()
        await interaction.edit_original_response(view=self)
```

- [ ] **Step 4: Run the regression test**

Run: `python -m pytest tests/test_settings_refresh_defer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwa_bot/ui/components/settings.py tests/test_settings_refresh_defer.py
git commit -m "Fix /settings 404: defer interaction before DB queries in _refresh"
```

---

## Task 11: Settings multi-select branch + summary line

**Files:**
- Modify: `src/manhwa_bot/ui/components/settings.py`
- Create: `tests/test_settings_update_buttons_multiselect.py`

- [ ] **Step 1: Write the failing settings UI tests**

Note: `discord.ui.Select.values` is populated by Discord at interaction-dispatch time and isn't reliably settable in unit tests. We test against an internal helper `_build_update_buttons_select(current)` (added in step 3) that returns the configured Select widget, and test the save callback through a tiny `_FakeSelect` stand-in for `_current_dynamic_item()`.

Create `tests/test_settings_update_buttons_multiselect.py`:

```python
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
            view = SettingsLayoutView(
                bot, guild_id=1, settings=settings, scanlator_overrides=[]
            )

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


def test_on_buttons_picked_persists_empty_selection() -> None:
    """When the user clears all options, the store row reflects an empty set."""

    class _FakeSelect:
        # Stand-in for the discord.ui.Select held by `_current_dynamic_item`.
        values: list[str] = []

    async def _run() -> None:
        tmp = tempfile.TemporaryDirectory()
        pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
        try:
            await apply_pending(pool)
            store = GuildSettingsStore(pool)
            await store.set_notifications_channel(1, 100)
            settings = await store.get(1)
            bot = SimpleNamespace(db=pool)
            view = SettingsLayoutView(
                bot, guild_id=1, settings=settings, scanlator_overrides=[]
            )

            # Swap _current_dynamic_item to return our fake widget.
            fake = _FakeSelect()
            view._current_dynamic_item = lambda: fake  # type: ignore[assignment]
            # Make _refresh a no-op so we don't need a real interaction round-trip.
            view._refresh = AsyncMock()  # type: ignore[assignment]

            # Wrap fake into the discord.ui.Select type-check used inside the
            # callback by replacing the isinstance check via a subclass.
            class _Select(discord.ui.Select, _FakeSelect):  # type: ignore[misc]
                pass

            await view._on_buttons_picked(_interaction())  # type: ignore[attr-defined]

            persisted = await store.get(1)
            assert persisted is not None
            assert persisted.update_buttons == frozenset()
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
            view = SettingsLayoutView(
                bot, guild_id=1, settings=settings, scanlator_overrides=[]
            )

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
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_settings_update_buttons_multiselect.py -v`
Expected: FAIL — `_SETTING_UPDATE_BUTTONS` does not exist and `_on_buttons_picked` is unimplemented.

- [ ] **Step 3: Edit `settings.py`**

In `src/manhwa_bot/ui/components/settings.py`:

1. Import the constants at the top, after the existing imports:

```python
from .notification_buttons import (
    UPDATE_BUTTON_KEYS,
    UPDATE_BUTTON_LABELS,
)
```

2. Rename the constant `_SETTING_SHOW_UPDATE_BUTTONS` to `_SETTING_UPDATE_BUTTONS` and adjust every usage. Remove it from `_BOOL_SETTINGS`.

3. Replace the entry in `_MAIN_OPTIONS` (currently labelled "Show buttons for chapter updates") with:

```python
    discord.SelectOption(
        label="Buttons shown on chapter updates",
        value=_SETTING_UPDATE_BUTTONS,
        emoji="🔘",
        description="Pick which buttons appear on update notifications.",
    ),
```

4. In `_build_settings_container`, replace the `show_buttons = _bool_emoji(...)` line and the body line that uses it with:

```python
    if settings is None or not settings.update_buttons:
        update_buttons_display = "Disabled"
    else:
        labels = [
            UPDATE_BUTTON_LABELS[k][0]
            for k in UPDATE_BUTTON_KEYS
            if k in settings.update_buttons
        ]
        update_buttons_display = ", ".join(labels)
```

and change the body string from `f"**🔘 Show Update Buttons:** {show_buttons}\n"` to `f"**🔘 Update Buttons:** {update_buttons_display}\n"`.

5. Extract the multi-select construction into a helper and call it from `_on_main_select`. Add this method:

```python
    def _build_update_buttons_select(
        self, current: frozenset[str]
    ) -> discord.ui.Select:
        select = discord.ui.Select(
            placeholder="Pick buttons to show on update notifications (or none)…",
            min_values=0,
            max_values=len(UPDATE_BUTTON_KEYS),
            options=[
                discord.SelectOption(
                    label=UPDATE_BUTTON_LABELS[k][0],
                    value=k,
                    emoji=UPDATE_BUTTON_LABELS[k][1],
                    description=UPDATE_BUTTON_LABELS[k][2],
                    default=(k in current),
                )
                for k in UPDATE_BUTTON_KEYS
            ],
        )
        select.callback = self._on_buttons_picked  # type: ignore[assignment]
        return select
```

Then inside `_on_main_select`, after the `_BOOL_SETTINGS` branch and before the `_SETTING_SCANLATOR_CHANNELS` branch, add:

```python
        elif value == _SETTING_UPDATE_BUTTONS:
            current = self._settings.update_buttons if self._settings else frozenset(UPDATE_BUTTON_KEYS)
            self._set_dynamic(self._build_update_buttons_select(current))
```

6. Add a new callback below `_on_bool_picked`:

```python
    async def _on_buttons_picked(self, interaction: discord.Interaction) -> None:
        item = self._current_dynamic_item()
        if not isinstance(item, discord.ui.Select):
            await interaction.response.defer()
            return
        chosen = [v for v in item.values if v in UPDATE_BUTTON_KEYS]
        await self._store.set_update_buttons(self._guild_id, chosen)
        await self._refresh(interaction)
```

7. Remove the now-unused `show_buttons` variable from `_build_settings_container`. In `_read_bool`, drop the `if setting == _SETTING_SHOW_UPDATE_BUTTONS: return self._settings.show_update_buttons` branch and change the default-when-`None` line from `return setting == _SETTING_SHOW_UPDATE_BUTTONS` to `return False`. In `_on_bool_picked`, remove the `_SETTING_SHOW_UPDATE_BUTTONS` branch (it called the now-deleted `set_show_update_buttons`).

- [ ] **Step 4: Run the multi-select tests**

Run: `python -m pytest tests/test_settings_update_buttons_multiselect.py tests/test_settings_refresh_defer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwa_bot/ui/components/settings.py tests/test_settings_update_buttons_multiselect.py
git commit -m "Convert show_update_buttons toggle to multi-select in /settings"
```

---

## Task 12: DM settings multi-select

**Files:**
- Modify: `src/manhwa_bot/ui/components/settings.py` (the `DmSettingsLayoutView` section near the bottom)

- [ ] **Step 1: Write the DM-side test**

Append to `tests/test_settings_update_buttons_multiselect.py`:

```python
def test_dm_settings_renders_update_buttons_multi_select() -> None:
    from manhwa_bot.ui.components.settings import DmSettingsLayoutView
    from manhwa_bot.db.dm_settings import DmSettingsStore

    async def _run() -> None:
        tmp = tempfile.TemporaryDirectory()
        pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
        try:
            await apply_pending(pool)
            await DmSettingsStore(pool).set_update_buttons(42, ["subscribe"])
            bot = SimpleNamespace(db=pool)
            view = DmSettingsLayoutView(bot, user_id=42)
            await view.initialize()

            selects = [
                c for c in view.walk_children() if isinstance(c, discord.ui.Select)
            ]
            buttons_select = next(
                s for s in selects if s.placeholder and "buttons" in s.placeholder.lower()
            )
            default_values = {opt.value for opt in buttons_select.options if opt.default}
            assert default_values == {"subscribe"}
        finally:
            await pool.close()
            tmp.cleanup()

    asyncio.run(_run())
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_settings_update_buttons_multiselect.py::test_dm_settings_renders_update_buttons_multi_select -v`
Expected: FAIL — DM settings still has a button toggle, not a select.

- [ ] **Step 3: Replace the DM view's `_rebuild`**

In `src/manhwa_bot/ui/components/settings.py`, edit `DmSettingsLayoutView` so the state tracks the set and the row uses a Select:

```python
class DmSettingsLayoutView(BaseLayoutView):
    def __init__(self, bot: Any, user_id: int) -> None:
        super().__init__(invoker_id=user_id, timeout=2 * 24 * 60 * 60)
        self._bot = bot
        self._user_id = user_id
        self._store = DmSettingsStore(bot.db)
        self._notifications_enabled = True
        self._paid_chapter_notifs = True
        self._update_buttons: frozenset[str] = frozenset(UPDATE_BUTTON_KEYS)

    async def initialize(self) -> None:
        record = await self._store.get(self._user_id)
        if record is not None:
            self._notifications_enabled = record.notifications_enabled
            self._paid_chapter_notifs = record.paid_chapter_notifs
            self._update_buttons = record.update_buttons
        self._rebuild()

    def _container(self) -> discord.ui.Container:
        if not self._update_buttons:
            update_buttons_display = "Disabled"
        else:
            update_buttons_display = ", ".join(
                UPDATE_BUTTON_LABELS[k][0]
                for k in UPDATE_BUTTON_KEYS
                if k in self._update_buttons
            )
        body = (
            f"**🔔 DM Notifications:** {_bool_emoji(self._notifications_enabled)}\n"
            "-# Receive personal chapter update DMs from the bot.\n\n"
            f"**🔘 Update Buttons:** {update_buttons_display}\n"
            "-# Pick which buttons appear on chapter updates in DMs.\n\n"
            f"**💰 Paid Chapter Notifs:** {_bool_emoji(self._paid_chapter_notifs)}\n"
            "-# Notify me about premium / locked chapters."
        )
        return discord.ui.Container(
            discord.ui.TextDisplay("## ⚙️  DM Settings"),
            small_separator(),
            discord.ui.TextDisplay(body),
            small_separator(),
            footer_section(self._bot),
        )

    def _rebuild(self) -> None:
        self.clear_items()
        container = self._container()

        toggles_row = discord.ui.ActionRow()
        notifs_btn = discord.ui.Button(
            label=f"🔔 DM Notifications: {_bool_emoji(self._notifications_enabled)}",
            style=discord.ButtonStyle.secondary,
        )
        notifs_btn.callback = self._toggle_notifs  # type: ignore[assignment]
        toggles_row.add_item(notifs_btn)

        paid_btn = discord.ui.Button(
            label=f"💰 Paid Chapters: {_bool_emoji(self._paid_chapter_notifs)}",
            style=discord.ButtonStyle.secondary,
        )
        paid_btn.callback = self._toggle_paid  # type: ignore[assignment]
        toggles_row.add_item(paid_btn)
        container.add_item(small_separator())
        container.add_item(toggles_row)

        buttons_row = discord.ui.ActionRow()
        select = discord.ui.Select(
            placeholder="Pick buttons to show on DM update notifications (or none)…",
            min_values=0,
            max_values=len(UPDATE_BUTTON_KEYS),
            options=[
                discord.SelectOption(
                    label=UPDATE_BUTTON_LABELS[k][0],
                    value=k,
                    emoji=UPDATE_BUTTON_LABELS[k][1],
                    description=UPDATE_BUTTON_LABELS[k][2],
                    default=(k in self._update_buttons),
                )
                for k in UPDATE_BUTTON_KEYS
            ],
        )
        select.callback = self._on_update_buttons_picked  # type: ignore[assignment]
        buttons_row.add_item(select)
        container.add_item(small_separator())
        container.add_item(buttons_row)

        self.add_item(container)

    async def _toggle_notifs(self, interaction: discord.Interaction) -> None:
        self._notifications_enabled = not self._notifications_enabled
        await self._store.set_notifications_enabled(self._user_id, self._notifications_enabled)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _toggle_paid(self, interaction: discord.Interaction) -> None:
        self._paid_chapter_notifs = not self._paid_chapter_notifs
        await self._store.set_paid_chapter_notifs(self._user_id, self._paid_chapter_notifs)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_update_buttons_picked(self, interaction: discord.Interaction) -> None:
        select = next(
            c for c in self.walk_children()
            if isinstance(c, discord.ui.Select)
            and c.placeholder
            and "buttons" in c.placeholder.lower()
        )
        chosen = [v for v in select.values if v in UPDATE_BUTTON_KEYS]
        await self._store.set_update_buttons(self._user_id, chosen)
        self._update_buttons = frozenset(chosen)
        self._rebuild()
        if not interaction.response.is_done():
            await interaction.response.edit_message(view=self)
        else:
            await interaction.edit_original_response(view=self)
```

(Delete the old `_toggle_buttons` method.)

- [ ] **Step 4: Run all settings tests**

Run: `python -m pytest tests/test_settings_update_buttons_multiselect.py tests/test_settings_refresh_defer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/manhwa_bot/ui/components/settings.py tests/test_settings_update_buttons_multiselect.py
git commit -m "DM settings: replace update-buttons toggle with multi-select"
```

---

## Task 13: Full test suite + ruff sweep

**Files:** (none — verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -v`
Expected: all tests PASS.

- [ ] **Step 2: Run ruff**

Run: `python -m ruff check .` and `python -m ruff format --check .`
Expected: clean. If ruff reports issues, fix them and re-run.

- [ ] **Step 3: Commit any ruff fixes**

```bash
git add -A
git commit -m "Lint pass after update-buttons rollout"
```

(Skip the commit if ruff reported nothing.)

---

## Out-of-scope follow-ups

- `src/manhwa_bot/ui/components/base.py:256` — `except discord.HTTPException, AttributeError:` parses on Python 3.14 but only catches `HTTPException`. Fix to `except (discord.HTTPException, AttributeError):`.

---

## Self-review notes

- Spec section A ↔ Task 10.
- Spec section B (view) ↔ Tasks 5, 6, 7, 8, 9.
- Spec section C ↔ Tasks 1, 2, 3, 4, 11, 12.
- DynamicItem custom_ids stay ≤100 chars (verified by Task 5 step 1 final test).
- `update_buttons` ordering is canonical (`UPDATE_BUTTON_KEYS`) at both serialize and render time — consistent across files.
- `_SETTING_UPDATE_BUTTONS` constant is introduced in Task 11 and consumed by tests in the same task; no out-of-order references.
