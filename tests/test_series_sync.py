from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

from manhwa_bot.crawler.series_sync import collect_series_reference_refs, handle_series_sync_request
from manhwa_bot.db.bookmarks import BookmarkStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.subscriptions import SubscriptionStore
from manhwa_bot.db.tracked import TrackedStore


class _FakeCrawler:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []

    async def request(self, type_: str, **kwargs):
        self.requests.append((type_, dict(kwargs)))
        return {"accepted": True}


def test_series_sync_handler_submits_union_of_local_references() -> None:
    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await DbPool.open(str(Path(tmp) / "test.db"))
            try:
                await apply_pending(pool)
                bookmarks = BookmarkStore(pool)
                tracked = TrackedStore(pool)
                subs = SubscriptionStore(pool)

                await bookmarks.upsert_bookmark(1, "site", "shared")
                await bookmarks.upsert_bookmark(2, "site", "bookmarked-only")
                await tracked.upsert_series("site", "shared", "https://site.test/shared", "Shared")
                await tracked.add_to_guild(10, "site", "shared")
                await tracked.upsert_series(
                    "site", "tracked-only", "https://site.test/tracked-only", "Tracked"
                )
                await tracked.add_to_guild(11, "site", "tracked-only")
                await subs.subscribe(3, 10, "site", "shared")
                await subs.subscribe(4, 10, "site", "subscribed-only")

                crawler = _FakeCrawler()
                bot = SimpleNamespace(
                    db=pool,
                    crawler=crawler,
                    config=SimpleNamespace(
                        crawler=SimpleNamespace(client_id="", consumer_key="bot-consumer")
                    ),
                )
                await handle_series_sync_request(
                    bot,
                    {
                        "request_id": "sync-1",
                        "type": "series_sync_request",
                        "data": {"client_reference_ttl_days": 365},
                    },
                )

                assert crawler.requests == [
                    (
                        "series_sync_submit",
                        {
                            "sync_request_id": "sync-1",
                            "client_id": "bot-consumer",
                            "client_reference_ttl_days": 365,
                            "refs": [
                                {
                                    "website_key": "site",
                                    "url_name": "bookmarked-only",
                                    "bookmarks": 1,
                                    "tracked": 0,
                                    "subscriptions": 0,
                                },
                                {
                                    "website_key": "site",
                                    "url_name": "shared",
                                    "bookmarks": 1,
                                    "tracked": 1,
                                    "subscriptions": 1,
                                },
                                {
                                    "website_key": "site",
                                    "url_name": "subscribed-only",
                                    "bookmarks": 0,
                                    "tracked": 0,
                                    "subscriptions": 1,
                                },
                                {
                                    "website_key": "site",
                                    "url_name": "tracked-only",
                                    "bookmarks": 0,
                                    "tracked": 1,
                                    "subscriptions": 0,
                                },
                            ],
                        },
                    )
                ]
            finally:
                await pool.close()

    asyncio.run(run())


def test_collect_series_reference_refs_merges_counts() -> None:
    refs = collect_series_reference_refs(
        bookmark_refs=[{"website_key": "site", "url_name": "a", "bookmarks": 2}],
        tracked_refs=[{"website_key": "site", "url_name": "a", "tracked": 1}],
        subscription_refs=[{"website_key": "site", "url_name": "b", "subscriptions": 3}],
    )

    assert refs == [
        {
            "website_key": "site",
            "url_name": "a",
            "bookmarks": 2,
            "tracked": 1,
            "subscriptions": 0,
        },
        {
            "website_key": "site",
            "url_name": "b",
            "bookmarks": 0,
            "tracked": 0,
            "subscriptions": 3,
        },
    ]
