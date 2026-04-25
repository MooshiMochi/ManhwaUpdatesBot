"""Store for the dm_settings table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .pool import DbPool


@dataclass(frozen=True)
class DmSettings:
    user_id: int
    notifications_enabled: bool
    paid_chapter_notifs: bool
    updated_at: str


def _row_to_dm_settings(row: Any) -> DmSettings:
    return DmSettings(
        user_id=row["user_id"],
        notifications_enabled=bool(row["notifications_enabled"]),
        paid_chapter_notifs=bool(row["paid_chapter_notifs"]),
        updated_at=row["updated_at"],
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
            INSERT INTO dm_settings (user_id, notifications_enabled, paid_chapter_notifs)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              notifications_enabled = excluded.notifications_enabled,
              paid_chapter_notifs   = excluded.paid_chapter_notifs,
              updated_at            = CURRENT_TIMESTAMP
            """,
            (
                settings.user_id,
                int(settings.notifications_enabled),
                int(settings.paid_chapter_notifs),
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
