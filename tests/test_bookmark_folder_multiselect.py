from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from manhwa_bot.db.bookmarks import Bookmark
from manhwa_bot.ui.components.bookmark import BOOKMARK_FOLDERS, BookmarkBrowserView


def _bookmark(folder: str, index: int) -> Bookmark:
    return Bookmark(
        user_id=1,
        website_key="site",
        url_name=f"series-{index}",
        folder=folder,
        last_read_chapter=None,
        last_read_index=None,
        created_at="",
        updated_at=str(index),
    )


def _browser(*, current_folder: str | None = None) -> BookmarkBrowserView:
    bookmarks = [_bookmark(folder, index) for index, folder in enumerate(BOOKMARK_FOLDERS)]
    return BookmarkBrowserView(
        bookmarks,
        store=SimpleNamespace(),
        tracked=SimpleNamespace(),
        subscriptions=SimpleNamespace(),
        guild_settings=SimpleNamespace(),
        crawler=SimpleNamespace(),
        invoker_id=1,
        current_folder=current_folder,
    )


def _browse_select(browser: BookmarkBrowserView) -> discord.ui.Select:
    row = browser._build_folder_filter_row()
    return next(item for item in row.children if isinstance(item, discord.ui.Select))


def test_folder_multiselect_defaults_to_reading_and_subscribed() -> None:
    browser = _browser()

    select = _browse_select(browser)

    assert browser._selected_folders == {"Reading", "Subscribed"}
    assert [bookmark.folder for bookmark in browser._filtered] == [
        "Reading",
        "Subscribed",
    ]
    assert select.min_values == 0
    assert select.max_values == len(BOOKMARK_FOLDERS)
    assert [option.value for option in select.options] == list(BOOKMARK_FOLDERS)
    assert [option.value for option in select.options if option.default] == [
        "Reading",
        "Subscribed",
    ]


def test_slash_folder_argument_starts_with_single_included_folder() -> None:
    browser = _browser(current_folder="Planned")

    select = _browse_select(browser)

    assert browser._selected_folders == {"Planned"}
    assert [bookmark.folder for bookmark in browser._filtered] == ["Planned"]
    assert [option.value for option in select.options if option.default] == ["Planned"]


def test_folder_multiselect_includes_selected_and_excludes_unselected() -> None:
    async def _run() -> None:
        browser = _browser()
        browser._index = 4
        browser._rebuild_and_edit = AsyncMock()  # type: ignore[method-assign]
        interaction = SimpleNamespace(data={"values": ["Reading", "Planned"]})

        await browser._on_filter_change(interaction)  # type: ignore[arg-type]

        assert browser._selected_folders == {"Reading", "Planned"}
        assert [bookmark.folder for bookmark in browser._filtered] == ["Reading", "Planned"]
        assert browser._index == 0
        browser._rebuild_and_edit.assert_awaited_once_with(interaction)

    asyncio.run(_run())


def test_folder_multiselect_empty_selection_shows_no_bookmarks() -> None:
    async def _run() -> None:
        browser = _browser()
        browser._rebuild_and_edit = AsyncMock()  # type: ignore[method-assign]
        interaction = SimpleNamespace(data={"values": []})

        await browser._on_filter_change(interaction)  # type: ignore[arg-type]

        assert browser._selected_folders == set()
        assert browser._filtered == []

    asyncio.run(_run())
