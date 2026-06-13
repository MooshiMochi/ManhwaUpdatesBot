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


def _interaction(
    *,
    pool: DbPool | None = None,
    crawler: Any | None = None,
    namespace: Any | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        guild=SimpleNamespace(id=100),
        user=SimpleNamespace(id=200),
        client=SimpleNamespace(db=pool, crawler=crawler),
        namespace=namespace or SimpleNamespace(),
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


def test_bookmark_autocomplete_includes_subscribed_folder_beyond_first_page() -> None:
    # The old folder-ordered LIMIT 100 fetch silently dropped 'Subscribed'
    # bookmarks (that folder sorts last) for users with many bookmarks.
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                store = BookmarkStore(pool)
                for i in range(120):
                    await store.upsert_bookmark(200, "asura", f"series-{i}", folder="Reading")
                await store.upsert_bookmark(200, "asura", "tomb-raider-king", folder="Subscribed")
                await TrackedStore(pool).upsert_series(
                    "asura",
                    "tomb-raider-king",
                    "https://example.test/tomb",
                    "Tomb Raider King",
                )

                choices = await autocomplete.user_bookmarks(_interaction(pool=pool), "tomb")

                assert [(choice.name, choice.value) for choice in choices] == [
                    ("(asura) Tomb Raider King", "asura:tomb-raider-king")
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


def test_user_bookmark_chapters_uses_selected_series_from_namespace() -> None:
    async def _run() -> None:
        calls: list[dict[str, Any]] = []

        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                calls.append({"type": type_, **fields})
                return {
                    "chapters": [
                        {"chapter": "Chapter 1", "url": "https://example.test/c1"},
                        {"chapter": "Chapter 2", "url": "https://example.test/c2"},
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                autocomplete.clear_chapter_autocomplete_cache()
                await BookmarkStore(pool).upsert_bookmark(200, "asura", "solo-leveling")
                await TrackedStore(pool).upsert_series(
                    "asura",
                    "solo-leveling",
                    "https://example.test/solo-leveling",
                    "Solo Leveling",
                )

                choices = await autocomplete.user_bookmark_chapters(
                    _interaction(
                        pool=pool,
                        crawler=Crawler(),
                        namespace=SimpleNamespace(manga="asura:solo-leveling"),
                    ),
                    "",
                )

                # Reads the crawler's cached series_data (keyed by url_name),
                # never a live chapters/info scrape.
                assert calls == [
                    {
                        "type": "series_data",
                        "website_key": "asura",
                        "url_name": "solo-leveling",
                        "allow_live": False,
                    }
                ]
                assert [(choice.name, choice.value) for choice in choices] == [
                    ("0 - Chapter 1", 0),
                    ("1 - Chapter 2", 1),
                ]
            finally:
                autocomplete.clear_chapter_autocomplete_cache()
                await pool.close()

    asyncio.run(_run())


def test_user_bookmark_chapters_filters_by_typed_value() -> None:
    async def _run() -> None:
        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                del type_, fields
                return {
                    "chapters": [
                        {"chapter": "Chapter 1"},
                        {"chapter": "Side Story 1"},
                        {"chapter": "Chapter 2"},
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                autocomplete.clear_chapter_autocomplete_cache()
                await BookmarkStore(pool).upsert_bookmark(200, "asura", "solo-leveling")

                choices = await autocomplete.user_bookmark_chapters(
                    _interaction(
                        pool=pool,
                        crawler=Crawler(),
                        namespace=SimpleNamespace(series="asura:solo-leveling"),
                    ),
                    "side",
                )

                assert [(choice.name, choice.value) for choice in choices] == [
                    ("1 - Side Story 1", 1)
                ]
            finally:
                autocomplete.clear_chapter_autocomplete_cache()
                await pool.close()

    asyncio.run(_run())


def test_user_bookmark_chapters_returns_empty_without_selected_bookmark() -> None:
    async def _run() -> None:
        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                raise AssertionError("chapter autocomplete should not query without a bookmark")

        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                autocomplete.clear_chapter_autocomplete_cache()
                choices = await autocomplete.user_bookmark_chapters(
                    _interaction(
                        pool=pool,
                        crawler=Crawler(),
                        namespace=SimpleNamespace(manga="asura:solo-leveling"),
                    ),
                    "",
                )

                assert choices == []
            finally:
                autocomplete.clear_chapter_autocomplete_cache()
                await pool.close()

    asyncio.run(_run())


def test_user_bookmark_chapters_returns_quickly_while_fetch_warms_cache(monkeypatch) -> None:
    async def _run() -> None:
        release = asyncio.Event()
        calls: list[dict[str, Any]] = []

        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                calls.append({"type": type_, **fields})
                await release.wait()
                return {
                    "chapters": [
                        {"chapter": "Chapter 1"},
                        {"chapter": "Chapter 2"},
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                await BookmarkStore(pool).upsert_bookmark(200, "asura", "solo-leveling")
                await TrackedStore(pool).upsert_series(
                    "asura",
                    "solo-leveling",
                    "https://example.test/solo-leveling",
                    "Solo Leveling",
                )
                interaction = _interaction(
                    pool=pool,
                    crawler=Crawler(),
                    namespace=SimpleNamespace(manga="asura:solo-leveling"),
                )

                monkeypatch.setattr(
                    autocomplete, "CHAPTER_AUTOCOMPLETE_WAIT_SECONDS", 0.01, raising=False
                )
                autocomplete.clear_chapter_autocomplete_cache()

                first_task = asyncio.create_task(
                    autocomplete.user_bookmark_chapters(interaction, "")
                )
                await asyncio.sleep(0)
                first = await asyncio.wait_for(first_task, timeout=0.2)
                assert first == []
                assert calls == [
                    {
                        "type": "series_data",
                        "website_key": "asura",
                        "url_name": "solo-leveling",
                        "allow_live": False,
                    }
                ]

                release.set()
                await asyncio.sleep(0)
                await asyncio.sleep(0)

                second = await autocomplete.user_bookmark_chapters(interaction, "2")
                assert [(choice.name, choice.value) for choice in second] == [("1 - Chapter 2", 1)]
                assert len(calls) == 1
            finally:
                autocomplete.clear_chapter_autocomplete_cache()
                await pool.close()

    asyncio.run(_run())


def test_user_bookmark_chapters_uses_url_name_for_untracked_bookmark() -> None:
    # Untracked bookmarks have no stored series_url; the autocomplete must key
    # the cached series_data lookup on url_name (a bare url_name passed to a
    # live `chapters`/`info` op used to silently fail to resolve).
    async def _run() -> None:
        calls: list[dict[str, Any]] = []

        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                calls.append({"type": type_, **fields})
                return {
                    "chapters": [
                        {"chapter": "Chapter 10"},
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                await BookmarkStore(pool).upsert_bookmark(
                    200, "toongod", "someone-stop-her-uncensored"
                )
                interaction = _interaction(
                    pool=pool,
                    crawler=Crawler(),
                    namespace=SimpleNamespace(manga="toongod:someone-stop-her-uncensored"),
                )
                autocomplete.clear_chapter_autocomplete_cache()

                choices = await autocomplete.user_bookmark_chapters(interaction, "")

                assert calls == [
                    {
                        "type": "series_data",
                        "website_key": "toongod",
                        "url_name": "someone-stop-her-uncensored",
                        "allow_live": False,
                    },
                ]
                assert [(choice.name, choice.value) for choice in choices] == [
                    ("0 - Chapter 10", 0)
                ]
            finally:
                autocomplete.clear_chapter_autocomplete_cache()
                await pool.close()

    asyncio.run(_run())
