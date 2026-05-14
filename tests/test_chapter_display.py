"""Chapter display markdown across component views."""

from __future__ import annotations

from collections.abc import Iterable

import discord

from manhwa_bot.cogs.bookmarks import _chapter_markdown
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
