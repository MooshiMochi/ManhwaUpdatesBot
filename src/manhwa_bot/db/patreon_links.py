"""Store for the patreon_links table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .pool import DbPool


@dataclass(frozen=True)
class PatreonLink:
    discord_user_id: int
    patreon_user_id: str
    tier_ids: str
    cents: int
    refreshed_at: str
    expires_at: str


def _row_to_link(row: Any) -> PatreonLink:
    return PatreonLink(
        discord_user_id=row["discord_user_id"],
        patreon_user_id=row["patreon_user_id"],
        tier_ids=row["tier_ids"],
        cents=row["cents"],
        refreshed_at=row["refreshed_at"],
        expires_at=row["expires_at"],
    )


class PatreonLinkStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def upsert(
        self,
        discord_user_id: int,
        patreon_user_id: str,
        tier_ids: str,
        cents: int,
        refreshed_at: str,
        expires_at: str,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO patreon_links
              (discord_user_id, patreon_user_id, tier_ids, cents, refreshed_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(discord_user_id) DO UPDATE SET
              patreon_user_id = excluded.patreon_user_id,
              tier_ids        = excluded.tier_ids,
              cents           = excluded.cents,
              refreshed_at    = excluded.refreshed_at,
              expires_at      = excluded.expires_at
            """,
            (discord_user_id, patreon_user_id, tier_ids, cents, refreshed_at, expires_at),
        )

    async def get(self, discord_user_id: int) -> PatreonLink | None:
        row = await self._pool.fetchone(
            "SELECT * FROM patreon_links WHERE discord_user_id = ?", (discord_user_id,)
        )
        return _row_to_link(row) if row else None

    async def is_active(self, discord_user_id: int) -> bool:
        row = await self._pool.fetchone(
            "SELECT 1 FROM patreon_links WHERE discord_user_id = ? AND expires_at > datetime('now')",
            (discord_user_id,),
        )
        return row is not None

    async def delete(self, discord_user_id: int) -> None:
        await self._pool.execute(
            "DELETE FROM patreon_links WHERE discord_user_id = ?", (discord_user_id,)
        )

    async def list_active(self) -> list[PatreonLink]:
        rows = await self._pool.fetchall(
            "SELECT * FROM patreon_links WHERE expires_at > datetime('now') ORDER BY discord_user_id"
        )
        return [_row_to_link(r) for r in rows]
