from __future__ import annotations

from manhwa_bot.ui.components.help import build_stats_view


def _collect_text(view) -> str:
    out: list[str] = []

    def walk(item) -> None:
        content = getattr(item, "content", None)
        if isinstance(content, str):
            out.append(content)
        for child in getattr(item, "children", None) or []:
            walk(child)

    for child in view.children:
        walk(child)
    return "\n".join(out)


def test_stats_view_renders_columnar_grid_and_timestamps() -> None:
    view = build_stats_view(
        bookmarks_count=1234,
        tracks_count=567,
        subs_count=89,
        manhwa_count=2345,
        websites_count=42,
        guilds_count=1011,
        users_count=890,
        start_unix=1000,
        bot_created_unix=2000,
        bot=None,
    )
    text = _collect_text(view)

    # Columns are rendered in a monospace code block so they line up.
    assert "```" in text

    # All seven count metrics are present.
    for label in (
        "Bookmarks",
        "Tracked",
        "Subscriptions",
        "Manhwas",
        "Websites",
        "Servers",
        "Users",
    ):
        assert label in text, f"missing metric label: {label}"

    # Values render (thousands separators are fine).
    assert "1,234" in text
    assert "2,345" in text

    # Uptime / Born stay as relative timestamps (cannot live inside a code block).
    assert "<t:1000:R>" in text
    assert "<t:2000:R>" in text


def test_stats_grid_rows_are_width_aligned() -> None:
    view = build_stats_view(
        bookmarks_count=1,
        tracks_count=22,
        subs_count=333,
        manhwa_count=4444,
        websites_count=5,
        guilds_count=66,
        users_count=777,
        start_unix=1,
        bot_created_unix=2,
        bot=None,
    )
    text = _collect_text(view)
    block = text.split("```")[1]
    grid_lines = [line for line in block.splitlines() if line.strip()]
    # The grid packs the seven metrics into rows of three (3 + 3 + 1).
    assert len(grid_lines) == 3
    # First two rows hold three aligned cells each => identical rendered width.
    assert len(grid_lines[0]) == len(grid_lines[1])
