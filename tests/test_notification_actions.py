from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.notification_actions import NotificationActionContextStore
from manhwa_bot.db.pool import DbPool


def test_notification_action_context_is_short_stable_and_durable() -> None:
    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "bot.db")
            pool = await DbPool.open(path)
            await apply_pending(pool)
            store = NotificationActionContextStore(pool)
            first = await store.get_or_create(
                website_key="comix",
                url_name=(
                    "the-final-boss-prince-is-somehow-obsessed-with-the-chubby-villainess-"
                    "reincarnated-me"
                ),
                series_url="https://comix.to/title/e35qr-the-final-boss-prince",
                chapter_index=102,
                chapter_name="Chapter 102",
                chapter_url="https://comix.to/title/e35qr-the-final-boss-prince/102",
            )
            again = await store.get_or_create(
                website_key=first.website_key,
                url_name=first.url_name,
                series_url=first.series_url,
                chapter_index=first.chapter_index,
                chapter_name=first.chapter_name,
                chapter_url=first.chapter_url,
            )
            assert first.token == again.token
            assert len(first.token) <= 24
            await pool.close()

            reopened = await DbPool.open(path)
            try:
                restored = await NotificationActionContextStore(reopened).get(first.token)
                assert restored == first
            finally:
                await reopened.close()

    asyncio.run(run())
