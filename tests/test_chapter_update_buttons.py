"""build_chapter_update_view honours `allowed_buttons`."""

from __future__ import annotations

import discord

from manhwa_bot.ui.components.notifications import (
    ALL_UPDATE_BUTTONS,
    build_chapter_update_view,
)


def _payload() -> dict:
    return {
        "website_key": "comick",
        "url_name": "demo",
        "series_title": "Demo Series",
        "series_url": "https://example.com/demo",
        "chapter": {
            "index": 7,
            "name": "Chapter 7",
            "url": "https://example.com/demo/7",
            "is_premium": False,
        },
        "cover_url": "https://example.com/cover.png",
    }


def _action_rows(view: discord.ui.LayoutView) -> list[discord.ui.ActionRow]:
    return [
        item
        for item in view.walk_children()
        if isinstance(item, discord.ui.ActionRow)
        and any(isinstance(c, discord.ui.Button) for c in item.children)
    ]


def _buttons(view: discord.ui.LayoutView) -> list[discord.ui.Button]:
    return [c for c in view.walk_children() if isinstance(c, discord.ui.Button)]


def test_no_buttons_when_allowed_empty() -> None:
    view = build_chapter_update_view(_payload(), bot=None, allowed_buttons=frozenset())
    assert _action_rows(view) == []
    assert _buttons(view) == []


def test_only_open_chapter_renders_link_button() -> None:
    view = build_chapter_update_view(
        _payload(), bot=None, allowed_buttons=frozenset({"open_chapter"})
    )
    buttons = _buttons(view)
    assert len(buttons) == 1
    assert buttons[0].style is discord.ButtonStyle.link
    assert buttons[0].url == "https://example.com/demo/7"


def test_all_buttons_appear_in_canonical_order() -> None:
    view = build_chapter_update_view(_payload(), bot=None, allowed_buttons=ALL_UPDATE_BUTTONS)
    buttons = _buttons(view)
    assert len(buttons) == 4
    # mark_read, bookmark, subscribe come from DynamicItem.item; open_chapter is a link button.
    assert buttons[0].custom_id == "mu:upd:mr:comick:demo:7"
    assert buttons[1].custom_id == "mu:upd:bm:comick:demo"
    assert buttons[2].custom_id == "mu:upd:sub:comick:demo"
    assert buttons[3].style is discord.ButtonStyle.link
    assert buttons[3].url == "https://example.com/demo/7"


def test_container_has_no_accent_colour() -> None:
    view = build_chapter_update_view(_payload(), bot=None, allowed_buttons=ALL_UPDATE_BUTTONS)
    containers = [c for c in view.children if isinstance(c, discord.ui.Container)]
    assert containers
    for c in containers:
        assert c.accent_colour is None


def test_mark_read_falls_back_to_index_when_missing() -> None:
    payload = _payload()
    payload["chapter"].pop("index")
    view = build_chapter_update_view(
        payload, bot=None, allowed_buttons=frozenset({"mark_read"})
    )
    buttons = _buttons(view)
    assert len(buttons) == 1
    # -1 sentinel encodes "unknown index" — handler upserts as last_read_index=-1.
    assert buttons[0].custom_id == "mu:upd:mr:comick:demo:-1"


def test_view_has_no_timeout() -> None:
    view = build_chapter_update_view(_payload(), bot=None, allowed_buttons=ALL_UPDATE_BUTTONS)
    assert view.timeout is None
