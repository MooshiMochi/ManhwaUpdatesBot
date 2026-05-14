"""LayoutPaginator — flips between pre-built LayoutView pages on button click."""

from __future__ import annotations

import logging
from typing import Any

import discord

from .base import BaseLayoutView

_log = logging.getLogger(__name__)


class _NavButton(discord.ui.Button["LayoutPaginator"]):
    def __init__(
        self,
        *,
        label: str,
        style: discord.ButtonStyle,
        target: int | str,
        disabled: bool,
    ) -> None:
        super().__init__(label=label, style=style, disabled=disabled, row=None)
        self._target = target

    async def callback(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        paginator: LayoutPaginator | None = getattr(self, "_paginator", None)
        if paginator is None:
            return
        await paginator.handle_nav(interaction, self._target)


def _nav_action_row(
    paginator: LayoutPaginator, page_index: int, total: int
) -> discord.ui.ActionRow:
    """Build the 5-button nav row for ``page_index`` of ``total``."""
    row = discord.ui.ActionRow()

    is_first = page_index == 0
    is_last = page_index >= total - 1

    btn_first = _NavButton(
        label="⏮️",
        style=discord.ButtonStyle.blurple,
        target="first",
        disabled=is_first,
    )
    btn_prev = _NavButton(
        label="⬅️",
        style=discord.ButtonStyle.blurple,
        target="prev",
        disabled=is_first,
    )
    btn_stop = _NavButton(
        label="⏹️",
        style=discord.ButtonStyle.red,
        target="stop",
        disabled=False,
    )
    btn_next = _NavButton(
        label="➡️",
        style=discord.ButtonStyle.blurple,
        target="next",
        disabled=is_last,
    )
    btn_last = _NavButton(
        label="⏭️",
        style=discord.ButtonStyle.blurple,
        target="last",
        disabled=is_last,
    )

    for btn in (btn_first, btn_prev, btn_stop, btn_next, btn_last):
        btn._paginator = paginator  # type: ignore[attr-defined]
        row.add_item(btn)

    return row


def _add_nav_to_page(page: discord.ui.LayoutView, row: discord.ui.ActionRow) -> None:
    for child in page.children:
        if isinstance(child, discord.ui.Container):
            child.add_item(row)
            return
    page.add_item(row)


class LayoutPaginator:
    """Coordinate navigation across a sequence of pre-built ``LayoutView`` pages.

    Pages are constructed once by the caller; on button click we just swap the
    message's view to the next page — no per-click rebuild work.

    The paginator appends a nav ``ActionRow`` (⏮ ⬅ ⏹ ➡ ⏭) to each page when
    ``total_pages > 1`` and binds the buttons to its own ``handle_nav`` method.

    Pages must be `BaseLayoutView` (or any subclass) so we can wire the
    invoker-lock and on-timeout hooks consistently.
    """

    def __init__(
        self,
        pages: list[discord.ui.LayoutView],
        *,
        invoker_id: int | None,
        timeout: float | None = 3 * 3600,
    ) -> None:
        if not pages:
            raise ValueError("LayoutPaginator requires at least one page")
        self._pages = pages
        self._invoker_id = invoker_id
        self._timeout = timeout
        self._index = 0
        self._message: discord.Message | discord.WebhookMessage | None = None

        total = len(pages)
        for i, page in enumerate(pages):
            # Push the timeout / invoker-lock onto the page if it's BaseLayoutView.
            if isinstance(page, BaseLayoutView):
                if invoker_id is not None and page._invoker_id is None:
                    page._invoker_id = invoker_id
                if timeout is not None:
                    page.timeout = timeout
            if total > 1:
                _add_nav_to_page(page, _nav_action_row(self, i, total))

    @property
    def page(self) -> int:
        return self._index

    @property
    def total_pages(self) -> int:
        return len(self._pages)

    @property
    def current_view(self) -> discord.ui.LayoutView:
        return self._pages[self._index]

    def bind_message(self, message: discord.Message | discord.WebhookMessage | None) -> None:
        self._message = message
        for page in self._pages:
            if isinstance(page, BaseLayoutView):
                page.bind_message(message)

    async def handle_nav(self, interaction: discord.Interaction, target: Any) -> None:
        total = len(self._pages)
        if target == "first":
            new_index = 0
        elif target == "prev":
            new_index = max(0, self._index - 1)
        elif target == "next":
            new_index = min(total - 1, self._index + 1)
        elif target == "last":
            new_index = total - 1
        elif target == "stop":
            await self._stop(interaction)
            return
        elif isinstance(target, int):
            new_index = max(0, min(total - 1, target))
        else:
            return

        if new_index == self._index and target != "stop":
            # Defer with no-op edit to acknowledge.
            try:
                await interaction.response.defer()
            except discord.HTTPException:
                pass
            return

        self._index = new_index
        try:
            await interaction.response.edit_message(view=self._pages[self._index])
        except discord.HTTPException:
            _log.exception("paginator: failed to edit message for nav %s", target)

    async def _stop(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.edit_message(view=None)
        except discord.HTTPException:
            _log.exception("paginator: failed to clear view on stop")
        for page in self._pages:
            page.stop()


async def send_paginated(
    interaction: discord.Interaction,
    pages: list[discord.ui.LayoutView],
    *,
    invoker_id: int | None,
    ephemeral: bool = False,
    edit_original: bool = False,
    timeout: float | None = 3 * 3600,
) -> tuple[LayoutPaginator, discord.Message | discord.WebhookMessage | None]:
    """Send (or edit) the first page of a paginated layout and return the paginator.

    ``edit_original=True`` swaps the interaction's existing response (used by
    commands that already deferred or sent a progress view). Otherwise this
    sends a fresh follow-up.
    """
    paginator = LayoutPaginator(pages, invoker_id=invoker_id, timeout=timeout)
    first = paginator.current_view

    if edit_original:
        msg = await interaction.edit_original_response(
            content=None,
            embed=None,
            embeds=[],
            attachments=[],
            view=first,
        )
    else:
        msg = await interaction.followup.send(view=first, ephemeral=ephemeral, wait=True)

    paginator.bind_message(msg)
    return paginator, msg
