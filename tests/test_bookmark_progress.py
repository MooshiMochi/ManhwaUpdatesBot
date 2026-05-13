"""Tests for bookmark command crawler progress responses."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from manhwa_bot.cogs import bookmarks as bookmarks_mod
from manhwa_bot.cogs.bookmarks import BookmarksCog


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
        self.guild_id = None
        self.original_edits: list[dict] = []

    async def edit_original_response(self, **kwargs) -> None:
        self.original_edits.append(kwargs)


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


class _RawBookmarkCrawler:
    def __init__(self) -> None:
        self.progress_request_seen = False

    async def request_with_progress(self, type_, *, request_id, on_progress, **kwargs):
        assert type_ == "info"
        assert request_id
        assert kwargs == {
            "website_key": "asura",
            "url": "https://asurascans.example/series/solo-leveling",
        }
        self.progress_request_seen = True
        await on_progress(
            SimpleNamespace(
                title="Fetching series",
                detail="Resolving bookmark URL",
                status="running",
            )
        )
        return {
            "title": "Solo Leveling",
            "series_url": "https://asurascans.example/series/solo-leveling",
            "url_name": "solo-leveling",
        }

    async def request(self, type_, **kwargs):
        assert type_ in {"chapters", "supported_websites"}
        if type_ == "supported_websites":
            return {"websites": []}
        assert kwargs == {
            "website_key": "asura",
            "url": "https://asurascans.example/series/solo-leveling",
        }
        return {
            "title": "Solo Leveling",
            "status": "Ongoing",
            "chapters": [
                {"name": "Chapter 1", "url": "https://asurascans.example/chapter/1"},
                {"name": "Chapter 2", "url": "https://asurascans.example/chapter/2"},
            ],
        }


class _FakeBot:
    def __init__(self, crawler) -> None:
        self.crawler = crawler
        self.db = object()
        self.user = None
        self.config = SimpleNamespace(supported_websites_cache=SimpleNamespace(ttl_seconds=60))
        self.websites_cache = _FakeWebsitesCache()


class _FakeBookmarks:
    def __init__(self) -> None:
        self.upserts: list[tuple] = []

    async def upsert_bookmark(self, *args, **kwargs) -> None:
        self.upserts.append((args, kwargs))


class _FakeTracked:
    async def find(self, *_args, **_kwargs):
        return None


def test_bookmark_add_raw_url_uses_progress_for_live_info(monkeypatch) -> None:
    async def _detect_website_key(_bot, _url: str) -> str:
        return "asura"

    async def _run() -> None:
        monkeypatch.setattr(bookmarks_mod, "detect_website_key", _detect_website_key)
        interaction = _FakeInteraction()
        crawler = _RawBookmarkCrawler()
        cog = BookmarksCog(_FakeBot(crawler))
        bookmarks = _FakeBookmarks()
        cog._bookmarks = bookmarks  # type: ignore[method-assign]
        cog._tracked = _FakeTracked()  # type: ignore[method-assign]

        await BookmarksCog.bookmark_new.callback(  # type: ignore[attr-defined]
            cog,
            interaction,
            "https://asurascans.example/series/solo-leveling",
        )

        assert crawler.progress_request_seen
        assert interaction.response.deferred == [{"thinking": True, "ephemeral": True}]
        assert interaction.followup.sends == []

        first_embed = interaction.original_edits[0]["embed"]
        assert first_embed.title == "Running /bookmark new"
        assert "Sent request to crawler" in (first_embed.description or "")

        progress_embed = interaction.original_edits[1]["embed"]
        assert progress_embed.title == "Running /bookmark new"
        assert "Fetching series: Resolving bookmark URL" in (progress_embed.description or "")

        final_edit = interaction.original_edits[-1]
        assert final_edit["content"] == "Successfully bookmarked Solo Leveling"
        assert final_edit["embed"].title == "Bookmark: Solo Leveling"
        assert bookmarks.upserts

    asyncio.run(_run())
