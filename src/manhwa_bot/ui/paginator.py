"""Generic embed paginator view with First / Prev / Page X/Y / Next / Last buttons."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import discord


class Paginator(discord.ui.View):
    """Displays a sequence of embeds with navigation buttons.

    Parameters
    ----------
    embeds:
        Ordered list of embeds to paginate.
    invoker_id:
        Discord user ID who invoked the command. When set, only that user can
        navigate. Pass ``None`` to allow anyone.
    timeout:
        Seconds before the view stops responding (default 300 = 5 minutes).
    items_factory:
        Optional callable ``(page_index) -> list[discord.ui.Item]`` that
        provides additional per-page items (e.g. subscribe buttons) appended
        after the navigation row.
    """

    def __init__(
        self,
        embeds: list[discord.Embed],
        *,
        invoker_id: int | None = None,
        timeout: float = 300.0,
        items_factory: Callable[[int], list[Any]] | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        if not embeds:
            raise ValueError("Paginator requires at least one embed")
        self._embeds = embeds
        self._page = 0
        self._invoker_id = invoker_id
        self._items_factory = items_factory
        self._rebuild()

    # -- public helpers --------------------------------------------------

    @property
    def current_embed(self) -> discord.Embed:
        return self._embeds[self._page]

    @property
    def page(self) -> int:
        return self._page

    @property
    def total_pages(self) -> int:
        return len(self._embeds)

    # -- interaction_check -----------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self._invoker_id is None:
            return True
        if interaction.user.id != self._invoker_id:
            await interaction.response.send_message(
                "Only the person who ran this command can navigate.", ephemeral=True
            )
            return False
        return True

    # -- navigation internals --------------------------------------------

    def _rebuild(self) -> None:
        """Clear and re-add all buttons for the current page."""
        self.clear_items()

        n = len(self._embeds)
        at_start = self._page == 0
        at_end = self._page >= n - 1

        first_btn = discord.ui.Button(
            label="«",
            style=discord.ButtonStyle.secondary,
            disabled=at_start,
            row=0,
        )
        first_btn.callback = self._go_first

        prev_btn = discord.ui.Button(
            label="<",
            style=discord.ButtonStyle.secondary,
            disabled=at_start,
            row=0,
        )
        prev_btn.callback = self._go_prev

        label_btn = discord.ui.Button(
            label=f"Page {self._page + 1}/{n}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=0,
        )

        next_btn = discord.ui.Button(
            label=">",
            style=discord.ButtonStyle.secondary,
            disabled=at_end,
            row=0,
        )
        next_btn.callback = self._go_next

        last_btn = discord.ui.Button(
            label="»",
            style=discord.ButtonStyle.secondary,
            disabled=at_end,
            row=0,
        )
        last_btn.callback = self._go_last

        for btn in (first_btn, prev_btn, label_btn, next_btn, last_btn):
            self.add_item(btn)

        if self._items_factory is not None:
            for item in self._items_factory(self._page):
                self.add_item(item)

    async def _go_first(self, interaction: discord.Interaction) -> None:
        self._page = 0
        self._rebuild()
        await interaction.response.edit_message(embed=self._embeds[self._page], view=self)

    async def _go_prev(self, interaction: discord.Interaction) -> None:
        self._page = max(0, self._page - 1)
        self._rebuild()
        await interaction.response.edit_message(embed=self._embeds[self._page], view=self)

    async def _go_next(self, interaction: discord.Interaction) -> None:
        self._page = min(len(self._embeds) - 1, self._page + 1)
        self._rebuild()
        await interaction.response.edit_message(embed=self._embeds[self._page], view=self)

    async def _go_last(self, interaction: discord.Interaction) -> None:
        self._page = len(self._embeds) - 1
        self._rebuild()
        await interaction.response.edit_message(embed=self._embeds[self._page], view=self)
