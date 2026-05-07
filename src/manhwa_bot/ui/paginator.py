"""Generic v1-style embed paginator view."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import discord


class Paginator(discord.ui.View):
    """Displays a sequence of embeds with v1 navigation buttons.

    Parameters
    ----------
    embeds:
        Ordered list of embeds to paginate.
    invoker_id:
        Discord user ID who invoked the command. When set, only that user can
        navigate. Pass ``None`` to allow anyone.
    timeout:
        Seconds before the view stops responding (default 3 hours, matching v1).
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
        timeout: float = 3 * 3600,
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
                embed=discord.Embed(
                    title="🚫 You cannot use this menu!",
                    colour=discord.Colour.red(),
                ),
                ephemeral=True,
            )
            return False
        return True

    # -- navigation internals --------------------------------------------

    def _move(self, delta: int) -> None:
        self._page = (self._page + delta) % len(self._embeds)

    def _rebuild(self) -> None:
        """Clear and re-add all buttons for the current page."""
        self.clear_items()

        first_btn = discord.ui.Button(
            label="⏮️",
            style=discord.ButtonStyle.blurple,
            row=0,
        )
        first_btn.callback = self._go_first

        prev_btn = discord.ui.Button(
            label="⬅️",
            style=discord.ButtonStyle.blurple,
            row=0,
        )
        prev_btn.callback = self._go_prev

        stop_btn = discord.ui.Button(
            label="⏹️",
            style=discord.ButtonStyle.red,
            row=0,
        )
        stop_btn.callback = self._stop

        next_btn = discord.ui.Button(
            label="➡️",
            style=discord.ButtonStyle.blurple,
            row=0,
        )
        next_btn.callback = self._go_next

        last_btn = discord.ui.Button(
            label="⏭️",
            style=discord.ButtonStyle.blurple,
            row=0,
        )
        last_btn.callback = self._go_last

        for btn in (first_btn, prev_btn, stop_btn, next_btn, last_btn):
            self.add_item(btn)

        if self._items_factory is not None:
            for item in self._items_factory(self._page):
                self.add_item(item)

    async def _go_first(self, interaction: discord.Interaction) -> None:
        self._page = 0
        self._rebuild()
        await interaction.response.edit_message(embed=self._embeds[self._page], view=self)

    async def _go_prev(self, interaction: discord.Interaction) -> None:
        self._move(-1)
        self._rebuild()
        await interaction.response.edit_message(embed=self._embeds[self._page], view=self)

    async def _stop(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=None)
        self.stop()

    async def _go_next(self, interaction: discord.Interaction) -> None:
        self._move(1)
        self._rebuild()
        await interaction.response.edit_message(embed=self._embeds[self._page], view=self)

    async def _go_last(self, interaction: discord.Interaction) -> None:
        self._page = len(self._embeds) - 1
        self._rebuild()
        await interaction.response.edit_message(embed=self._embeds[self._page], view=self)
