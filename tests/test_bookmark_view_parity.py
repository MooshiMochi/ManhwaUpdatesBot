from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord

from manhwa_bot.cogs.bookmarks import _BookmarkSuccessView
from manhwa_bot.db.bookmarks import Bookmark
from manhwa_bot.ui.bookmark_view import BookmarkView


class _Store:
    async def update_last_read(self, *args, **kwargs) -> None:
        pass


class _Tracked:
    async def find(self, website_key: str, url_name: str) -> SimpleNamespace:
        return SimpleNamespace(
            title="Solo Leveling",
            series_url="https://example.test/solo-leveling",
            cover_url="https://example.test/cover.jpg",
        )

    async def list_guilds_tracking(self, website_key: str, url_name: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(guild_id=100)]


class _Untracked(_Tracked):
    async def list_guilds_tracking(self, website_key: str, url_name: str) -> list[SimpleNamespace]:
        return []


class _Crawler:
    async def request(self, *args, **kwargs) -> dict:
        return {"chapters": []}


def _bookmark() -> Bookmark:
    return Bookmark(
        user_id=200,
        website_key="asura",
        url_name="solo-leveling",
        folder="Reading",
        last_read_chapter="Chapter 1",
        last_read_index=0,
        created_at="2026-01-01",
        updated_at="2026-01-02",
    )


def _view() -> BookmarkView:
    return BookmarkView(
        [_bookmark()],
        store=_Store(),
        tracked=_Tracked(),
        crawler=_Crawler(),
        invoker_id=200,
    )


def _guild_view(tracked: object) -> BookmarkView:
    return BookmarkView(
        [_bookmark()],
        store=_Store(),
        tracked=tracked,  # type: ignore[arg-type]
        crawler=_Crawler(),
        invoker_id=200,
        guild_id=100,
    )


def test_bookmark_visual_embed_uses_v1_title() -> None:
    view = _view()

    embed = asyncio.run(view.initial_embed())

    assert embed.title == "Bookmark: Solo Leveling"


def test_bookmark_visual_embed_warns_when_not_tracked_in_guild() -> None:
    view = _guild_view(_Untracked())

    embed = asyncio.run(view.initial_embed())

    fields = {field.name: field.value for field in embed.fields}
    assert "⚠️ Not tracked" in fields
    assert "will not be notified" in fields["⚠️ Not tracked"]


def test_bookmark_visual_embed_omits_warning_when_tracked_in_guild() -> None:
    view = _guild_view(_Tracked())

    embed = asyncio.run(view.initial_embed())

    assert "⚠️ Not tracked" not in {field.name for field in embed.fields}


def test_bookmark_visual_components_match_v1_shape() -> None:
    view = _view()
    asyncio.run(view.initial_embed())

    buttons = [child for child in view.children if isinstance(child, discord.ui.Button)]
    selects = [child for child in view.children if isinstance(child, discord.ui.Select)]

    assert [(button.label, button.style, button.row) for button in buttons] == [
        ("⏮️", discord.ButtonStyle.blurple, 0),
        ("⬅️", discord.ButtonStyle.blurple, 0),
        ("⏹️", discord.ButtonStyle.red, 0),
        ("➡️", discord.ButtonStyle.blurple, 0),
        ("⏭️", discord.ButtonStyle.blurple, 0),
        ("\u200b", discord.ButtonStyle.grey, 3),
        ("Update", discord.ButtonStyle.blurple, 3),
        ("Search", discord.ButtonStyle.blurple, 3),
        ("Delete", discord.ButtonStyle.red, 3),
        ("\u200b", discord.ButtonStyle.grey, 3),
    ]
    assert [select.placeholder for select in selects] == [
        "Select view type.",
        "Select folder.",
    ]


def test_bookmark_success_view_has_view_bookmark_button() -> None:
    view = _BookmarkSuccessView(
        bookmark=_bookmark(),
        store=_Store(),
        tracked=_Tracked(),  # type: ignore[arg-type]
        crawler=_Crawler(),
        invoker_id=200,
        guild_id=100,
    )

    buttons = [child for child in view.children if isinstance(child, discord.ui.Button)]

    assert [(button.label, button.style) for button in buttons] == [
        ("View Bookmark", discord.ButtonStyle.blurple)
    ]
