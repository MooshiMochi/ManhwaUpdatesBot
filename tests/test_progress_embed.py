"""Tests for Discord crawler progress embed rendering."""

from __future__ import annotations

from types import SimpleNamespace

import discord

from manhwa_bot.ui.progress_embed import ProgressEmbedState, progress_event_message


def test_numbered_history_title_footer_and_default_color() -> None:
    state = ProgressEmbedState(command_name="/info", request_id="abc123")

    state.add("Sent request to crawler")
    state.add("Preparing scrape for Toongod")

    embed = state.to_embed()

    assert embed.title == "Running /info"
    assert embed.description == "1. Sent request to crawler.\n2. Preparing scrape for Toongod..."
    assert embed.footer.text == "Request ID: abc123"
    assert embed.colour == discord.Colour.blurple()


def test_warning_latest_event_uses_gold_color() -> None:
    state = ProgressEmbedState(command_name="/info", request_id="abc123")

    state.add("Sent request to crawler")
    state.add("Crawler retrying request", severity="warning")

    embed = state.to_embed()

    assert embed.colour == discord.Colour.gold()


def test_warning_severity_can_be_positional() -> None:
    state = ProgressEmbedState(command_name="/info", request_id="abc123")

    state.add("Retrying", "warning")

    embed = state.to_embed()

    assert embed.description == "1. Retrying..."
    assert embed.colour == discord.Colour.gold()


def test_final_error_uses_red_color_and_no_active_suffix() -> None:
    state = ProgressEmbedState(command_name="/info", request_id="abc123")

    state.add("Sent request to crawler")
    state.add("Crawler request failed", severity="error")

    embed = state.to_embed(final_error=True)

    assert embed.description == "1. Sent request to crawler.\n2. Crawler request failed."
    assert embed.colour == discord.Colour.red()


def test_bounded_history_preserves_first_omitted_marker_and_newest_events() -> None:
    state = ProgressEmbedState(command_name="/info", request_id="abc123", max_visible_events=4)

    for index in range(1, 9):
        state.add(f"Progress update {index}")

    embed = state.to_embed()

    assert embed.description == (
        "1. Progress update 1.\n"
        "... 4 earlier updates omitted.\n"
        "6. Progress update 6.\n"
        "7. Progress update 7.\n"
        "8. Progress update 8..."
    )


def test_max_visible_events_one_preserves_first_omitted_marker_and_newest_event() -> None:
    state = ProgressEmbedState(command_name="/info", request_id="abc123", max_visible_events=1)

    for index in range(1, 5):
        state.add(f"Progress update {index}")

    embed = state.to_embed()

    assert embed.description == (
        "1. Progress update 1.\n... 2 earlier updates omitted.\n4. Progress update 4..."
    )


def test_max_visible_events_one_with_two_events_skips_zero_omitted_marker() -> None:
    state = ProgressEmbedState(command_name="/info", request_id="abc", max_visible_events=1)

    state.add("First update")
    state.add("Second update")

    embed = state.to_embed()

    assert embed.description == "1. First update.\n2. Second update..."
    assert "0 earlier updates omitted" not in embed.description


def test_progress_event_message_converts_typed_object() -> None:
    event = SimpleNamespace(
        title="Retrying scrape",
        detail="Temporary crawler timeout",
        status="retrying",
    )

    message, severity = progress_event_message(event)

    assert message == "Retrying scrape: Temporary crawler timeout."
    assert severity == "warning"


def test_progress_event_message_converts_dict_event() -> None:
    message, severity = progress_event_message(
        {
            "title": "Scrape failed",
            "detail": "Series not found",
            "status": "failed",
        }
    )

    assert message == "Scrape failed: Series not found."
    assert severity == "error"
