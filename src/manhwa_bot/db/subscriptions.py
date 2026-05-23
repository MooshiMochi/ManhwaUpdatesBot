"""Store for the subscriptions table."""

from __future__ import annotations

from .pool import DbPool


class SubscriptionStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def subscribe(self, user_id: int, guild_id: int, website_key: str, url_name: str) -> None:
        await self._pool.execute(
            """
            INSERT OR IGNORE INTO subscriptions (user_id, guild_id, website_key, url_name)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, guild_id, website_key, url_name),
        )

    async def unsubscribe(
        self, user_id: int, guild_id: int, website_key: str, url_name: str
    ) -> None:
        await self._pool.execute(
            """
            DELETE FROM subscriptions
            WHERE user_id = ? AND guild_id = ? AND website_key = ? AND url_name = ?
            """,
            (user_id, guild_id, website_key, url_name),
        )

    async def unsubscribe_all_for_user(self, user_id: int, *, guild_id: int | None = None) -> None:
        if guild_id is not None:
            await self._pool.execute(
                "DELETE FROM subscriptions WHERE user_id = ? AND guild_id = ?",
                (user_id, guild_id),
            )
        else:
            await self._pool.execute(
                "DELETE FROM subscriptions WHERE user_id = ?",
                (user_id,),
            )

    async def list_for_user(
        self,
        user_id: int,
        *,
        guild_id: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[dict]:
        if guild_id is not None:
            rows = await self._pool.fetchall(
                """
                SELECT s.*, t.title, t.series_url
                FROM subscriptions s
                LEFT JOIN tracked_series t
                  ON t.website_key = s.website_key AND t.url_name = s.url_name
                WHERE s.user_id = ? AND s.guild_id = ?
                ORDER BY s.subscribed_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, guild_id, limit, offset),
            )
        else:
            rows = await self._pool.fetchall(
                """
                SELECT s.*, t.title, t.series_url
                FROM subscriptions s
                LEFT JOIN tracked_series t
                  ON t.website_key = s.website_key AND t.url_name = s.url_name
                WHERE s.user_id = ?
                ORDER BY s.subscribed_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            )
        return [dict(r) for r in rows]

    async def list_subscribers_for_series(
        self,
        website_key: str,
        url_name: str,
        *,
        guild_id: int | None = None,
    ) -> list[int]:
        if guild_id is not None:
            rows = await self._pool.fetchall(
                """
                SELECT user_id FROM subscriptions
                WHERE website_key = ? AND url_name = ? AND guild_id = ?
                """,
                (website_key, url_name, guild_id),
            )
        else:
            rows = await self._pool.fetchall(
                "SELECT user_id FROM subscriptions WHERE website_key = ? AND url_name = ?",
                (website_key, url_name),
            )
        return [r["user_id"] for r in rows]

    async def is_subscribed(
        self, user_id: int, guild_id: int, website_key: str, url_name: str
    ) -> bool:
        row = await self._pool.fetchone(
            """
            SELECT 1 FROM subscriptions
            WHERE user_id = ? AND guild_id = ? AND website_key = ? AND url_name = ?
            """,
            (user_id, guild_id, website_key, url_name),
        )
        return row is not None

    async def list_distinct_series_refs(self) -> list[dict[str, int | str]]:
        rows = await self._pool.fetchall(
            """
            SELECT website_key, url_name, COUNT(*) AS subscriptions
            FROM subscriptions
            GROUP BY website_key, url_name
            """
        )
        return [
            {
                "website_key": str(row["website_key"]),
                "url_name": str(row["url_name"]),
                "subscriptions": int(row["subscriptions"]),
            }
            for row in rows
        ]
