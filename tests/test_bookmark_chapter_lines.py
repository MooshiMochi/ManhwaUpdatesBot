"""Bookmark views surface the series' latest chapter and the next chapter to read."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from manhwa_bot.db.bookmarks import Bookmark
from manhwa_bot.ui.components import bookmark


def _collect_text(view) -> str:
    out: list[str] = []

    def walk(item) -> None:
        content = getattr(item, "content", None)
        if isinstance(content, str):
            out.append(content)
        for child in getattr(item, "children", None) or []:
            walk(child)

    for child in view.children:
        walk(child)
    return "\n".join(out)


class _Crawler:
    async def request(self, type_: str, **kwargs):
        if type_ == "series_data":
            slug = str(kwargs.get("url_name") or kwargs.get("url") or "series")
            return {
                "website_key": "site",
                "url_name": slug,
                "url": f"https://site.test/series/{slug}",
                "title": slug.replace("-", " ").title(),
                "cover_url": None,
                "status": "Ongoing",
                "chapters": [
                    {"name": "Chapter 1", "url": "https://example.test/1"},
                    {"name": "Chapter 2", "url": "https://example.test/2"},
                    {"name": "Chapter 3", "url": "https://example.test/3"},
                ],
                "website": {"key": "site", "name": "Site", "base_url": "https://site.test"},
            }
        return {}


def _browser(bookmarks: list[Bookmark]) -> bookmark.BookmarkBrowserView:
    class _Tracked:
        async def find(self, *_a, **_k):
            return None

        async def list_guilds_tracking(self, *_a, **_k) -> list:
            return []

    class _Subs:
        async def is_subscribed(self, *_a, **_k) -> bool:
            return False

    class _GuildSettings:
        async def list_scanlator_channels(self, *_a, **_k) -> list:
            return []

        async def get(self, *_a, **_k):
            return None

    return bookmark.BookmarkBrowserView(
        bookmarks,
        store=SimpleNamespace(),
        tracked=_Tracked(),
        subscriptions=_Subs(),
        guild_settings=_GuildSettings(),
        crawler=_Crawler(),
        invoker_id=1,
    )


def test_bookmark_visual_view_shows_latest_and_next_chapter_links() -> None:
    bm = Bookmark(
        user_id=1,
        website_key="site",
        url_name="demo",
        folder="Reading",
        last_read_chapter="Chapter 1",
        last_read_index=0,
        created_at="2026-05-14T00:00:00",
        updated_at="2026-05-14T00:00:00",
    )
    browser = _browser([bm])

    asyncio.run(browser._rebuild())
    text = _collect_text(browser)

    assert "Latest Chapter" in text
    # chapters[-1] is the latest.
    assert "[Chapter 3](https://example.test/3)" in text
    assert "Next Chapter" in text
    # last_read_index 0 -> next to read is chapters[1].
    assert "[Chapter 2](https://example.test/2)" in text


def test_bookmark_detail_view_shows_latest_chapter_link() -> None:
    view = bookmark.build_bookmark_detail_view(
        title="Series",
        series_url="https://example.test/series",
        website_key="site",
        cover_url=None,
        scanlator_base_url=None,
        last_read_chapter="[Chapter 1](https://example.test/1)",
        next_chapter="[Chapter 2](https://example.test/2)",
        latest_chapter="[Chapter 3](https://example.test/3)",
        folder="Reading",
        available_chapters_label="3",
        chapter_count=3,
        status="Ongoing",
        is_completed=False,
    )
    text = _collect_text(view)
    assert "Latest Chapter" in text
    assert "[Chapter 3](https://example.test/3)" in text
