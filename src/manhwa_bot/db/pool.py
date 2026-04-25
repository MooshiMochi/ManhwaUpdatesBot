"""Thin aiosqlite wrapper with WAL mode, FK enforcement, and transaction helpers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite


class DbPool:
    """Manages a single aiosqlite connection with WAL + FK pragmas applied."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @classmethod
    async def open(cls, path: str) -> DbPool:
        # isolation_level=None → pure autocommit; we manage transactions explicitly.
        conn = await aiosqlite.connect(path, isolation_level=None)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA synchronous=NORMAL")
        return cls(conn)

    async def close(self) -> None:
        await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await self._conn.close()

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[aiosqlite.Connection]:
        yield self._conn

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        # In autocommit mode each statement commits immediately; no explicit commit needed.
        return await self._conn.execute(sql, params)

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchall()

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[aiosqlite.Connection]:
        await self._conn.execute("BEGIN")
        try:
            yield self._conn
            await self._conn.execute("COMMIT")
        except Exception:
            await self._conn.execute("ROLLBACK")
            raise
