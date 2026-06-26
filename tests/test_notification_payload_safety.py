"""Chapter-update notifications must never produce an unsendable payload.

Regression coverage for the production ``400 Bad Request (50035) Invalid Form
Body`` drops: an over-100-char button ``custom_id`` (long series slugs) or a
malformed cover ``media.url`` made ``channel.send`` raise, the dispatcher
swallowed it, and the notification was lost. The view factory must instead
degrade gracefully so the message still sends.
"""

from __future__ import annotations

import discord

from manhwa_bot.ui.components.notifications import build_chapter_update_view

_CHAPTER = {"name": "Chapter 1", "index": 1, "url": "https://example.test/ch/1"}


def _button_custom_ids(view: discord.ui.LayoutView) -> list[str]:
    return [
        child.custom_id
        for child in view.walk_children()
        if isinstance(child, discord.ui.Button) and child.custom_id
    ]


def _media_galleries(view: discord.ui.LayoutView) -> list[discord.ui.MediaGallery]:
    return [c for c in view.walk_children() if isinstance(c, discord.ui.MediaGallery)]


def test_overlong_slug_drops_only_the_overflowing_button() -> None:
    # With website_key "site", a 84-char url_name pushes only the mark_read id
    # (which also encodes the chapter index) past Discord's 100-char ceiling;
    # bookmark/subscribe/open_chapter still fit and must survive.
    payload = {
        "series_title": "S",
        "website_key": "site",
        "url_name": "a" * 84,
        "chapter": _CHAPTER,
    }

    view = build_chapter_update_view(payload)

    custom_ids = _button_custom_ids(view)
    assert custom_ids, "expected the still-valid buttons to be rendered"
    assert all(1 <= len(cid) <= 100 for cid in custom_ids), {cid: len(cid) for cid in custom_ids}
    assert not any(cid.startswith("mu:upd:mr:") for cid in custom_ids)
    assert len(custom_ids) == 3


def test_extreme_slug_yields_no_overlong_custom_ids() -> None:
    payload = {
        "series_title": "S",
        "website_key": "site",
        "url_name": "z" * 300,
        "chapter": _CHAPTER,
    }

    view = build_chapter_update_view(payload)

    custom_ids = _button_custom_ids(view)
    assert all(1 <= len(cid) <= 100 for cid in custom_ids), {cid: len(cid) for cid in custom_ids}


def test_malformed_cover_url_omits_media_gallery() -> None:
    payload = {
        "series_title": "S",
        "website_key": "site",
        "url_name": "series",
        "chapter": _CHAPTER,
        "cover_url": "not a real url",
    }

    view = build_chapter_update_view(payload)

    assert _media_galleries(view) == []


def test_valid_cover_url_keeps_media_gallery() -> None:
    payload = {
        "series_title": "S",
        "website_key": "site",
        "url_name": "series",
        "chapter": _CHAPTER,
        "cover_url": "https://example.test/cover.jpg",
    }

    view = build_chapter_update_view(payload)

    assert len(_media_galleries(view)) == 1
