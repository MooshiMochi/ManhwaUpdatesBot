from __future__ import annotations

import discord

from manhwa_bot.ui.subscribe_view import SubscribeView


def _buttons(view: SubscribeView) -> list[discord.ui.Button]:
    return [child for child in view.children if isinstance(child, discord.ui.Button)]


def test_subscribe_view_uses_v1_search_action_buttons() -> None:
    view = SubscribeView(
        website_key="asura",
        url_name="solo-leveling",
        series_url="https://example.test/solo-leveling",
        show_info_button=True,
        show_bookmark_button=True,
    )

    buttons = _buttons(view)

    assert [(button.label, str(button.emoji), button.style) for button in buttons] == [
        ("Track and Subscribe", "📚", discord.ButtonStyle.blurple),
        ("More Info", "None", discord.ButtonStyle.blurple),
        ("Bookmark", "🔖", discord.ButtonStyle.blurple),
    ]


def test_subscribe_view_can_render_v1_disabled_more_info_placeholder() -> None:
    view = SubscribeView(
        website_key="asura",
        url_name="solo-leveling",
        series_url="https://example.test/solo-leveling",
        show_info_button=False,
        show_bookmark_button=True,
    )

    buttons = _buttons(view)

    assert [(button.label, button.disabled, button.style) for button in buttons] == [
        ("Track and Subscribe", False, discord.ButtonStyle.blurple),
        ("\u200b", True, discord.ButtonStyle.grey),
        ("Bookmark", False, discord.ButtonStyle.blurple),
    ]
