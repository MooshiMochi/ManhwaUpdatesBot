from __future__ import annotations

from types import SimpleNamespace

import discord

from manhwa_bot.ui.settings_view import _MAIN_OPTIONS, SettingsView


def test_settings_main_select_options_match_v1_labels() -> None:
    assert [option.label for option in _MAIN_OPTIONS] == [
        "Set the updates channel",
        "Set Default ping role",
        "Auto create role for new tracked manhwa",
        "Set the bot manager role",
        "Set the system notifications channel",
        "Show buttons for chapter updates",
        "Custom Scanlator Channels",
        "Notify for Paid Chapter releases",
    ]


def test_settings_view_includes_v1_action_buttons() -> None:
    view = SettingsView(SimpleNamespace(db=None), 123, None, [])
    buttons = [child for child in view.children if isinstance(child, discord.ui.Button)]

    assert [(button.label, button.style) for button in buttons] == [
        ("Save", discord.ButtonStyle.blurple),
        ("Cancel", discord.ButtonStyle.blurple),
        ("Delete Mode: Off", discord.ButtonStyle.green),
        ("Delete config", discord.ButtonStyle.red),
    ]
