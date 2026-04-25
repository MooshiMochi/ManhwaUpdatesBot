"""Paginator — page-bound clamping and button disabled states."""

from __future__ import annotations

import discord

from manhwa_bot.ui.paginator import Paginator


def _embeds(n: int) -> list[discord.Embed]:
    return [discord.Embed(title=f"Page {i + 1}") for i in range(n)]


def _nav_buttons(p: Paginator) -> tuple:
    """Return (first, prev, label, next, last) button items."""
    items = list(p.children)
    # The first 5 items are always the nav buttons.
    return tuple(items[:5])


# -- single page ---------------------------------------------------------


def test_single_page_all_nav_disabled() -> None:
    p = Paginator(_embeds(1))
    first, prev, label, nxt, last = _nav_buttons(p)

    assert first.disabled
    assert prev.disabled
    assert label.disabled
    assert nxt.disabled
    assert last.disabled
    assert label.label == "Page 1/1"


# -- multi-page initial state -------------------------------------------


def test_multi_page_first_page_state() -> None:
    p = Paginator(_embeds(3))
    first, prev, label, nxt, last = _nav_buttons(p)

    assert first.disabled, "«  should be disabled on first page"
    assert prev.disabled, "<  should be disabled on first page"
    assert not nxt.disabled, ">  should be enabled on first page"
    assert not last.disabled, "»  should be enabled on first page"
    assert label.label == "Page 1/3"
    assert p.page == 0
    assert p.total_pages == 3


def test_multi_page_last_page_state() -> None:
    p = Paginator(_embeds(3))
    # Manually advance to the last page
    p._page = 2
    p._rebuild()

    first, prev, label, nxt, last = _nav_buttons(p)

    assert not first.disabled
    assert not prev.disabled
    assert nxt.disabled
    assert last.disabled
    assert label.label == "Page 3/3"


def test_middle_page_all_nav_enabled() -> None:
    p = Paginator(_embeds(5))
    p._page = 2
    p._rebuild()

    first, prev, label, nxt, last = _nav_buttons(p)

    assert not first.disabled
    assert not prev.disabled
    assert not nxt.disabled
    assert not last.disabled
    assert label.label == "Page 3/5"


# -- current_embed reflects the page ------------------------------------


def test_current_embed_matches_page() -> None:
    embeds = _embeds(4)
    p = Paginator(embeds)
    assert p.current_embed is embeds[0]

    p._page = 3
    p._rebuild()
    assert p.current_embed is embeds[3]


# -- items_factory adds extra items per page ----------------------------


def test_items_factory_called_per_rebuild() -> None:
    call_log: list[int] = []

    def factory(page: int) -> list[discord.ui.Item]:
        call_log.append(page)
        btn = discord.ui.Button(label=f"Extra {page}", row=1)
        return [btn]

    p = Paginator(_embeds(3), items_factory=factory)
    assert call_log == [0]  # initial build

    # There should be 6 items: 5 nav + 1 extra
    assert len(list(p.children)) == 6

    p._page = 1
    p._rebuild()
    assert call_log[-1] == 1
    assert len(list(p.children)) == 6


# -- single-embed edge: ValueError on empty list ------------------------


def test_empty_embeds_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="at least one embed"):
        Paginator([])
