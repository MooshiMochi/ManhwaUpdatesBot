"""DynamicItem custom_id templates parse the same data they encode."""

from __future__ import annotations

import re

from manhwa_bot.ui.components.notification_buttons import (
    BOOKMARK_TEMPLATE,
    BookmarkButton,
    MARK_READ_TEMPLATE,
    MarkReadButton,
    SUBSCRIBE_TEMPLATE,
    SubscribeToggleButton,
)


def test_mark_read_template_round_trips() -> None:
    button = MarkReadButton("comick", "solo-leveling", 137)
    cid = button.item.custom_id
    assert cid == "mu:upd:mr:comick:solo-leveling:137"
    match = re.fullmatch(MARK_READ_TEMPLATE, cid)
    assert match is not None
    assert match["wk"] == "comick"
    assert match["un"] == "solo-leveling"
    assert int(match["idx"]) == 137


def test_bookmark_template_round_trips() -> None:
    button = BookmarkButton("mangadex", "tower-of-god")
    cid = button.item.custom_id
    assert cid == "mu:upd:bm:mangadex:tower-of-god"
    match = re.fullmatch(BOOKMARK_TEMPLATE, cid)
    assert match is not None
    assert match["wk"] == "mangadex"
    assert match["un"] == "tower-of-god"


def test_subscribe_template_round_trips() -> None:
    button = SubscribeToggleButton("asurascans", "the-beginning-after-the-end")
    cid = button.item.custom_id
    assert cid == "mu:upd:sub:asurascans:the-beginning-after-the-end"
    match = re.fullmatch(SUBSCRIBE_TEMPLATE, cid)
    assert match is not None
    assert match["wk"] == "asurascans"
    assert match["un"] == "the-beginning-after-the-end"


def test_mark_read_custom_id_under_100_chars_for_realistic_inputs() -> None:
    # Worst-case realistic slug lengths.
    button = MarkReadButton("a" * 24, "b" * 60, 9999)
    assert len(button.item.custom_id) <= 100
