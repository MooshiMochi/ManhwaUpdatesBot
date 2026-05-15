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

        async def list_guilds_tracking(self, website_key: str, url_name: str) -> list:
            return []

    class FakeSubscriptionStore:
        async def is_subscribed(self, *_args, **_kwargs) -> bool:
            return False

        async def subscribe(self, *_args, **_kwargs) -> None:
            return None

        async def unsubscribe(self, *_args, **_kwargs) -> None:
            return None

    class FakeGuildSettingsStore:
        async def list_scanlator_channels(self, _guild_id: int) -> list:
            return []

        async def get(self, _guild_id: int):
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
        subscriptions=FakeSubscriptionStore(),
        guild_settings=FakeGuildSettingsStore(),
        crawler=SimpleNamespace(),
        invoker_id=1,
    )

    asyncio.run(browser.initial_render())

    _assert_buttons_are_nested(browser)


def _first_container(view: discord.ui.LayoutView) -> discord.ui.Container:
    return next(item for item in view.children if isinstance(item, discord.ui.Container))


def _action_rows(container: discord.ui.Container) -> list[discord.ui.ActionRow]:
    return [item for item in container.children if isinstance(item, discord.ui.ActionRow)]


def _dispatchable_controls(view: discord.ui.LayoutView) -> dict[str, str]:
    controls: dict[str, str] = {}
    for item in view.walk_children():
        custom_id = getattr(item, "custom_id", None)
        if not custom_id:
            continue
        label = getattr(item, "label", None)
        placeholder = getattr(item, "placeholder", None)
        key = str(label or placeholder or item.__class__.__name__)
        controls[key] = str(custom_id)
    return controls


class _FakeBookmarkCrawler:
    async def request(self, type_: str, **_kwargs):
        if type_ == "chapters":
            return {
                "chapters": [
                    {"name": "Chapter 1", "url": "https://example.test/1"},
                    {"name": "Chapter 2", "url": "https://example.test/2"},
                    {"name": "Chapter 3", "url": "https://example.test/3"},
                ]
            }
        if type_ == "supported_websites":
            return {"websites": [{"key": "site", "name": "Site", "base_url": "https://site.test"}]}
        return {}


def _bookmark_browser(bookmarks: list[Bookmark]) -> bookmark.BookmarkBrowserView:
    class FakeTrackedStore:
        async def find(self, website_key: str, url_name: str) -> None:
            return None

        async def list_guilds_tracking(self, website_key: str, url_name: str) -> list:
            return []

    class FakeSubscriptionStore:
        async def is_subscribed(self, *_args, **_kwargs) -> bool:
            return False

    class FakeGuildSettingsStore:
        async def list_scanlator_channels(self, _guild_id: int) -> list:
            return []

        async def get(self, _guild_id: int):
            return None

    return bookmark.BookmarkBrowserView(
        bookmarks,
        store=SimpleNamespace(),
        tracked=FakeTrackedStore(),
        subscriptions=FakeSubscriptionStore(),
        guild_settings=FakeGuildSettingsStore(),
        crawler=_FakeBookmarkCrawler(),
        invoker_id=1,
    )


class _Role:
    def __init__(self, role_id: int) -> None:
        self.id = role_id


class _Permissions:
    def __init__(self, *, read_messages: bool = True, manage_roles: bool = False) -> None:
        self.read_messages = read_messages
        self.manage_roles = manage_roles
        self.manage_guild = False


class _Member:
    def __init__(self, *, roles: list[_Role], manage_roles: bool = False) -> None:
        self.roles = roles
        self.guild_permissions = _Permissions(manage_roles=manage_roles)


class _Channel:
    id = 55
    name = "updates"

    def permissions_for(self, _member: _Member) -> _Permissions:
        return _Permissions(read_messages=True)


class _Guild:
    def __init__(self, member: _Member) -> None:
        self.id = 99
        self.name = "Guild"
        self._member = member
        self._channel = _Channel()

    def get_member(self, user_id: int) -> _Member | None:
        return self._member if user_id == 1 else None

    def get_channel(self, channel_id: int) -> _Channel | None:
        return self._channel if channel_id == self._channel.id else None


class _Bot:
    def __init__(self, guild: _Guild) -> None:
        self._guild = guild

    def get_guild(self, guild_id: int) -> _Guild | None:
        return self._guild if guild_id == self._guild.id else None

    def get_channel(self, channel_id: int) -> _Channel | None:
        return self._guild.get_channel(channel_id)


