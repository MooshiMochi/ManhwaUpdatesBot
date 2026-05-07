from __future__ import annotations

import discord

from manhwa_bot.ui.confirm_view import ConfirmView


def test_confirm_view_uses_v1_button_labels_and_styles() -> None:
    view = ConfirmView(author_id=123)
    buttons = [child for child in view.children if isinstance(child, discord.ui.Button)]

    assert [(button.label, button.style) for button in buttons] == [
        ("Confirm", discord.ButtonStyle.green),
        ("Cancel", discord.ButtonStyle.red),
    ]


def test_confirm_prompt_embed_defaults_to_v1_shape() -> None:
    embed = ConfirmView.prompt_embed("Continue?")

    assert embed.title == "Are you sure?"
    assert embed.description == "Continue?"
    assert embed.colour == discord.Colour.orange()
