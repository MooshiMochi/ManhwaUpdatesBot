"""Tests for catalog command crawler progress responses."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from manhwa_bot.cogs.catalog import CatalogCog
from manhwa_bot.crawler.errors import CrawlerError
from manhwa_bot.ui.subscribe_view import SubscribeView


class _FakeResponse:
    def __init__(self) -> None:
        self.deferred: list[dict] = []
        self.sent_messages: list[dict] = []

    async def defer(self, **kwargs) -> None:
        self.deferred.append(kwargs)

    async def send_message(self, **kwargs) -> None:
        self.sent_messages.append(kwargs)


class _FakeFollowup:
    def __init__(self) -> None:
        self.sends: list[dict] = []
        self.messages: list[_FakeFollowupMessage] = []

    async def send(self, **kwargs) -> None:
        self.sends.append(kwargs)
        if kwargs.get("wait"):
            message = _FakeFollowupMessage(kwargs)
            self.messages.append(message)
            return message
        return None


class _FakeFollowupMessage:
    def __init__(self, initial: dict) -> None:
        self.initial = initial
        self.edits: list[dict] = []

    async def edit(self, **kwargs) -> None:
        self.edits.append(kwargs)


class _FakeInteraction:
    def __init__(self) -> None:
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()
        self.user = SimpleNamespace(id=123)
        self.original_edits: list[dict] = []

    async def edit_original_response(self, **kwargs) -> None:
        self.original_edits.append(kwargs)


class _FakeDB:
    async def fetchone(self, *_args, **_kwargs):
        return None


class _FakeWebsitesCache:
    async def get_or_set(self, *_args, **_kwargs):
        return [
            {
                "key": "asura",
                "name": "Asura",
                "base_url": "https://asurascans.example",
                "icon_url": "https://asurascans.example/icon.png",
            }
        ]


class _FakeBot:
    def __init__(self, crawler) -> None:
        self.crawler = crawler
        self.db = _FakeDB()
        self.user = None
        self.config = SimpleNamespace(supported_websites_cache=SimpleNamespace(ttl_seconds=60))
        self.websites_cache = _FakeWebsitesCache()


class _SuccessfulCrawler:
    async def request_with_progress(self, type_, *, on_progress, **kwargs):
        assert type_ == "info"
        assert kwargs["website_key"] == "asura"
        assert kwargs["url"] == "https://asurascans.example/series/test"
        assert kwargs["request_id"]
        await on_progress(
            SimpleNamespace(
                title="Retrying scrape",
                detail="Temporary crawler timeout",
                status="retrying",
            )
        )
        await on_progress(
            SimpleNamespace(
                title="Fetched series info",
                detail="Parsing metadata",
                status="running",
            )
        )
        return {
            "title": "Test Series",
            "url": "https://asurascans.example/series/test",
            "status": "Ongoing",
            "synopsis": "A test synopsis.",
            "chapter_count": 2,
            "latest_chapters": [
                {"name": "Chapter 2", "url": "https://asurascans.example/chapter/2"},
                {"name": "Chapter 1", "url": "https://asurascans.example/chapter/1"},
            ],
        }

    async def request(self, type_, **kwargs):
        assert type_ == "chapters"
        assert kwargs["website_key"] == "asura"
        assert kwargs["url"] == "https://asurascans.example/series/test"
        return {
            "chapters": [
                {"name": "Chapter 2", "url": "https://asurascans.example/chapter/2"},
                {"name": "Chapter 1", "url": "https://asurascans.example/chapter/1"},
            ]
        }


class _SuccessfulSearchCrawler:
    async def request_with_progress(self, type_, *, request_id, on_progress, **kwargs):
        assert type_ == "search"
        assert request_id
        assert kwargs == {"query": "solo", "limit": 20, "timeout": 15.0}
        await on_progress(
            SimpleNamespace(
                title="Searching sites",
                detail="Checking configured scanlators",
                status="running",
            )
        )
        return {
            "results": [
                {
                    "title": "Solo Leveling",
                    "series_url": "https://asurascans.example/series/solo-leveling",
                    "website_key": "asura",
                    "url_name": "solo-leveling",
                    "status": "Ongoing",
                }
            ],
            "failed_websites": [],
        }

    async def request(self, type_, **_kwargs):
        assert type_ == "supported_websites"
        return {
            "websites": [
                {
                    "key": "asura",
                    "name": "Asura",
                    "base_url": "https://asurascans.example",
                    "icon_url": "https://asurascans.example/icon.png",
                }
            ]
        }


class _FailingSearchCrawler:
    async def request_with_progress(self, type_, *, request_id, on_progress, **kwargs):
        assert type_ == "search"
        assert request_id
        assert kwargs == {"query": "solo", "limit": 20, "timeout": 15.0}
        await on_progress(
            SimpleNamespace(
                title="Searching sites",
                detail="Checking configured scanlators",
                status="running",
            )
        )
        raise CrawlerError(
            code="search_failed",
            message="search failed",
            request_id=request_id,
        )


class _FailingCrawler:
    async def request_with_progress(self, type_, *, request_id, on_progress, **kwargs):
        assert type_ == "info"
        await on_progress(
            SimpleNamespace(
                title="Retrying scrape",
                detail="Temporary crawler timeout",
                status="retrying",
            )
        )
        raise CrawlerError(
            code="crawler_timeout",
            message="crawler took too long",
            request_id=request_id,
        )

    async def request(self, type_, **_kwargs):
        assert type_ == "chapters"
        return {"chapters": [{"name": "Chapter 1"}]}


class _SlowInfoCrawler:
    async def request_with_progress(self, type_, *, on_progress, **_kwargs):
        assert type_ == "info"
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            await on_progress(
                SimpleNamespace(
                    title="Late info progress",
                    detail="Should not overwrite final error",
                    status="running",
                )
            )
            raise
        await on_progress(
            SimpleNamespace(
                title="Late info progress",
                detail="Should not overwrite final error",
                status="running",
            )
        )
        return {"title": "Too Late"}

    async def request(self, type_, **_kwargs):
        raise AssertionError(f"/info should not request cached {type_}")


class _InfoFoundChaptersNotFoundCrawler:
    async def request_with_progress(self, type_, *, request_id, on_progress, **kwargs):
        assert type_ == "info"
        assert request_id
        assert kwargs["website_key"] == "asura"
        assert kwargs["url"] == "https://asurascans.example/series/test"
        await on_progress(
            SimpleNamespace(
                title="Fetched series info",
                detail="Parsing metadata",
                status="running",
            )
        )
        return {
            "title": "Test Series",
            "url": "https://asurascans.example/series/test",
            "status": "Ongoing",
            "chapter_count": 55,
            "latest_chapters": [
                {"name": "Chapter 55", "url": "https://asurascans.example/chapter/55"},
                {"name": "Chapter 1", "url": "https://asurascans.example/chapter/1"},
            ],
        }

    async def request(self, type_, **_kwargs):
        assert type_ == "chapters"
        raise CrawlerError(
            code="not_found",
            message="series not found in cache",
            request_id="chapters-request",
        )


class _InfoOnlyCrawler:
    async def request_with_progress(self, type_, *, request_id, on_progress, **kwargs):
        assert type_ == "info"
        assert request_id
        await on_progress(
            SimpleNamespace(
                title="Fetched series info",
                detail="Parsing metadata",
                status="running",
            )
        )
        return {
            "title": "Test Series",
            "url": "https://asurascans.example/series/test",
            "status": "Ongoing",
            "chapter_count": 1,
            "latest_chapters": [
                {"name": "Chapter 1", "url": "https://asurascans.example/chapter/1"},
            ],
        }

    async def request(self, type_, **_kwargs):
        if type_ == "supported_websites":
            return {"websites": []}
        raise AssertionError(f"/info should not request cached {type_}")


async def _resolved_input(_series: str) -> tuple[str, str]:
    return "asura", "https://asurascans.example/series/test"


async def _url_name(_website_key: str, _identifier: str) -> str:
    return "test"


def test_info_edits_original_response_with_progress_then_final_embed() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = CatalogCog(_FakeBot(_SuccessfulCrawler()))
        cog._resolve_series_input = _resolved_input  # type: ignore[method-assign]
        cog._resolve_url_name = _url_name  # type: ignore[method-assign]

        await CatalogCog.info.callback(cog, interaction, "asura|test")  # type: ignore[misc]

        assert interaction.response.deferred == [{"thinking": True, "ephemeral": True}]
        assert len(interaction.followup.sends) == 1
        assert interaction.followup.sends[0]["ephemeral"] is True
        assert interaction.followup.sends[0]["wait"] is True

        progress_message = interaction.followup.messages[0]
        first_embed = progress_message.initial["embed"]
        assert first_embed.title == "Running /info"
        assert "Sent request to crawler" in (first_embed.description or "")

        progress_embed = progress_message.edits[0]["embed"]
        assert progress_embed.title == "Running /info"
        assert "Retrying scrape: Temporary crawler timeout" in (progress_embed.description or "")

        final_edit = progress_message.edits[-1]
        assert final_edit["embed"].title == "Test Series"
        assert "Num of Chapters:** 2" in (final_edit["embed"].description or "")
        assert isinstance(final_edit["view"], SubscribeView)

    asyncio.run(_run())


def test_search_edits_original_response_with_progress_then_final_result_embed() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = CatalogCog(_FakeBot(_SuccessfulSearchCrawler()))

        await CatalogCog.search.callback(cog, interaction, "solo")  # type: ignore[misc]

        assert len(interaction.response.sent_messages) == 1
        assert interaction.response.sent_messages[0]["ephemeral"] is True
        assert interaction.followup.sends == []

        first_embed = interaction.response.sent_messages[0]["embed"]
        assert first_embed.title == "Running /search"
        assert "Sent request to crawler" in (first_embed.description or "")

        progress_embed = interaction.original_edits[0]["embed"]
        assert progress_embed.title == "Running /search"
        assert "Searching sites: Checking configured scanlators" in (
            progress_embed.description or ""
        )

        final_edit = interaction.original_edits[-1]
        assert final_edit["embed"].title == "Solo Leveling"
        assert final_edit["view"] is not None

    asyncio.run(_run())


def test_search_edits_original_response_with_progress_history_on_crawler_error() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = CatalogCog(_FakeBot(_FailingSearchCrawler()))

        await CatalogCog.search.callback(cog, interaction, "solo")  # type: ignore[misc]

        assert interaction.followup.sends == []
        final_embed = interaction.original_edits[-1]["embed"]
        assert final_embed.title == "Crawler Error"
        assert "[search_failed] search failed" in (final_embed.description or "")
        assert "Sent request to crawler" in (final_embed.description or "")
        assert "Searching sites: Checking configured scanlators" in (final_embed.description or "")

    asyncio.run(_run())


def test_info_edits_original_response_with_progress_history_on_crawler_error() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = CatalogCog(_FakeBot(_FailingCrawler()))
        cog._resolve_series_input = _resolved_input  # type: ignore[method-assign]
        cog._resolve_url_name = _url_name  # type: ignore[method-assign]

        await CatalogCog.info.callback(cog, interaction, "asura|test")  # type: ignore[misc]

        progress_message = interaction.followup.messages[0]
        final_embed = progress_message.edits[-1]["embed"]
        assert final_embed.title == "Crawler Error"
        assert "[crawler_timeout] crawler took too long" in (final_embed.description or "")
        assert "Sent request to crawler" in (final_embed.description or "")
        assert "Retrying scrape: Temporary crawler timeout" in (final_embed.description or "")

    asyncio.run(_run())


def test_info_late_progress_does_not_overwrite_final_embed() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = CatalogCog(_FakeBot(_SlowInfoCrawler()))
        cog._resolve_series_input = _resolved_input  # type: ignore[method-assign]
        cog._resolve_url_name = _url_name  # type: ignore[method-assign]

        await CatalogCog.info.callback(cog, interaction, "asura|test")  # type: ignore[misc]
        await asyncio.sleep(0.1)

        progress_message = interaction.followup.messages[0]
        assert progress_message.edits[-1]["embed"].title == "Too Late"
        assert "Late info progress" not in (progress_message.edits[-1]["embed"].description or "")

    asyncio.run(_run())


def test_info_uses_live_info_when_cached_chapters_are_not_found() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = CatalogCog(_FakeBot(_InfoFoundChaptersNotFoundCrawler()))
        cog._resolve_series_input = _resolved_input  # type: ignore[method-assign]
        cog._resolve_url_name = _url_name  # type: ignore[method-assign]

        await CatalogCog.info.callback(cog, interaction, "asura|test")  # type: ignore[misc]

        progress_message = interaction.followup.messages[0]
        assert progress_message.initial["embed"].title == "Running /info"
        final_edit = progress_message.edits[-1]
        assert final_edit["embed"].title == "Test Series"
        assert "Num of Chapters:** 55" in (final_edit["embed"].description or "")
        assert "Latest Chapter:** Chapter 55" in (final_edit["embed"].description or "")
        assert isinstance(final_edit["view"], SubscribeView)

    asyncio.run(_run())


def test_info_does_not_request_cached_chapters_after_live_info() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = CatalogCog(_FakeBot(_InfoOnlyCrawler()))
        cog._resolve_series_input = _resolved_input  # type: ignore[method-assign]
        cog._resolve_url_name = _url_name  # type: ignore[method-assign]

        await CatalogCog.info.callback(cog, interaction, "asura|test")  # type: ignore[misc]

        progress_message = interaction.followup.messages[0]
        assert progress_message.initial["embed"].title == "Running /info"
        assert progress_message.edits[-1]["embed"].title == "Test Series"
        assert "Num of Chapters:** 1" in (progress_message.edits[-1]["embed"].description or "")

    asyncio.run(_run())
