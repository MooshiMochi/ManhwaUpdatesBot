from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from manhwa_bot.db.bookmarks import Bookmark
from manhwa_bot.ui.components import bookmark, tracking


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


def test_grouped_list_orders_scanlators_then_titles_and_renders_note() -> None:
    items = [
        {"title": "Zeta", "url": "https://x/z", "website_key": "comix"},
        {"title": "Alpha", "url": "https://x/a", "website_key": "comix", "note": "🔔 <@&5>"},
        {"title": "Beta", "url": "https://x/b", "website_key": "asura"},
    ]
    views = tracking.build_grouped_list_views(items, title="Tracked", bot=None, invoker_id=1)
    text = _collect_text(views[0])

    # Scanlator headers in alphabetical order.
    assert text.index("Asura") < text.index("Comix")
    # asura's series sorts ahead of every comix series.
    assert text.index("Beta") < text.index("Alpha")
    # Within comix, titles are alphabetical.
    assert text.index("Alpha") < text.index("Zeta")
    # The per-item ping-role note is rendered.
    assert "🔔 <@&5>" in text


def _make_bookmark(website_key: str, url_name: str, updated_at: str) -> Bookmark:
    return Bookmark(
        user_id=1,
        website_key=website_key,
        url_name=url_name,
        folder="Reading",
        last_read_chapter="Chapter 1",
        last_read_index=0,
        created_at="2026-05-14T00:00:00",
        updated_at=updated_at,
    )


def _make_browser(bookmarks: list[Bookmark]) -> bookmark.BookmarkBrowserView:
    class FakeTrackedStore:
        async def find(self, *_a, **_k):
            return None

        async def list_guilds_tracking(self, *_a, **_k) -> list:
            return []

    class FakeSubscriptionStore:
        async def is_subscribed(self, *_a, **_k) -> bool:
            return False

    class FakeGuildSettingsStore:
        async def list_scanlator_channels(self, *_a, **_k) -> list:
            return []

        async def get(self, *_a, **_k):
            return None

    class FakeCrawler:
        async def request(self, *_a, **_k) -> dict:
            return {}

    return bookmark.BookmarkBrowserView(
        bookmarks,
        store=SimpleNamespace(),
        tracked=FakeTrackedStore(),
        subscriptions=FakeSubscriptionStore(),
        guild_settings=FakeGuildSettingsStore(),
        crawler=FakeCrawler(),
        invoker_id=1,
    )


def test_bookmark_sort_by_scanlator_orders_by_site_then_slug() -> None:
    async def _run() -> None:
        browser = _make_browser(
            [
                _make_bookmark("comix", "zeta", "2026-05-14T00:00:01"),
                _make_bookmark("asura", "beta", "2026-05-14T00:00:02"),
                _make_bookmark("comix", "alpha", "2026-05-14T00:00:03"),
            ]
        )
        browser._rebuild_and_edit = AsyncMock()  # type: ignore[method-assign]
        interaction = SimpleNamespace(data={"values": ["scanlator"]})

        await browser._on_sort_select(interaction)  # type: ignore[arg-type]

        assert [(bm.website_key, bm.url_name) for bm in browser._filtered] == [
            ("asura", "beta"),
            ("comix", "alpha"),
            ("comix", "zeta"),
        ]

    asyncio.run(_run())
