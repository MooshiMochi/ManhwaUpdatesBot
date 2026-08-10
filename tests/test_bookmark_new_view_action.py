"""Regression coverage for the `/bookmark new` View Bookmark action."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from manhwa_bot.cogs import bookmarks as bookmarks_module
from manhwa_bot.cogs.bookmarks import BookmarksCog
from manhwa_bot.crawler.chapter import Chapter
from manhwa_bot.db.bookmarks import Bookmark


def test_view_bookmark_action_opens_the_persisted_folder(monkeypatch) -> None:
    persisted = Bookmark(
        user_id=42,
        website_key="site",
        url_name="finished-series",
        folder="Finished",
        last_read_chapter="Chapter 1",
        last_read_index=0,
        created_at="2026-08-10T00:00:00",
        updated_at="2026-08-10T00:00:00",
    )
    chapters = [
        Chapter("Chapter 1", "https://site.test/chapter/1", 0, False),
        Chapter("Chapter 2", "https://site.test/chapter/2", 1, False),
    ]
    crawler = SimpleNamespace(
        request_with_progress=AsyncMock(
            return_value={
                "title": "Finished Series",
                "status": "Ongoing",
                "cover_url": "https://site.test/cover.jpg",
            }
        )
    )
    bot = SimpleNamespace(db=SimpleNamespace(), crawler=crawler)
    cog = BookmarksCog(bot)  # type: ignore[arg-type]
    cog._bookmarks = SimpleNamespace(
        upsert_bookmark=AsyncMock(),
        get_bookmark=AsyncMock(return_value=persisted),
    )
    cog._tracked = SimpleNamespace(find=AsyncMock(return_value=None))
    cog._subs = SimpleNamespace()
    cog._guild_settings = SimpleNamespace()
    cog._resolve_series = AsyncMock(  # type: ignore[method-assign]
        return_value=bookmarks_module._ResolvedSeries(
            website_key="site",
            url_name="finished-series",
            series_url="https://site.test/series/finished-series",
            info={},
        )
    )
    cog._fetch_chapters_with_fallback = AsyncMock(  # type: ignore[method-assign]
        return_value=chapters
    )
    cog._site_metadata = AsyncMock(  # type: ignore[method-assign]
        return_value={"base_url": "https://site.test"}
    )

    browser_kwargs: dict[str, object] = {}

    class BrowserSpy:
        def __init__(self, _bookmarks, **kwargs) -> None:
            browser_kwargs.update(kwargs)

        async def initial_render(self) -> None:
            return None

    detail_builder = Mock(return_value=object())
    monkeypatch.setattr(bookmarks_module, "BookmarkBrowserView", BrowserSpy)
    monkeypatch.setattr(bookmarks_module, "build_bookmark_detail_view", detail_builder)

    interaction = SimpleNamespace(
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        user=SimpleNamespace(id=42),
        guild_id=None,
    )

    async def run() -> None:
        await BookmarksCog.bookmark_new.callback(
            cog,
            interaction,
            "site:finished-series",
            "Finished",
        )
        action_row = detail_builder.call_args.kwargs["extra_action_row"]
        button = next(
            child
            for child in action_row.children
            if isinstance(child, discord.ui.Button) and child.label == "View Bookmark"
        )
        button_interaction = SimpleNamespace(
            response=SimpleNamespace(send_message=AsyncMock())
        )
        await button.callback(button_interaction)

    asyncio.run(run())

    assert browser_kwargs["current_folder"] == "Finished"