class _TrackButtonGuildSettingsStore:
    def __init__(self, *, bot_manager_role_id: int | None) -> None:
        self._bot_manager_role_id = bot_manager_role_id

    async def list_scanlator_channels(self, _guild_id: int) -> list:
        return [{"website_key": "site", "channel_id": 55}]

    async def get(self, _guild_id: int):
        return SimpleNamespace(
            notifications_channel_id=55,
            bot_manager_role_id=self._bot_manager_role_id,
        )


class _UntrackedStore:
    async def find(self, website_key: str, url_name: str) -> None:
        return None

    async def list_guilds_tracking(self, website_key: str, url_name: str) -> list:
        return []


def _bookmark_browser_with_tracking_context(
    *,
    member: _Member,
    bot_manager_role_id: int | None,
) -> bookmark.BookmarkBrowserView:
    guild = _Guild(member)
    return bookmark.BookmarkBrowserView(
        [
            Bookmark(
                user_id=1,
                website_key="site",
                url_name="series",
                folder="Reading",
                last_read_chapter="Chapter 2",
                last_read_index=1,
                created_at="2026-05-14T00:00:00",
                updated_at="2026-05-14T00:00:00",
            )
        ],
        store=SimpleNamespace(),
        tracked=_UntrackedStore(),
        subscriptions=SimpleNamespace(),
        guild_settings=_TrackButtonGuildSettingsStore(bot_manager_role_id=bot_manager_role_id),
        crawler=_FakeBookmarkCrawler(),
        invoker_id=1,
        guild_id=guild.id,
        bot=_Bot(guild),
    )


def test_bookmark_browser_track_button_enabled_for_bot_manager_role() -> None:
    browser = _bookmark_browser_with_tracking_context(
        member=_Member(roles=[_Role(123)]),
        bot_manager_role_id=123,
    )

    asyncio.run(browser.initial_render())

    container = _first_container(browser)
    action_row = next(
        row
        for row in _action_rows(container)
        if any(
            isinstance(child, discord.ui.Button) and child.label == "Track"
            for child in row.children
        )
    )
    labels = [child.label for child in action_row.children]
    assert labels == ["Text mode", "Delete bookmark", "Track"]
    track_button = next(child for child in action_row.children if child.label == "Track")
    assert track_button.disabled is False


def test_bookmark_browser_track_button_disabled_without_permission_or_manager_role() -> None:
    browser = _bookmark_browser_with_tracking_context(
        member=_Member(roles=[]),
        bot_manager_role_id=123,
    )

    asyncio.run(browser.initial_render())

    container = _first_container(browser)
    track_button = next(
        child
        for row in _action_rows(container)
        for child in row.children
        if isinstance(child, discord.ui.Button) and child.label == "Track"
    )
    assert track_button.disabled is True


def test_bookmark_browser_rebuild_keeps_dispatch_custom_ids_stable() -> None:
    browser = _bookmark_browser_with_tracking_context(
        member=_Member(roles=[_Role(123)]),
        bot_manager_role_id=123,
    )

    async def run() -> None:
        await browser.initial_render()
        before = _dispatchable_controls(browser)
        await browser._rebuild()
        after = _dispatchable_controls(browser)

        assert after["Track"] == before["Track"]
        assert after[">"] == before[">"]
        assert after["Browsing folder: All folders"] == before["Browsing folder: All folders"]
        assert after["Move bookmark: Reading"] == before["Move bookmark: Reading"]

    asyncio.run(run())


def test_bookmark_browser_navigation_defers_before_rebuild() -> None:
    browser = _bookmark_browser(
        [
            Bookmark(
                user_id=1,
                website_key="site",
                url_name=f"series-{i}",
                folder="Reading",
                last_read_chapter="Chapter 1",
                last_read_index=0,
                created_at="2026-05-14T00:00:00",
                updated_at=f"2026-05-14T00:00:{i:02d}",
            )
            for i in range(2)
        ]
    )

    async def run() -> None:
        await browser.initial_render()
        next_button = next(
            item
            for item in browser.walk_children()
            if isinstance(item, discord.ui.Button) and item.label == ">"
        )

        class Response:
            def __init__(self) -> None:
                self.deferred = False

            def is_done(self) -> bool:
                return self.deferred

            async def defer(self) -> None:
                self.deferred = True

            async def edit_message(self, **_kwargs) -> None:
                raise AssertionError("navigation must edit through edit_original_response")

        response = Response()

        async def edit_original_response(**kwargs) -> None:
            interaction.edits.append(kwargs)

        interaction = SimpleNamespace(
            response=response,
            edits=[],
            edit_original_response=edit_original_response,
        )

        async def rebuild() -> None:
            assert response.deferred is True
            await original_rebuild()

        original_rebuild = browser._rebuild
        browser._rebuild = rebuild  # type: ignore[method-assign]

        await next_button.callback(interaction)

        assert response.deferred is True
        assert interaction.edits == [{"view": browser}]

    asyncio.run(run())


