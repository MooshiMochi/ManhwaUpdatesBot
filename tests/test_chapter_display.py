"""Chapter display markdown across component views."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from types import SimpleNamespace

import discord

from manhwa_bot.cogs.bookmarks import _chapter_markdown
from manhwa_bot.cogs.catalog import CatalogCog
from manhwa_bot.ui import emojis
from manhwa_bot.ui.components.chapter_list import build_chapter_list_views
from manhwa_bot.ui.components.notifications import build_chapter_update_view
from manhwa_bot.ui.components.series_info import build_info_view


def _text_content(item: discord.ui.Item[object]) -> Iterable[str]:
    content = getattr(item, "content", None)
    if isinstance(content, str):
        yield content
    for child in getattr(item, "children", ()):
        yield from _text_content(child)


def _view_text(view: discord.ui.LayoutView) -> str:
    return "\n".join(text for child in view.children for text in _text_content(child))


def test_chapter_list_links_premium_chapters_with_lock_only_when_premium() -> None:
    view = build_chapter_list_views(
        [
            {
                "name": "Chapter 2",
                "url": "https://example.test/chapter-2",
                "is_premium": True,
            },
            {
                "name": "Chapter 1",
                "url": "https://example.test/chapter-1",
                "is_premium": False,
            },
        ],
        manga_title="Series",
        manga_url="https://example.test/series",
        bot=None,
    )[0]

    text = _view_text(view)

    assert f"[{emojis.LOCK} Chapter 2](https://example.test/chapter-2)" in text
    assert "[Chapter 1](https://example.test/chapter-1)" in text
    assert f"{emojis.LOCK} Chapter 1" not in text


def test_info_view_links_latest_and_first_chapters_with_premium_lock() -> None:
    view = build_info_view(
        {
            "title": "Series",
            "website_key": "site",
            "chapters": [
                {
                    "name": "Chapter 9",
                    "url": "https://example.test/chapter-9",
                    "is_premium": True,
                },
                {
                    "name": "Chapter 1",
                    "url": "https://example.test/chapter-1",
                    "is_premium": False,
                },
            ],
        }
    )

    text = _view_text(view)

    assert f"**Latest Chapter:** [{emojis.LOCK} Chapter 9](https://example.test/chapter-9)" in text
    assert "**First Chapter:** [Chapter 1](https://example.test/chapter-1)" in text


def test_update_notification_links_premium_chapter_with_lock_not_suffix() -> None:
    view = build_chapter_update_view(
        {
            "series_title": "Series",
            "series_url": "https://example.test/series",
            "chapter": {
                "name": "Chapter 9",
                "url": "https://example.test/chapter-9",
                "is_premium": True,
            },
        }
    )

    text = _view_text(view)

    assert f"**New chapter:** [{emojis.LOCK} Chapter 9](https://example.test/chapter-9)" in text
    assert "(premium)" not in text


def test_bookmark_chapter_markdown_links_premium_chapters_with_lock() -> None:
    assert (
        _chapter_markdown(
            {
                "name": "Chapter 9",
                "url": "https://example.test/chapter-9",
                "is_premium": True,
            },
            0,
        )
        == f"[{emojis.LOCK} Chapter 9](https://example.test/chapter-9)"
    )


def test_info_command_renders_dedicated_chapter_urls_when_info_payload_lacks_urls() -> None:
    class FakeResponse:
        async def defer(self, *, thinking: bool, ephemeral: bool) -> None:
            self.deferred = (thinking, ephemeral)

    class FakeMessage:
        def __init__(self) -> None:
            self.view: discord.ui.LayoutView | None = None

        async def edit(self, *, view: discord.ui.LayoutView) -> None:
            self.view = view

    class FakeFollowup:
        def __init__(self, message: FakeMessage) -> None:
            self._message = message

        async def send(
            self,
            *,
            view: discord.ui.LayoutView,
            ephemeral: bool,
            wait: bool = False,
        ) -> FakeMessage | None:
            del ephemeral
            self._message.view = view
            return self._message if wait else None

    class FakeCrawler:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def request_with_progress(self, type_: str, **kwargs) -> dict:
            del kwargs
            self.calls.append(type_)
            assert type_ == "info"
            return {
                "title": "Series",
                "url": "https://example.test/series",
                "website_key": "site",
                "chapters": [{"name": "Chapter 9", "is_premium": True}],
            }

        async def request(self, type_: str, **kwargs) -> dict:
            del kwargs
            self.calls.append(type_)
            if type_ == "chapters":
                return {
                    "chapters": [
                        {
                            "name": "Chapter 9",
                            "url": "https://example.test/chapter-9",
                            "is_premium": True,
                        }
                    ]
                }
            if type_ == "supported_websites":
                return {"websites": [{"key": "site", "name": "Site"}]}
            raise AssertionError(type_)

    class FakeCache:
        async def get_or_set(self, key, loader, ttl):
            del key, ttl
            return await loader()

    async def _run() -> None:
        message = FakeMessage()
        crawler = FakeCrawler()
        bot = SimpleNamespace(
            db=None,
            crawler=crawler,
            websites_cache=FakeCache(),
            config=SimpleNamespace(supported_websites_cache=SimpleNamespace(ttl_seconds=60)),
        )
        interaction = SimpleNamespace(
            response=FakeResponse(),
            followup=FakeFollowup(message),
            user=SimpleNamespace(id=1),
        )
        cog = CatalogCog(bot)  # type: ignore[arg-type]

        await CatalogCog.info.callback(
            cog,
            interaction,  # type: ignore[arg-type]
            "site|https://example.test/series",
        )

        assert message.view is not None
        text = _view_text(message.view)
        assert f"**Latest Chapter:** [{emojis.LOCK} Chapter 9](https://example.test/chapter-9)" in text
        assert crawler.calls == ["info", "chapters", "supported_websites"]

    asyncio.run(_run())
