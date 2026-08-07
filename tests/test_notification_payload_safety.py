"""Chapter-update notifications must never produce an unsendable payload.

Regression coverage for the production ``400 Bad Request (50035) Invalid Form
Body`` drops: an over-100-char button ``custom_id`` (long series slugs) or a
malformed cover ``media.url`` made ``channel.send`` raise, the dispatcher
swallowed it, and the notification was lost. The view factory must instead
degrade gracefully so the message still sends.
"""

from __future__ import annotations

import discord
import pytest

from manhwa_bot.ui.components.notifications import (
    build_chapter_update_view,
    build_status_change_view,
)

_CHAPTER = {"name": "Chapter 1", "index": 1, "url": "https://example.test/ch/1"}


def _button_custom_ids(view: discord.ui.LayoutView) -> list[str]:
    return [
        child.custom_id
        for child in view.walk_children()
        if isinstance(child, discord.ui.Button) and child.custom_id
    ]


def _media_galleries(view: discord.ui.LayoutView) -> list[discord.ui.MediaGallery]:
    return [c for c in view.walk_children() if isinstance(c, discord.ui.MediaGallery)]


def _media_gallery_urls(view: discord.ui.LayoutView) -> list[str]:
    return [item.media.url for gallery in _media_galleries(view) for item in gallery.items]


def _view_text(view: discord.ui.LayoutView) -> str:
    return "\n".join(
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    )


def test_long_comix_slug_keeps_all_four_buttons_with_compact_action_token() -> None:
    payload = {
        "series_title": "S",
        "website_key": "comix",
        "url_name": (
            "the-final-boss-prince-is-somehow-obsessed-with-the-chubby-villainess-reincarnated-me"
        ),
        "chapter": _CHAPTER,
        "action_token": "AbCdEf123456",
    }

    view = build_chapter_update_view(payload)

    custom_ids = _button_custom_ids(view)
    assert all(1 <= len(cid) <= 100 for cid in custom_ids), {cid: len(cid) for cid in custom_ids}
    assert len(custom_ids) == 4
    assert {cid.split(":")[2] for cid in custom_ids} == {"mr", "bm", "sub", "lr"}


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


def test_chapter_view_accepts_attachment_cover_override_without_mutating_payload() -> None:
    payload = {
        "series_title": "S",
        "website_key": "comix",
        "url_name": "series",
        "chapter": _CHAPTER,
        "cover_url": "https://example.test/cover.jpg",
    }

    view = build_chapter_update_view(
        payload, cover_media_url="attachment://comix-cover-deadbeef.jpg"
    )

    assert _media_gallery_urls(view) == ["attachment://comix-cover-deadbeef.jpg"]
    assert payload["cover_url"] == "https://example.test/cover.jpg"


def test_status_view_accepts_attachment_cover_override() -> None:
    view = build_status_change_view(
        {
            "series_title": "S",
            "website_key": "comix",
            "url_name": "series",
            "old_status": "Ongoing",
            "new_status": "Completed",
            "cover_url": "https://example.test/cover.jpg",
        },
        cover_media_url="attachment://comix-cover-deadbeef.jpg",
    )

    assert _media_gallery_urls(view) == ["attachment://comix-cover-deadbeef.jpg"]


@pytest.mark.parametrize(
    "attachment_url",
    [
        "attachment://",
        "attachment://has space.jpg",
        "attachment://../cover.jpg",
        "attachment://folder/cover.jpg",
        "attachment://folder\\cover.jpg",
        "attachment://cover?.jpg",
    ],
)
def test_malformed_attachment_cover_override_is_rejected(attachment_url: str) -> None:
    payload = {
        "series_title": "S",
        "website_key": "comix",
        "url_name": "series",
        "chapter": _CHAPTER,
    }

    view = build_chapter_update_view(payload, cover_media_url=attachment_url)

    assert _media_galleries(view) == []


def test_notification_footer_names_scanlator_and_check_source() -> None:
    payload = {
        "series_title": "S",
        "website_key": "comix",
        "url_name": "series",
        "chapter": _CHAPTER,
        "scanlator_name": "Comix",
        "source": "main",
    }

    view = build_chapter_update_view(payload)

    assert "-# Scanlator: Comix • via main check" in _view_text(view)
