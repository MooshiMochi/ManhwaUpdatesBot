"""Confirmation prompt (Yes/No) as a Components V2 LayoutView."""

from __future__ import annotations

import discord

from .. import emojis
from .base import BaseLayoutView, footer_section


class ConfirmLayoutView(BaseLayoutView):
    """V2 confirm dialog. Sets ``self.value`` to ``True``/``False`` (or ``None`` on timeout)."""

    def __init__(
        self,
        *,
        author_id: int,
        prompt: str,
        prompt_title: str = "Are you sure?",
        bot: discord.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(invoker_id=author_id, timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None

        container = discord.ui.Container(
            discord.ui.TextDisplay(f"## {emojis.WARNING}  {prompt_title}"),
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay(prompt),
            accent_colour=discord.Colour.orange(),
        )
        if bot is not None:
            container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
            container.add_item(footer_section(bot))
        self.add_item(container)

        row = discord.ui.ActionRow()
        confirm_btn = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.green)
        confirm_btn.callback = self._on_confirm  # type: ignore[assignment]
        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.red)
        cancel_btn.callback = self._on_cancel  # type: ignore[assignment]
        row.add_item(confirm_btn)
        row.add_item(cancel_btn)
        self.add_item(row)
        self._confirm_btn = confirm_btn
        self._cancel_btn = cancel_btn

    def _disable_all(self) -> None:
        for btn in (self._confirm_btn, self._cancel_btn):
            btn.disabled = True

    async def _on_confirm(self, interaction: discord.Interaction) -> None:
        self.value = True
        self._disable_all()
        await interaction.response.edit_message(view=self)
        self.stop()

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        self.value = False
        self._disable_all()
        await interaction.response.edit_message(view=self)
        self.stop()
