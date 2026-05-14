"""Button rows stay inside their component containers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord

from manhwa_bot.config import DiscordPremiumConfig, PatreonPremiumConfig, PremiumConfig
from manhwa_bot.db.bookmarks import Bookmark
from manhwa_bot.db.guild_settings import GuildSettings
from manhwa_bot.ui.components import bookmark, confirm, help, series_info, settings, upgrade
from manhwa_bot.ui.components.base import BaseLayoutView
from manhwa_bot.ui.components.paginator import LayoutPaginator


def _top_level_button_rows(view: discord.ui.LayoutView) -> list[discord.ui.ActionRow]:
    return [
        item
        for item in view.children
        if isinstance(item, discord.ui.ActionRow)
        and any(isinstance(child, discord.ui.Button) for child in item.children)
    ]


def _assert_buttons_are_nested(view: discord.ui.LayoutView) -> None:
    assert _top_level_button_rows(view) == []


def _button_row() -> discord.ui.ActionRow:
    row = discord.ui.ActionRow()
    row.add_item(discord.ui.Button(label="Open", style=discord.ButtonStyle.blurple))
    return row


def test_static_component_buttons_are_nested_inside_containers() -> None:
    premium_config = PremiumConfig(
        enabled=True,
        owner_bypass=False,
        log_decisions=False,
        patreon=PatreonPremiumConfig(
            enabled=True,
            campaign_id=1,
            poll_interval_seconds=60,
            freshness_seconds=300,
            required_tier_ids=(),
            pledge_url="https://example.test/patreon",
            access_token="",
        ),
        discord=DiscordPremiumConfig(
            enabled=True,
            user_sku_ids=(123,),
            guild_sku_ids=(),
            upgrade_url="https://example.test/upgrade",
        ),
    )

    views = [
        confirm.ConfirmLayoutView(author_id=1, prompt="Continue?"),
        help.build_help_view(bot=None, support_url="https://example.test/support"),
        help.build_patreon_view(bot=None),
        upgrade.build_upgrade_view(premium_config),
        series_info.build_info_view(
            {"title": "Series", "website_key": "site"},
            action_row=series_info.SeriesActionRow(website_key="site", url_name="series"),
        ),
        series_info.build_search_result_view(
            {"title": "Series", "website_key": "site"},
            page=1,
            total_pages=1,
            action_row=series_info.SeriesActionRow(website_key="site", url_name="series"),
        ),
        bookmark.build_bookmark_detail_view(
            title="Series",
            series_url="https://example.test/series",
            website_key="site",
            cover_url=None,
            scanlator_base_url=None,
            last_read_chapter="1",
            next_chapter=None,
            folder="Reading",
            available_chapters_label="1",
            chapter_count=1,
            status="Ongoing",
            is_completed=False,
            extra_action_row=_button_row(),
        ),
    ]

    for view in views:
        _assert_buttons_are_nested(view)


def test_interactive_component_buttons_are_nested_inside_containers() -> None:
    fake_bot = SimpleNamespace(db=None)
    guild_settings = GuildSettings(
        guild_id=1,
        notifications_channel_id=None,
        default_ping_role_id=None,
        auto_create_role=True,
        show_update_buttons=True,
        system_alerts_channel_id=None,
        bot_manager_role_id=None,
        paid_chapter_notifs=True,
        updated_at="2026-05-14T00:00:00",
    )

    dm_settings = settings.DmSettingsLayoutView(fake_bot, 1)
    dm_settings._rebuild()

    views = [
        settings.SettingsLayoutView(fake_bot, 1, guild_settings, []),
        settings.ScanlatorChannelsLayoutView(
            fake_bot,
            1,
            [{"website_key": "site", "channel_id": 2}],
            parent=settings.SettingsLayoutView(fake_bot, 1, guild_settings, []),
        ),
        settings.ScanlatorAddLayoutView(
            fake_bot,
            1,
            ["site"],
            parent=settings.ScanlatorChannelsLayoutView(
                fake_bot,
                1,
                [],
                parent=settings.SettingsLayoutView(fake_bot, 1, guild_settings, []),
            ),
        ),
        dm_settings,
    ]

    for view in views:
        _assert_buttons_are_nested(view)


def test_bookmark_browser_buttons_are_nested_inside_container() -> None:
    class FakeTrackedStore:
        async def find(self, website_key: str, url_name: str) -> None:
            return None

    browser = bookmark.BookmarkBrowserView(
        [
            Bookmark(
                user_id=1,
                website_key="site",
                url_name="series",
                folder="Reading",
                last_read_chapter="1",
                last_read_index=0,
                created_at="2026-05-14T00:00:00",
                updated_at="2026-05-14T00:00:00",
            )
        ],
        store=SimpleNamespace(),
        tracked=FakeTrackedStore(),
        crawler=SimpleNamespace(),
        invoker_id=1,
    )

    asyncio.run(browser.initial_render())

    _assert_buttons_are_nested(browser)


def test_paginator_buttons_are_nested_inside_page_containers() -> None:
    pages: list[discord.ui.LayoutView] = []
    for index in range(2):
        view = BaseLayoutView(invoker_id=1)
        view.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(f"Page {index + 1}"),
                accent_colour=discord.Colour.blurple(),
            )
        )
        pages.append(view)

    paginator = LayoutPaginator(pages, invoker_id=1)

    for page in paginator._pages:
        _assert_buttons_are_nested(page)
