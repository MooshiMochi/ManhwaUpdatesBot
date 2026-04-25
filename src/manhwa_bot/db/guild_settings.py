"""Store for guild_settings and guild_scanlator_channels tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .pool import DbPool


@dataclass(frozen=True)
class GuildSettings:
    guild_id: int
    notifications_channel_id: int | None
    system_alerts_channel_id: int | None
    default_ping_role_id: int | None
    paid_chapter_notifs: bool
    updated_at: str


def _row_to_settings(row: Any) -> GuildSettings:
    return GuildSettings(
        guild_id=row["guild_id"],
        notifications_channel_id=row["notifications_channel_id"],
        system_alerts_channel_id=row["system_alerts_channel_id"],
        default_ping_role_id=row["default_ping_role_id"],
        paid_chapter_notifs=bool(row["paid_chapter_notifs"]),
        updated_at=row["updated_at"],
    )


class GuildSettingsStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def get(self, guild_id: int) -> GuildSettings | None:
        row = await self._pool.fetchone(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        return _row_to_settings(row) if row else None

    async def upsert(self, settings: GuildSettings) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings
              (guild_id, notifications_channel_id, system_alerts_channel_id,
               default_ping_role_id, paid_chapter_notifs)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              notifications_channel_id = excluded.notifications_channel_id,
              system_alerts_channel_id = excluded.system_alerts_channel_id,
              default_ping_role_id     = excluded.default_ping_role_id,
              paid_chapter_notifs      = excluded.paid_chapter_notifs,
              updated_at               = CURRENT_TIMESTAMP
            """,
            (
                settings.guild_id,
                settings.notifications_channel_id,
                settings.system_alerts_channel_id,
                settings.default_ping_role_id,
                int(settings.paid_chapter_notifs),
            ),
        )

    async def set_notifications_channel(self, guild_id: int, channel_id: int | None) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, notifications_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              notifications_channel_id = excluded.notifications_channel_id,
              updated_at               = CURRENT_TIMESTAMP
            """,
            (guild_id, channel_id),
        )

    async def set_system_alerts_channel(self, guild_id: int, channel_id: int | None) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, system_alerts_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              system_alerts_channel_id = excluded.system_alerts_channel_id,
              updated_at               = CURRENT_TIMESTAMP
            """,
            (guild_id, channel_id),
        )

    async def set_default_ping_role(self, guild_id: int, role_id: int | None) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, default_ping_role_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              default_ping_role_id = excluded.default_ping_role_id,
              updated_at           = CURRENT_TIMESTAMP
            """,
            (guild_id, role_id),
        )

    async def set_paid_chapter_notifs(self, guild_id: int, enabled: bool) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, paid_chapter_notifs)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              paid_chapter_notifs = excluded.paid_chapter_notifs,
              updated_at          = CURRENT_TIMESTAMP
            """,
            (guild_id, int(enabled)),
        )

    async def set_scanlator_channel(self, guild_id: int, website_key: str, channel_id: int) -> None:
        # Ensure guild_settings row exists so FK is satisfied.
        await self._pool.execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
        )
        await self._pool.execute(
            """
            INSERT INTO guild_scanlator_channels (guild_id, website_key, channel_id)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, website_key) DO UPDATE SET channel_id = excluded.channel_id
            """,
            (guild_id, website_key, channel_id),
        )

    async def clear_scanlator_channel(self, guild_id: int, website_key: str) -> None:
        await self._pool.execute(
            "DELETE FROM guild_scanlator_channels WHERE guild_id = ? AND website_key = ?",
            (guild_id, website_key),
        )

    async def list_scanlator_channels(self, guild_id: int) -> list[dict]:
        rows = await self._pool.fetchall(
            "SELECT * FROM guild_scanlator_channels WHERE guild_id = ?", (guild_id,)
        )
        return [dict(r) for r in rows]
