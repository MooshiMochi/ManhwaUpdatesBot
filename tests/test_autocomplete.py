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


def test_tracked_manga_autocomplete_filters_before_the_legacy_row_cap() -> None:
    """A matching title after the first 100 alphabetical rows remains selectable."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                store = TrackedStore(pool)
                for index in range(101):
                    url_name = f"a-series-{index:03d}"
                    await store.upsert_series(
                        "comix",
                        url_name,
                        f"https://example.test/{url_name}",
                        f"A Series {index:03d}",
                    )
                    await store.add_to_guild(100, "comix", url_name)
                await store.upsert_series(
                    "comix",
                    "dukedoms-legendary-prodigy",
                    "https://example.test/dukedoms-legendary-prodigy",
                    "Dukedom's Legendary Prodigy",
                )
                await store.add_to_guild(100, "comix", "dukedoms-legendary-prodigy")

                choices = await autocomplete.tracked_manga_in_guild(
                    _interaction(pool=pool), "dukedom"
                )

                assert [(choice.name, choice.value) for choice in choices] == [
                    ("(comix) Dukedom's Legendary Prodigy", "comix:dukedoms-legendary-prodigy")
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


def test_user_subscribed_manga_with_all_prepends_all_choice() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                await SubscriptionStore(pool).subscribe(200, 100, "asura", "solo-leveling")

                choices = await autocomplete.user_subscribed_manga_with_all(
                    _interaction(pool=pool), ""
                )
                assert choices[0].value == "*"
                assert "default ping role" in choices[0].name
                assert [(c.name, c.value) for c in choices[1:]] == [
                    ("(asura) solo-leveling", "asura:solo-leveling")
                ]

                # A non-matching query hides the All option.
                filtered = await autocomplete.user_subscribed_manga_with_all(
                    _interaction(pool=pool), "solo"
                )
                assert all(choice.value != "*" for choice in filtered)
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
                # Newest chapter first (descending) so the latest sits on top.
                # Values are strings — the chapter option is a string option.
                assert [(choice.name, choice.value) for choice in choices] == [
                    ("1 - Chapter 2", "1"),
                    ("0 - Chapter 1", "0"),
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
                    ("1 - Side Story 1", "1")
                ]
            finally:
                autocomplete.clear_chapter_autocomplete_cache()
                await pool.close()

    asyncio.run(_run())


def test_user_bookmark_chapters_prompts_when_no_series_selected() -> None:
    # Before a manga is picked the field instantly shows a single hint choice,
    # without touching the DB or crawler.
    async def _run() -> None:
        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                raise AssertionError("must not query the crawler without a selected series")

        autocomplete.clear_chapter_autocomplete_cache()
        choices = await autocomplete.user_bookmark_chapters(
            _interaction(crawler=Crawler(), namespace=SimpleNamespace()),
            "",
        )

        assert [(choice.name, choice.value) for choice in choices] == [
            ("You must select a series first", autocomplete.NO_SERIES_SELECTED_VALUE)
        ]

    asyncio.run(_run())


def test_user_bookmark_chapters_returns_latest_first_descending() -> None:
    # No chapter input yet → newest chapters at the top (descending index).
    async def _run() -> None:
        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                del type_, fields
                return {
                    "chapters": [
                        {"chapter": "Chapter 1"},
                        {"chapter": "Chapter 2"},
                        {"chapter": "Chapter 3"},
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
                        namespace=SimpleNamespace(manga="asura:solo-leveling"),
                    ),
                    "",
                )

                assert [(choice.name, choice.value) for choice in choices] == [
                    ("2 - Chapter 3", "2"),
                    ("1 - Chapter 2", "1"),
                    ("0 - Chapter 1", "0"),
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
                assert [(choice.name, choice.value) for choice in second] == [
                    ("1 - Chapter 2", "1")
                ]
                assert len(calls) == 1
            finally:
                autocomplete.clear_chapter_autocomplete_cache()
                await pool.close()

    asyncio.run(_run())


def test_user_bookmark_chapters_does_not_cache_empty_result_long(monkeypatch) -> None:
    # A transient miss (crawler busy during an update check) must not blackhole
    # the field: once the crawler recovers the next keystroke should re-fetch
    # instead of returning a stale empty list cached for the full TTL.
    async def _run() -> None:
        state = {"fail": True}

        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                if state["fail"]:
                    raise RuntimeError("crawler busy")
                return {"chapters": [{"chapter": "Chapter 1"}]}

        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                autocomplete.clear_chapter_autocomplete_cache()
                monkeypatch.setattr(
                    autocomplete,
                    "CHAPTER_AUTOCOMPLETE_EMPTY_CACHE_TTL_SECONDS",
                    0.0,
                    raising=False,
                )
                await BookmarkStore(pool).upsert_bookmark(200, "asura", "solo-leveling")
                interaction = _interaction(
                    pool=pool,
                    crawler=Crawler(),
                    namespace=SimpleNamespace(manga="asura:solo-leveling"),
                )

                first = await autocomplete.user_bookmark_chapters(interaction, "")
                assert first == []

                state["fail"] = False
                await asyncio.sleep(0)
                second = await autocomplete.user_bookmark_chapters(interaction, "")
                assert [(c.name, c.value) for c in second] == [("0 - Chapter 1", "0")]
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
                    ("0 - Chapter 10", "0")
                ]
            finally:
                autocomplete.clear_chapter_autocomplete_cache()
                await pool.close()

    asyncio.run(_run())


def test_series_choice_value_short_is_unchanged() -> None:
    # Short ids keep the historical "website_key:url_name" form (backward compat).
    value = autocomplete.series_choice_value("asura", "solo-leveling")
    assert value == "asura:solo-leveling"
    assert autocomplete.resolve_series_value(value, []) == ("asura", "solo-leveling")


def test_series_choice_value_long_slug_round_trips_via_token() -> None:
    # A "website_key:url_name" longer than Discord's 100-char choice-value cap
    # must round-trip through a compact token resolved against the user's rows.
    long_url = "reincarnation-colosseum-" + "x" * 110
    raw = f"comix:{long_url}"
    assert len(raw) > autocomplete.SERIES_VALUE_MAX_LEN

    value = autocomplete.series_choice_value("comix", long_url)
    assert value != raw
    assert value.startswith("#")
    assert len(value) <= autocomplete.SERIES_VALUE_MAX_LEN

    # Resolves only against the invoker's accessible rows.
    assert autocomplete.resolve_series_value(value, [("comix", long_url)]) == ("comix", long_url)
    # A token for a series the user doesn't have resolves to nothing.
    assert autocomplete.resolve_series_value(value, [("comix", "something-else")]) is None


def test_user_bookmarks_tokenizes_long_slug_and_resolves_back() -> None:
    # Full path: the manga autocomplete emits a <=100-char token for a long-slug
    # bookmark, and command-side resolution against the user's bookmarks recovers
    # the exact (website_key, url_name).
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                long_url = "kurasu-mushoku-no-eiyuu-tan-" + "y" * 110
                await BookmarkStore(pool).upsert_bookmark(200, "manganato", long_url)
                await TrackedStore(pool).upsert_series(
                    "manganato", long_url, "https://example.test/long", "Long Title Series"
                )

                choices = await autocomplete.user_bookmarks(_interaction(pool=pool), "Long")
                assert len(choices) == 1
                value = choices[0].value
                assert len(value) <= autocomplete.SERIES_VALUE_MAX_LEN
                assert value.startswith("#")

                rows = await BookmarkStore(pool).list_user_bookmarks(200, limit=2000)
                pairs = [(row.website_key, row.url_name) for row in rows]
                assert autocomplete.resolve_series_value(value, pairs) == ("manganato", long_url)
            finally:
                await pool.close()

    asyncio.run(_run())


def test_user_bookmark_chapters_resolves_tokenized_series_value() -> None:
    # The chapter autocomplete must resolve a #-token sibling manga value (long
    # slug) back to its series before reading the crawler's stored chapters.
    async def _run() -> None:
        long_url = "reincarnation-colosseum-" + "z" * 110
        token = autocomplete.series_choice_value("comix", long_url)
        assert token.startswith("#")

        class Crawler:
            async def request(self, type_: str, **fields: Any) -> dict[str, Any]:
                assert fields["url_name"] == long_url
                return {"chapters": [{"chapter": "Chapter 1"}, {"chapter": "Chapter 2"}]}

        with tempfile.TemporaryDirectory() as tmp:
            pool = await _make_pool(tmp)
            try:
                autocomplete.clear_chapter_autocomplete_cache()
                await BookmarkStore(pool).upsert_bookmark(200, "comix", long_url)

                choices = await autocomplete.user_bookmark_chapters(
                    _interaction(
                        pool=pool,
                        crawler=Crawler(),
                        namespace=SimpleNamespace(manga=token),
                    ),
                    "",
                )

                assert [(c.name, c.value) for c in choices] == [
                    ("1 - Chapter 2", "1"),
                    ("0 - Chapter 1", "0"),
                ]
            finally:
                autocomplete.clear_chapter_autocomplete_cache()
                await pool.close()

    asyncio.run(_run())
