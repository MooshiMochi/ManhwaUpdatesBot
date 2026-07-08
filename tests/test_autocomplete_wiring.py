"""Guards which autocomplete callback each series-input command is wired to.

`/info`, `/chapters`, and `/bookmark new` draw from the full crawler catalog
(`autocomplete.all_manga`), not the guild-tracked list. The subscribe/update/
delete commands intentionally keep their context-specific autocompletes.
"""

from __future__ import annotations

from discord import app_commands

from manhwa_bot import autocomplete
from manhwa_bot.cogs.bookmarks import BookmarksCog
from manhwa_bot.cogs.catalog import CatalogCog
from manhwa_bot.cogs.subscriptions import SubscriptionsCog
from manhwa_bot.cogs.tracking import TrackingCog


def _subcommand(group: app_commands.Group, name: str) -> app_commands.Command:
    match = next((command for command in group.commands if command.name == name), None)
    assert isinstance(match, app_commands.Command)
    return match


def _autocomplete_cb(command: app_commands.Command, param_name: str):
    return command._params[param_name].autocomplete


def test_info_uses_full_catalog_autocomplete() -> None:
    assert _autocomplete_cb(CatalogCog.info, "series") is autocomplete.all_manga


def test_chapters_uses_full_catalog_autocomplete() -> None:
    assert _autocomplete_cb(CatalogCog.chapters, "series") is autocomplete.all_manga


def test_bookmark_new_uses_full_catalog_autocomplete() -> None:
    new = _subcommand(BookmarksCog.bookmark, "new")
    assert _autocomplete_cb(new, "manga_url_or_id") is autocomplete.all_manga


def test_track_new_uses_catalog_search_autocomplete() -> None:
    new = _subcommand(TrackingCog.track, "new")
    assert _autocomplete_cb(new, "manga_url") is autocomplete.track_new_url_or_search


def test_context_specific_commands_keep_their_autocompletes() -> None:
    # These intentionally stay scoped and must NOT switch to the full catalog.
    sub_new = _subcommand(SubscriptionsCog.subscribe, "new")
    assert _autocomplete_cb(sub_new, "manga_id") is autocomplete.tracked_manga_in_guild_with_all

    sub_delete = _subcommand(SubscriptionsCog.subscribe, "delete")
    assert _autocomplete_cb(sub_delete, "manga_id") is autocomplete.user_subscribed_manga_with_all

    track_remove = _subcommand(TrackingCog.track, "remove")
    assert _autocomplete_cb(track_remove, "manga_id") is autocomplete.tracked_manga_in_guild

    bm_update = _subcommand(BookmarksCog.bookmark, "update")
    assert _autocomplete_cb(bm_update, "series") is autocomplete.user_bookmarks
    assert _autocomplete_cb(bm_update, "chapter_index") is autocomplete.user_bookmark_chapters

    bm_delete = _subcommand(BookmarksCog.bookmark, "delete")
    assert _autocomplete_cb(bm_delete, "series") is autocomplete.user_bookmarks
