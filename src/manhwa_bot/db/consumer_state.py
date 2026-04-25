"""Store for the consumer_state table."""

from __future__ import annotations

from .pool import DbPool


class ConsumerStateStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def get_last_acked(self, consumer_key: str) -> int:
        row = await self._pool.fetchone(
            "SELECT last_acked_notification FROM consumer_state WHERE consumer_key = ?",
            (consumer_key,),
        )
        return row["last_acked_notification"] if row else 0

    async def set_last_acked(self, consumer_key: str, notification_id: int) -> None:
        await self._pool.execute(
            """
            INSERT INTO consumer_state (consumer_key, last_acked_notification)
            VALUES (?, ?)
            ON CONFLICT(consumer_key) DO UPDATE SET
              last_acked_notification = excluded.last_acked_notification,
              updated_at              = CURRENT_TIMESTAMP
            """,
            (consumer_key, notification_id),
        )