def test_bookmark_browser_visual_controls_match_requested_layout() -> None:
    browser = _bookmark_browser(
        [
            Bookmark(
                user_id=1,
                website_key="site",
                url_name="series",
                folder="Reading",
                last_read_chapter="Chapter 2",
                last_read_index=1,
                created_at="2026-05-14T00:00:00",
                updated_at="2026-05-14T00:00:00",
            )
        ]
    )

    asyncio.run(browser.initial_render())

    container = _first_container(browser)
    rows = _action_rows(container)
    select_placeholders = [
        child.placeholder
        for row in rows
        for child in row.children
        if isinstance(child, discord.ui.Select)
    ]
    assert not any(
        placeholder and placeholder.startswith("Mark a specific chapter")
        for placeholder in select_placeholders
    )

    last_read_row = next(
        row
        for row in rows
        if any(
            isinstance(child, discord.ui.Button) and child.label == "Mark previous chapter as read"
            for child in row.children
        )
    )
    assert [child.label for child in last_read_row.children] == [
        "Mark previous chapter as read",
        "Chapter 2",
        "Mark next chapter as read",
    ]

    move_select = next(
        child
        for row in rows
        for child in row.children
        if isinstance(child, discord.ui.Select) and child.placeholder == "Move bookmark: Reading"
    )
    assert move_select.options[0].description == "Move this bookmark to Reading."

    pagination_index = next(
        i
        for i, item in enumerate(container.children)
        if isinstance(item, discord.ui.ActionRow)
        and [getattr(child, "label", None) for child in item.children]
        == ["<<", "<", "Page 1/1", ">", ">>"]
    )
    browse_folder_index = next(
        i
        for i, item in enumerate(container.children)
        if isinstance(item, discord.ui.ActionRow)
        and any(
            isinstance(child, discord.ui.Select)
            and child.placeholder == "Browsing folder: All folders"
            for child in item.children
        )
    )
    assert browse_folder_index > pagination_index


def test_bookmark_browser_text_paginator_clamps_and_uses_plain_labels() -> None:
    bookmarks = [
        Bookmark(
            user_id=1,
            website_key="site",
            url_name=f"series-{i}",
            folder="Reading",
            last_read_chapter="Chapter 1",
            last_read_index=0,
            created_at="2026-05-14T00:00:00",
            updated_at=f"2026-05-14T00:00:{i:02d}",
        )
        for i in range(12)
    ]
    browser = _bookmark_browser(bookmarks)

    async def run() -> None:
        await browser.initial_render()
        browser._mode = "text"
        await browser._rebuild()

        class Response:
            def __init__(self) -> None:
                self.deferred = False

            def is_done(self) -> bool:
                return self.deferred

            async def edit_message(self, **_kwargs) -> None:
                return None

            async def defer(self) -> None:
                self.deferred = True

        response = Response()

        async def edit_original_response(**_kwargs) -> None:
            return None

        interaction = SimpleNamespace(
            response=response,
            edit_original_response=edit_original_response,
        )

        container = _first_container(browser)
        pagination = next(
            row
            for row in _action_rows(container)
            if any(
                isinstance(child, discord.ui.Button) and child.label == "Page 1/2"
                for child in row.children
            )
        )
        assert [child.label for child in pagination.children] == ["<<", "<", "Page 1/2", ">", ">>"]

        next_button = next(child for child in pagination.children if child.label == ">")
        await next_button.callback(interaction)
        assert browser._index == 10

        container = _first_container(browser)
        pagination = next(
            row
            for row in _action_rows(container)
            if any(
                isinstance(child, discord.ui.Button) and child.label == "Page 2/2"
                for child in row.children
            )
        )
        next_button = next(child for child in pagination.children if child.label == ">")
        assert next_button.disabled is True

    asyncio.run(run())


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
