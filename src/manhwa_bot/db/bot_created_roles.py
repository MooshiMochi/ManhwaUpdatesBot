"""Tracks roles the bot created so they can be cleaned up when guilds leave."""

from __future__ import annotations

from .pool import DbPool


class BotCreatedRolesStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def add(self, guild_id: int, role_id: int) -> None:
        await self._pool.execute(
            "INSERT OR IGNORE INTO bot_created_roles (guild_id, role_id) VALUES (?, ?)",
            (guild_id, role_id),
        )

    async def remove(self, guild_id: int, role_id: int) -> None:
        await self._pool.execute(
            "DELETE FROM bot_created_roles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )

    async def list_for_guild(self, guild_id: int) -> list[int]:
        rows = await self._pool.fetchall(
            "SELECT role_id FROM bot_created_roles WHERE guild_id = ?",
            (guild_id,),
        )
        return [r["role_id"] for r in rows]

    async def clear_for_guild(self, guild_id: int) -> int:
        cursor = await self._pool.execute(
            "DELETE FROM bot_created_roles WHERE guild_id = ?",
            (guild_id,),
        )
        return cursor.rowcount
