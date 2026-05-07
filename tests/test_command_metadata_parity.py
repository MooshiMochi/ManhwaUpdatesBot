from __future__ import annotations

from discord import app_commands

from manhwa_bot.cogs.bookmarks import BookmarksCog
from manhwa_bot.cogs.catalog import CatalogCog
from manhwa_bot.cogs.general import GeneralCog
from manhwa_bot.cogs.settings import SettingsCog
from manhwa_bot.cogs.subscriptions import SubscriptionsCog
from manhwa_bot.cogs.tracking import TrackingCog


def _subcommand(group: app_commands.Group, name: str) -> app_commands.Command:
    match = next((command for command in group.commands if command.name == name), None)
    assert isinstance(match, app_commands.Command)
    return match


def _param(command: app_commands.Command, name: str) -> app_commands.Parameter:
    match = next((param for param in command.parameters if param.name == name), None)
    assert match is not None
    return match


def test_track_metadata_matches_v1() -> None:
    assert TrackingCog.track.description == (
        "(Mods) Start tracking a manga for the server to get notifications."
    )

    new = _subcommand(TrackingCog.track, "new")
    assert new.description == "Start tracking a manga for the server to get notifications."
    assert _param(new, "manga_url").description == "The URL of the manga you want to track."
    assert _param(new, "ping_role").description == ("The role to ping when a notification is sent.")

    update = _subcommand(TrackingCog.track, "update")
    assert update.description == "Update a tracked manga for the server to get notifications."
    assert _param(update, "manga_id").display_name == "manga"
    assert _param(update, "manga_id").description == "The name of the manga."
    assert _param(update, "role").description == "The new role to ping."

    remove = _subcommand(TrackingCog.track, "remove")
    assert remove.description == "Stop tracking a manga on this server."
    assert _param(remove, "manga_id").display_name == "manga"
    assert _param(remove, "manga_id").description == "The name of the manga."
    assert _param(remove, "delete_role").description == (
        "Whether to delete the role associated with the manhwa."
    )

    assert _subcommand(TrackingCog.track, "list").description == (
        "List all the manga that are being tracked in this server."
    )


def test_subscribe_metadata_matches_v1() -> None:
    assert SubscriptionsCog.subscribe.description == "Subscribe to a manga to get notifications."

    new = _subcommand(SubscriptionsCog.subscribe, "new")
    assert new.description == "Subscribe to a tracked manga to get new release notifications."
    assert _param(new, "manga_id").display_name == "manga"
    assert _param(new, "manga_id").description == (
        "The name of the tracked manga you want to subscribe to."
    )

    delete = _subcommand(SubscriptionsCog.subscribe, "delete")
    assert delete.description == "Unsubscribe from a currently subscribed manga."
    assert _param(delete, "manga_id").display_name == "manga"
    assert _param(delete, "manga_id").description == "The name of the manga."

    list_cmd = _subcommand(SubscriptionsCog.subscribe, "list")
    assert list_cmd.description == "List all the manga you're subscribed to."
    assert _param(list_cmd, "_global").display_name == "global"
    assert _param(list_cmd, "_global").description == (
        "Whether to show your subscriptions in all servers."
    )


def test_bookmark_metadata_matches_v1() -> None:
    assert BookmarksCog.bookmark.description == "Bookmark a manga"

    new = _subcommand(BookmarksCog.bookmark, "new")
    assert new.description == "Bookmark a new manga"
    assert _param(new, "manga_url_or_id").display_name == "manga_url"
    assert _param(new, "manga_url_or_id").description == (
        "The name of the bookmarked manga you want to view"
    )
    assert _param(new, "folder").description == (
        "The folder you want to view. If manga is specified, this is ignored."
    )

    view = _subcommand(BookmarksCog.bookmark, "view")
    assert view.description == "View your bookmark(s)"
    assert _param(view, "series").display_name == "manga"
    assert _param(view, "series").description == (
        "The name of the bookmarked manga you want to view"
    )

    update = _subcommand(BookmarksCog.bookmark, "update")
    assert update.description == "Update a bookmark"
    assert _param(update, "series").display_name == "manga"
    assert _param(update, "chapter_index").display_name == "chapter"
    assert _param(update, "series").description == (
        "The name of the bookmarked manga you want to update"
    )
    assert _param(update, "chapter_index").description == (
        "The chapter you want to update the bookmark to"
    )

    delete = _subcommand(BookmarksCog.bookmark, "delete")
    assert delete.description == "Delete a bookmark"
    assert _param(delete, "series").display_name == "manga"
    assert _param(delete, "series").description == (
        "The name of the bookmarked manga you want to delete"
    )


def test_catalog_general_and_settings_metadata_match_v1() -> None:
    assert CatalogCog.search.description == (
        "Search for a manga on on all/one scanlator of choice."
    )
    assert _param(CatalogCog.search, "query").description == "The name of the manga."
    assert _param(CatalogCog.search, "scanlator_website").display_name == "scanlator"
    assert _param(CatalogCog.search, "scanlator_website").description == (
        "The website to search on."
    )

    assert CatalogCog.info.description == "Display info about a manhwa."
    assert _param(CatalogCog.info, "series").display_name == "manhwa"
    assert _param(CatalogCog.info, "series").description == (
        "The name of the manhwa you want to get info for."
    )

    assert CatalogCog.chapters.description == "Get a list of chapters for a manga."
    assert _param(CatalogCog.chapters, "series").display_name == "manga"
    assert _param(CatalogCog.chapters, "series").description == "The name of the manga."

    assert CatalogCog.supported_websites.description == "Get a list of supported websites."

    assert GeneralCog.stats.description == "Get some basic info and stats about the bot."
    assert GeneralCog.translate.description == "Translate any text from one language to another"
    assert _param(GeneralCog.translate, "from_").display_name == "from"
    assert _param(GeneralCog.translate, "from_").description == ("The language to translate from")
    assert _param(GeneralCog.translate, "to").description == "The language to translate to"
    assert GeneralCog.patreon.description == (
        "Help fund the server and manage your current patreon subscription"
    )
    assert GeneralCog.next_update_check.description == "Get the time of the next update check."
    assert _param(GeneralCog.next_update_check, "show_all").description == (
        "Whether to show the next update check for all scanlators supported by the bot."
    )

    assert SettingsCog.settings.description == "View and Edit the server/DM settings."
