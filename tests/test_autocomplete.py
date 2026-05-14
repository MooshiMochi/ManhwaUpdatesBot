from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from manhwa_bot import autocomplete
from manhwa_bot.db.bookmarks import BookmarkStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.subscriptions import SubscriptionStore
from manhwa_bot.db.tracked import TrackedStore


async def _make_pool(tmp: str) -> DbPool:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    return pool


def _interaction(*, pool: DbPool | None = None, crawler: Any | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        guild=SimpleNamespace(id=100),
        user=SimpleNamespace(id=200),
        client=SimpleNamespace(db=pool, crawler=crawler),
    )


def test_tracked_manga_autocomplete_uses_prefix_label_and_filter() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                store = TrackedStore(pool)
                await store.upsert_series(
                    "asura", "solo-leveling", "https://example.test/solo", "Solo Leveling"
                )
                await store.upsert_series(
                    "comick", "solo-leveling", "https://example.test/comick-solo", "Solo Leveling"
                )
                await store.add_to_guild(100, "asura", "solo-leveling")
                await store.add_to_guild(100, "comick", "solo-leveling")

                choices = await autocomplete.tracked_manga_in_guild(
                    _interaction(pool=pool), "(asu Solo"
                )

                assert [(choice.name, choice.value) for choice in choices] == [
                    ("(asura) Solo Leveling", "asura:solo-leveling")
                ]
            finally:
                await pool.close()

    asyncio.run(_run())


def test_subscription_and_bookmark_autocomplete_use_prefix_labels_and_filters() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                await SubscriptionStore(pool).subscribe(200, 100, "asura", "solo-leveling")
                await SubscriptionStore(pool).subscribe(200, 100, "comick", "solo-leveling")
                await BookmarkStore(pool).upsert_bookmark(200, "asura", "solo-leveling")
                await BookmarkStore(pool).upsert_bookmark(200, "comick", "solo-leveling")

                sub_choices = await autocomplete.user_subscribed_manga(
                    _interaction(pool=pool), "(asu solo"
                )
                bookmark_choices = await autocomplete.user_bookmarks(
                    _interaction(pool=pool), "(asu solo"
                )

                assert [(choice.name, choice.value) for choice in sub_choices] == [
                    ("(asura) solo-leveling", "asura:solo-leveling")
                ]
                assert [(choice.name, choice.value) for choice in bookmark_choices] == [
                    ("(asura) solo-leveling", "asura:solo-leveling")
                ]
            finally:
                await pool.close()

    asyncio.run(_run())


def test_track_new_autocomplete_queries_crawler_for_empty_input() -> None:
    async def _run() -> None:
        calls: list[dict[str, Any]] = []

        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                calls.append({"type": type_, **fields})
                return {
                    "results": [
                        {
                            "website_key": "asura",
                            "series_url": "https://example.test/solo",
                            "title": "Solo Leveling",
                        }
                    ]
                }

        autocomplete.clear_track_new_autocomplete_cache()
        choices = await autocomplete.track_new_url_or_search(_interaction(crawler=Crawler()), "")

        assert calls == [{"type": "autocomplete", "query": "", "limit": 10}]
        assert [(choice.name, choice.value) for choice in choices] == [
            ("(asura) Solo Leveling", "asura|https://example.test/solo")
        ]

    asyncio.run(_run())


def test_all_manga_autocomplete_queries_crawler_catalog() -> None:
    async def _run() -> None:
        calls: list[dict[str, Any]] = []

        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                calls.append({"type": type_, **fields})
                return {
                    "results": [
                        {
                            "website_key": "toongod",
                            "series_url": "https://www.toongod.org/webtoon/someone-stop-her-uncensored/",
                            "title": "Someone Stop Her",
                        }
                    ]
                }

        autocomplete.clear_track_new_autocomplete_cache()
        choices = await autocomplete.all_manga(_interaction(crawler=Crawler()), "someone")

        assert calls == [{"type": "autocomplete", "query": "someone", "limit": 10}]
        assert [(choice.name, choice.value) for choice in choices] == [
            (
                "(toongod) Someone Stop Her",
                "toongod|https://www.toongod.org/webtoon/someone-stop-her-uncensored/",
            )
        ]

    asyncio.run(_run())


def test_track_new_autocomplete_reuses_cached_results() -> None:
    async def _run() -> None:
        calls: list[str] = []

        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                del type_
                calls.append(str(fields["query"]))
                return {
                    "results": [
                        {
                            "website_key": "asura",
                            "series_url": "https://example.test/solo",
                            "title": "Solo Leveling",
                        }
                    ]
                }

        autocomplete.clear_track_new_autocomplete_cache()
        interaction = _interaction(crawler=Crawler())

        first_choices = await autocomplete.track_new_url_or_search(interaction, "solo")
        second_choices = await autocomplete.track_new_url_or_search(interaction, "solo")

        assert [(choice.name, choice.value) for choice in first_choices] == [
            ("(asura) Solo Leveling", "asura|https://example.test/solo")
        ]
        assert [(choice.name, choice.value) for choice in second_choices] == [
            ("(asura) Solo Leveling", "asura|https://example.test/solo")
        ]
        assert calls == ["solo"]

    asyncio.run(_run())


def test_track_new_autocomplete_coalesces_identical_inflight_queries() -> None:
    async def _run() -> None:
        calls: list[str] = []
        release = asyncio.Event()

        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                del type_
                calls.append(str(fields["query"]))
                await release.wait()
                return {
                    "results": [
                        {
                            "website_key": "asura",
                            "series_url": "https://example.test/solo",
                            "title": "Solo Leveling",
                        }
                    ]
                }

        autocomplete.clear_track_new_autocomplete_cache()
        interaction = _interaction(crawler=Crawler())
        first = asyncio.create_task(autocomplete.track_new_url_or_search(interaction, "solo"))
        await asyncio.sleep(0)
        second = asyncio.create_task(autocomplete.track_new_url_or_search(interaction, " solo "))
        await asyncio.sleep(0)
        release.set()

        first_choices, second_choices = await asyncio.gather(first, second)

        assert [(choice.name, choice.value) for choice in first_choices] == [
            ("(asura) Solo Leveling", "asura|https://example.test/solo")
        ]
        assert [(choice.name, choice.value) for choice in second_choices] == [
            ("(asura) Solo Leveling", "asura|https://example.test/solo")
        ]
        assert calls == ["solo"]

    asyncio.run(_run())


def test_track_new_autocomplete_does_not_sleep_before_different_queries(
    monkeypatch,
) -> None:
    async def _run() -> None:
        calls: list[str] = []

        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                del type_
                calls.append(str(fields["query"]))
                return {"results": []}

        async def _fail_sleep(delay: float) -> None:
            raise AssertionError(f"autocomplete should not sleep before querying: {delay}")

        autocomplete.clear_track_new_autocomplete_cache()
        monkeypatch.setattr(autocomplete.asyncio, "sleep", _fail_sleep)
        interaction = _interaction(crawler=Crawler())

        assert await autocomplete.track_new_url_or_search(interaction, "solo") == []
        assert await autocomplete.track_new_url_or_search(interaction, "solo l") == []
        assert calls == ["solo", "solo l"]

    asyncio.run(_run())
