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

    async def defer(self, **kwargs) -> None:
        self.deferred.append(kwargs)


class _FakeFollowup:
    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def send(self, **kwargs) -> None:
        self.sends.append(kwargs)


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
        assert interaction.followup.sends == []

        first_embed = interaction.original_edits[0]["embed"]
        assert first_embed.title == "Running /info"
        assert "Sent request to crawler" in (first_embed.description or "")

        progress_embed = interaction.original_edits[1]["embed"]
        assert progress_embed.title == "Running /info"
        assert "Retrying scrape: Temporary crawler timeout" in (progress_embed.description or "")

        final_edit = interaction.original_edits[-1]
        assert final_edit["embed"].title == "Test Series"
        assert "Num of Chapters:** 2" in (final_edit["embed"].description or "")
        assert isinstance(final_edit["view"], SubscribeView)

    asyncio.run(_run())


def test_info_edits_original_response_with_progress_history_on_crawler_error() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = CatalogCog(_FakeBot(_FailingCrawler()))
        cog._resolve_series_input = _resolved_input  # type: ignore[method-assign]
        cog._resolve_url_name = _url_name  # type: ignore[method-assign]

        await CatalogCog.info.callback(cog, interaction, "asura|test")  # type: ignore[misc]

        assert interaction.followup.sends == []
        final_embed = interaction.original_edits[-1]["embed"]
        assert final_embed.title == "Crawler Error"
        assert "[crawler_timeout] crawler took too long" in (final_embed.description or "")
        assert "Sent request to crawler" in (final_embed.description or "")
        assert "Retrying scrape: Temporary crawler timeout" in (final_embed.description or "")

    asyncio.run(_run())
