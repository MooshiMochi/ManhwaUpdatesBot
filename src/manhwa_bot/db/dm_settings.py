"""Store for the dm_settings table."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .guild_settings import (
    _clean_nsfw_mode,
    _optional_row,
    _parse_update_buttons,
    _serialize_update_buttons,
)
from .pool import DbPool


@dataclass(frozen=True)
class DmSettings:
    user_id: int
    notifications_enabled: bool
    paid_chapter_notifs: bool
    update_buttons: frozenset[str]
    updated_at: str
    nsfw_spoiler_mode: str = "always"


def _row_to_dm_settings(row: Any) -> DmSettings:
    return DmSettings(
        user_id=row["user_id"],
        notifications_enabled=bool(row["notifications_enabled"]),
        paid_chapter_notifs=bool(row["paid_chapter_notifs"]),
        update_buttons=_parse_update_buttons(row["update_buttons"]),
        updated_at=row["updated_at"],
        nsfw_spoiler_mode=_clean_nsfw_mode(_optional_row(row, "nsfw_spoiler_mode")),
    )


class DmSettingsStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def get(self, user_id: int) -> DmSettings | None:
        row = await self._pool.fetchone("SELECT * FROM dm_settings WHERE user_id = ?", (user_id,))
        return _row_to_dm_settings(row) if row else None

    async def upsert(self, settings: DmSettings) -> None:
        await self._pool.execute(
            """
            INSERT INTO dm_settings
              (user_id, notifications_enabled, paid_chapter_notifs, update_buttons,
               nsfw_spoiler_mode)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              notifications_enabled = excluded.notifications_enabled,
              paid_chapter_notifs   = excluded.paid_chapter_notifs,
              update_buttons        = excluded.update_buttons,
              nsfw_spoiler_mode     = excluded.nsfw_spoiler_mode,
              updated_at            = CURRENT_TIMESTAMP
            """,
            (
                settings.user_id,
                int(settings.notifications_enabled),
                int(settings.paid_chapter_notifs),
                _serialize_update_buttons(settings.update_buttons),
                _clean_nsfw_mode(settings.nsfw_spoiler_mode),
            ),
        )

    async def set_nsfw_spoiler_mode(self, user_id: int, mode: str) -> None:
        await self._pool.execute(
            """
            INSERT INTO dm_settings (user_id, nsfw_spoiler_mode)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              nsfw_spoiler_mode = excluded.nsfw_spoiler_mode,
              updated_at        = CURRENT_TIMESTAMP
            """,
            (user_id, _clean_nsfw_mode(mode)),
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
