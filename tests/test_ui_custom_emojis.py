"""Custom emoji usage in Components V2 views."""

from __future__ import annotations

from collections.abc import Iterable

import discord

from manhwa_bot.ui.components import error, progress, tracking
from manhwa_bot.ui.components.settings import _bool_emoji

WARNING = "<a:awarning:1205218288016302182>"
CHECK = "<a:check2:1188236008135868487>"
ERROR = "<a:error_no:1205218470594084954>"
LOADING = "<a:loading:1172323932834107454>"
LOCK = "<:purple_lock:1335845570748616705>"


def _text_content(item: discord.ui.Item[object]) -> Iterable[str]:
    content = getattr(item, "content", None)
    if isinstance(content, str):
        yield content
    for child in getattr(item, "children", ()):
        yield from _text_content(child)


def _view_text(view: discord.ui.LayoutView) -> str:
    return "\n".join(text for child in view.children for text in _text_content(child))


def test_error_success_and_progress_views_use_custom_status_emojis() -> None:
    assert ERROR in _view_text(error.build_error_view("Nope"))
    assert CHECK in _view_text(error.build_success_view(title="Saved", description="Done"))

    state = progress.ProgressLayoutState(command_name="track", request_id="abc")
    state.add("Fetching")
    assert LOADING in _view_text(state.to_view())

    state.add("Retrying", severity="warning")
    assert WARNING in _view_text(state.to_view())

    assert ERROR in _view_text(state.to_view(final_error=True))


def test_tracking_warnings_and_role_errors_use_custom_emojis() -> None:
    success_text = _view_text(
        tracking.build_tracking_success_view(
            title="Series",
            series_url="https://example.test/series",
            ping_role=None,
            notif_channel=None,
            cover_url=None,
            is_dm=False,
            warning="Crawler warning",
        )
    )
    assert CHECK in success_text
    assert WARNING in success_text

    assert ERROR in _view_text(tracking.build_role_managed_view())
    assert ERROR in _view_text(tracking.build_role_hierarchy_view())


def test_boolean_and_lock_status_helpers_use_custom_emojis() -> None:
    assert _bool_emoji(True) == CHECK
    assert _bool_emoji(False) == ERROR

    view = tracking.build_simple_status_view(
        title=f"{LOCK}  Premium setting locked",
        description="Upgrade required.",
        accent=discord.Colour.blurple(),
    )
    assert LOCK in _view_text(view)
