"""Store for tracked_series and tracked_in_guild tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .pool import DbPool


@dataclass(frozen=True)
class TrackedSeries:
    website_key: str
    url_name: str
    series_url: str
    title: str
    cover_url: str | None
    status: str | None
    added_at: str
    last_chapter_text: str | None = None
    last_chapter_url: str | None = None
    last_chapter_at: str | None = None


@dataclass(frozen=True)
class GuildTrackedSeries:
    website_key: str
    url_name: str
    series_url: str
    title: str
    cover_url: str | None
    status: str | None
    added_at: str
    guild_id: int
    ping_role_id: int | None
    last_chapter_text: str | None = None
    last_chapter_url: str | None = None
    last_chapter_at: str | None = None


def _row_to_tracked(row: Any) -> TrackedSeries:
    return TrackedSeries(
        website_key=row["website_key"],
        url_name=row["url_name"],
        series_url=row["series_url"],
        title=row["title"],
        cover_url=row["cover_url"],
        status=row["status"],
        added_at=row["added_at"],
        last_chapter_text=_optional(row, "last_chapter_text"),
        last_chapter_url=_optional(row, "last_chapter_url"),
        last_chapter_at=_optional(row, "last_chapter_at"),
    )


def _row_to_guild_tracked(row: Any) -> GuildTrackedSeries:
    return GuildTrackedSeries(
        website_key=row["website_key"],
        url_name=row["url_name"],
        series_url=row["series_url"],
        title=row["title"],
        cover_url=row["cover_url"],
        status=row["status"],
        added_at=row["added_at"],
        guild_id=row["guild_id"],
        ping_role_id=row["ping_role_id"],
        last_chapter_text=_optional(row, "last_chapter_text"),
        last_chapter_url=_optional(row, "last_chapter_url"),
        last_chapter_at=_optional(row, "last_chapter_at"),
    )


def _optional(row: Any, key: str) -> Any:
    try:
        return row[key]
    except KeyError, IndexError:
        return None


class TrackedStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def upsert_series(
        self,
        website_key: str,
        url_name: str,
        series_url: str,
        title: str,
        cover_url: str | None = None,
        status: str | None = None,
        *,
        last_chapter_text: str | None = None,
        last_chapter_url: str | None = None,
        last_chapter_at: str | None = None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO tracked_series (
              website_key, url_name, series_url, title, cover_url, status,
              last_chapter_text, last_chapter_url, last_chapter_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(website_key, url_name) DO UPDATE SET
              series_url        = excluded.series_url,
              title             = excluded.title,
              cover_url         = excluded.cover_url,
              status            = excluded.status,
              last_chapter_text = COALESCE(excluded.last_chapter_text, last_chapter_text),
              last_chapter_url  = COALESCE(excluded.last_chapter_url,  last_chapter_url),
              last_chapter_at   = COALESCE(excluded.last_chapter_at,   last_chapter_at)
            """,
            (
                website_key,
                url_name,
                series_url,
                title,
                cover_url,
                status,
                last_chapter_text,
                last_chapter_url,
                last_chapter_at,
            ),
        )

    async def update_latest_chapter(
        self,
        website_key: str,
        url_name: str,
        *,
        text: str | None,
        url: str | None,
        at: str | None,
    ) -> None:
        await self._pool.execute(
            """
            UPDATE tracked_series
            SET last_chapter_text = ?,
                last_chapter_url  = ?,
                last_chapter_at   = ?
            WHERE website_key = ? AND url_name = ?
            """,
            (text, url, at, website_key, url_name),
        )

    async def add_to_guild(
        self,
        guild_id: int,
        website_key: str,
        url_name: str,
        ping_role_id: int | None = None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT OR IGNORE INTO tracked_in_guild (guild_id, website_key, url_name, ping_role_id)
            VALUES (?, ?, ?, ?)
            """,
            (guild_id, website_key, url_name, ping_role_id),
        )

    async def update_ping_role(
        self,
        guild_id: int,
        website_key: str,
        url_name: str,
        ping_role_id: int | None,
    ) -> None:
        await self._pool.execute(
            """
            UPDATE tracked_in_guild SET ping_role_id = ?
            WHERE guild_id = ? AND website_key = ? AND url_name = ?
            """,
            (ping_role_id, guild_id, website_key, url_name),
        )

    async def remove_from_guild(
        self, guild_id: int, website_key: str, url_name: str
    ) -> tuple[bool, int]:
        """Delete a guild's tracking row and return (was_last_guild, remaining_count)."""
        await self._pool.execute(
            "DELETE FROM tracked_in_guild WHERE guild_id = ? AND website_key = ? AND url_name = ?",
            (guild_id, website_key, url_name),
        )
        row = await self._pool.fetchone(
            "SELECT COUNT(*) AS cnt FROM tracked_in_guild WHERE website_key = ? AND url_name = ?",
            (website_key, url_name),
        )
        remaining = row["cnt"] if row else 0
        return (remaining == 0, remaining)

    async def delete_series(self, website_key: str, url_name: str) -> None:
        await self._pool.execute(
            "DELETE FROM tracked_series WHERE website_key = ? AND url_name = ?",
            (website_key, url_name),
        )

    async def list_for_guild(
        self, guild_id: int, *, limit: int = 25, offset: int = 0
    ) -> list[GuildTrackedSeries]:
        rows = await self._pool.fetchall(
            """
            SELECT ts.*, tig.guild_id, tig.ping_role_id
            FROM tracked_in_guild tig
            JOIN tracked_series ts USING (website_key, url_name)
            WHERE tig.guild_id = ?
            ORDER BY ts.title
            LIMIT ? OFFSET ?
            """,
            (guild_id, limit, offset),
        )
        return [_row_to_guild_tracked(r) for r in rows]

    async def find(self, website_key: str, url_name: str) -> TrackedSeries | None:
        row = await self._pool.fetchone(
            "SELECT * FROM tracked_series WHERE website_key = ? AND url_name = ?",
            (website_key, url_name),
        )
        return _row_to_tracked(row) if row else None

    async def list_guilds_tracking(
        self, website_key: str, url_name: str
    ) -> list[GuildTrackedSeries]:
        rows = await self._pool.fetchall(
            """
            SELECT ts.*, tig.guild_id, tig.ping_role_id
            FROM tracked_in_guild tig
            JOIN tracked_series ts USING (website_key, url_name)
            WHERE tig.website_key = ? AND tig.url_name = ?
            """,
            (website_key, url_name),
        )
        return [_row_to_guild_tracked(r) for r in rows]

    async def count_for_guild(self, guild_id: int) -> int:
        row = await self._pool.fetchone(
            "SELECT COUNT(*) AS cnt FROM tracked_in_guild WHERE guild_id = ?",
            (guild_id,),
        )
        return row["cnt"] if row else 0
