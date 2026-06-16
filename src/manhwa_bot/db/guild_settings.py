"""Store for guild_settings and guild_scanlator_channels tables."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .pool import DbPool

_VALID_UPDATE_BUTTONS: frozenset[str] = frozenset(
    {"mark_read", "bookmark", "subscribe", "open_chapter"}
)

_VALID_NSFW_SPOILER_MODES: frozenset[str] = frozenset(
    {"always", "never", "nsfw_channel_aware"}
)


def _clean_nsfw_mode(value: object) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in _VALID_NSFW_SPOILER_MODES else "always"


def _parse_update_buttons(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    return frozenset(
        token.strip() for token in raw.split(",") if token.strip() in _VALID_UPDATE_BUTTONS
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
    nsfw_spoiler_mode: str = "always"


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
        nsfw_spoiler_mode=_clean_nsfw_mode(_optional_row(row, "nsfw_spoiler_mode")),
    )


def _optional_row(row: Any, key: str) -> object:
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


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
               default_ping_role_id, bot_manager_role_id,
               paid_chapter_notifs, auto_create_role, update_buttons, nsfw_spoiler_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              notifications_channel_id = excluded.notifications_channel_id,
              system_alerts_channel_id = excluded.system_alerts_channel_id,
              default_ping_role_id     = excluded.default_ping_role_id,
              bot_manager_role_id      = excluded.bot_manager_role_id,
              paid_chapter_notifs      = excluded.paid_chapter_notifs,
              auto_create_role         = excluded.auto_create_role,
              update_buttons           = excluded.update_buttons,
              nsfw_spoiler_mode        = excluded.nsfw_spoiler_mode,
              updated_at               = CURRENT_TIMESTAMP
            """,
            (
                settings.guild_id,
                settings.notifications_channel_id,
                settings.system_alerts_channel_id,
                settings.default_ping_role_id,
                settings.bot_manager_role_id,
                int(settings.paid_chapter_notifs),
                int(settings.auto_create_role),
                _serialize_update_buttons(settings.update_buttons),
                _clean_nsfw_mode(settings.nsfw_spoiler_mode),
            ),
        )

    async def set_nsfw_spoiler_mode(self, guild_id: int, mode: str) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, nsfw_spoiler_mode)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              nsfw_spoiler_mode = excluded.nsfw_spoiler_mode,
              updated_at        = CURRENT_TIMESTAMP
            """,
            (guild_id, _clean_nsfw_mode(mode)),
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

    async def set_bot_manager_role(self, guild_id: int, role_id: int | None) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, bot_manager_role_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              bot_manager_role_id = excluded.bot_manager_role_id,
              updated_at          = CURRENT_TIMESTAMP
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

    async def set_auto_create_role(self, guild_id: int, enabled: bool) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, auto_create_role)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              auto_create_role = excluded.auto_create_role,
              updated_at       = CURRENT_TIMESTAMP
            """,
            (guild_id, int(enabled)),
        )

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

    async def list_with_system_alerts(self) -> list[GuildSettings]:
        """Return guild settings rows that have a system-alerts channel configured."""
        rows = await self._pool.fetchall(
            "SELECT * FROM guild_settings WHERE system_alerts_channel_id IS NOT NULL"
        )
        return [_row_to_settings(r) for r in rows]
