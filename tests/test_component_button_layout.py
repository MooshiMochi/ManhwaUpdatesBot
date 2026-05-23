"""Button rows stay inside their component containers."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import discord

from manhwa_bot.config import DiscordPremiumConfig, PatreonPremiumConfig, PremiumConfig
from manhwa_bot.db.bookmarks import Bookmark
from manhwa_bot.db.guild_settings import GuildSettings
from manhwa_bot.ui.components import (
    bookmark,
    chapter_list,
    confirm,
    dev,
    error,
    help,
    notifications,
    progress,
    series_info,
    settings,
    tracking,
    upgrade,
)
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


def _premium_config() -> PremiumConfig:
    return PremiumConfig(
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


def _containers(view: discord.ui.LayoutView) -> list[discord.ui.Container]:
    return [item for item in view.walk_children() if isinstance(item, discord.ui.Container)]


def _assert_containers_unaccented(view: discord.ui.LayoutView) -> None:
    containers = _containers(view)
    assert containers
    assert [container.accent_colour for container in containers] == [None] * len(containers)


def test_component_v2_headings_do_not_use_h1_markdown() -> None:
    components_dir = Path(__file__).parents[1] / "src" / "manhwa_bot" / "ui" / "components"
    offenders: list[str] = []
    for path in components_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith("# "):
                    offenders.append(f"{path.name}:{node.lineno}")
            elif isinstance(node, ast.JoinedStr):
                first = node.values[0] if node.values else None
                if (
                    isinstance(first, ast.Constant)
                    and isinstance(first.value, str)
                    and first.value.startswith("# ")
                ):
                    offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == []


def test_static_component_buttons_are_nested_inside_containers() -> None:
    premium_config = _premium_config()

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
        update_buttons=frozenset({"mark_read", "bookmark", "subscribe", "open_chapter"}),
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


def test_scanlator_remove_button_uses_layout_view_after_nesting() -> None:
    class FakeStore:
        def __init__(self) -> None:
            self.cleared: list[tuple[int, str]] = []

        async def clear_scanlator_channel(self, guild_id: int, website_key: str) -> None:
            self.cleared.append((guild_id, website_key))

        async def list_scanlator_channels(self, guild_id: int) -> list[dict]:
            assert guild_id == 1
            return []

    class FakeResponse:
        def __init__(self) -> None:
            self.view: discord.ui.LayoutView | None = None

        async def edit_message(self, *, view: discord.ui.LayoutView) -> None:
            self.view = view

    fake_bot = SimpleNamespace(db=None)
    guild_settings = GuildSettings(
        guild_id=1,
        notifications_channel_id=None,
        default_ping_role_id=None,
        auto_create_role=True,
        update_buttons=frozenset({"mark_read", "bookmark", "subscribe", "open_chapter"}),
        system_alerts_channel_id=None,
        bot_manager_role_id=None,
        paid_chapter_notifs=True,
        updated_at="2026-05-14T00:00:00",
    )
    parent = settings.SettingsLayoutView(fake_bot, 1, guild_settings, [])
    view = settings.ScanlatorChannelsLayoutView(
        fake_bot,
        1,
        [{"website_key": "site", "channel_id": 2}],
        parent=parent,
    )
    fake_store = FakeStore()
    view._store = fake_store

    remove_button = next(
        child
        for child in view.walk_children()
        if isinstance(child, discord.ui.Button) and child.label == "✕ site"
    )
    response = FakeResponse()
    interaction = SimpleNamespace(response=response)

    asyncio.run(remove_button.callback(interaction))

    assert fake_store.cleared == [(1, "site")]
    assert view._overrides == []
    assert response.view is view


def test_neutral_component_v2_containers_do_not_set_accent_colour() -> None:
    fake_bot = SimpleNamespace(db=None)
    guild_settings = GuildSettings(
        guild_id=1,
        notifications_channel_id=None,
        default_ping_role_id=None,
        auto_create_role=True,
        update_buttons=frozenset({"mark_read", "bookmark", "subscribe", "open_chapter"}),
        system_alerts_channel_id=None,
        bot_manager_role_id=None,
        paid_chapter_notifs=True,
        updated_at="2026-05-14T00:00:00",
    )
    state = progress.ProgressLayoutState("crawl", "req-1", bot=None)
    state.add("Retrying upstream.", "warning")
    dm_settings = settings.DmSettingsLayoutView(fake_bot, 1)
    dm_settings._rebuild()

    views = [
        confirm.ConfirmLayoutView(author_id=1, prompt="Continue?"),
        dev.build_diagnostic_view(title="Output", body="ok"),
        dev.build_diagnostic_view(title="Output", body="ok", accent=discord.Colour.blurple()),
        dev.build_diagnostic_pages("ok", title="Output")[0],
        dev.build_premium_list_views(
            [
                SimpleNamespace(
                    id=1,
                    scope="user",
                    target_id=2,
                    expires_at=None,
                    revoked_at=None,
                    reason="test",
                )
            ],
            bot=None,
        )[0],
        help.build_help_view(bot=None, support_url="https://example.test/support"),
        help.build_stats_view(
            bookmarks_count=1,
            tracks_count=2,
            subs_count=3,
            manhwa_count=4,
            websites_count=5,
            guilds_count=6,
            users_count=7,
            start_unix=1,
            bot_created_unix=1,
            bot=None,
        ),
        help.build_patreon_view(bot=None),
        help.build_next_update_check_views([("site", None)], bot=None)[0],
        help.build_translation_view(text="hola", translated="hello", lang_from="es", lang_to="en"),
        help.build_lost_manga_view(entries_count=1, lost_websites=1),
        chapter_list.build_chapter_list_views([], manga_title="Series", manga_url=None, bot=None)[
            0
        ],
        chapter_list.build_chapter_list_views(
            [{"name": "1", "url": "https://example.test/ch/1"}],
            manga_title="Series",
            manga_url=None,
            bot=None,
        )[0],
        chapter_list.build_supported_websites_views(
            [{"key": "site", "name": "Site", "base_url": "https://example.test"}],
            bot=None,
        )[0],
        notifications.build_chapter_update_view(
            {
                "series_title": "Series",
                "chapter": {"name": "1", "url": "https://example.test/ch/1"},
            }
        ),
        series_info.build_info_view({"title": "Series", "website_key": "site"}),
        series_info.build_search_result_view(
            {"title": "Series", "website_key": "site"},
            page=1,
            total_pages=1,
        ),
        settings.SettingsLayoutView(fake_bot, 1, guild_settings, []),
        settings.ScanlatorChannelsLayoutView(
            fake_bot, 1, [], parent=settings.SettingsLayoutView(fake_bot, 1, guild_settings, [])
        ),
        settings.ScanlatorAddLayoutView(
            fake_bot,
            1,
            ["site"],
            parent=settings.ScanlatorChannelsLayoutView(
                fake_bot, 1, [], parent=settings.SettingsLayoutView(fake_bot, 1, guild_settings, [])
            ),
        ),
        dm_settings,
        tracking.build_grouped_list_views(
            [{"title": "Series", "url": "https://example.test/series", "website_key": "site"}],
            title="Tracked Manhwa",
            bot=None,
        )[0],
        tracking.build_grouped_list_views([], title="Tracked Manhwa", bot=None)[0],
        tracking.build_simple_status_view(
            title="Operation cancelled",
            description="No changes were made.",
            accent=discord.Colour.greyple(),
        ),
        upgrade.build_upgrade_view(_premium_config()),
        state.to_view(),
    ]

    for view in views:
        _assert_containers_unaccented(view)


def test_error_and_success_component_v2_containers_keep_accent_colour() -> None:
    views = [
        error.build_error_view("Nope"),
        error.build_success_view(title="Saved", description="Settings saved."),
        tracking.build_tracking_success_view(
            title="Series",
            series_url="https://example.test/series",
            ping_role=None,
            notif_channel=None,
            cover_url=None,
            is_dm=False,
        ),
        tracking.build_role_managed_view(),
        help.build_no_lost_manga_view(),
    ]

    for view in views:
        accents = [container.accent_colour for container in _containers(view)]
        assert accents
        assert all(accent is not None for accent in accents)


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


def _button(view: discord.ui.LayoutView, label: str) -> discord.ui.Button:
    return next(
        item
        for item in view.walk_children()
        if isinstance(item, discord.ui.Button) and item.label == label
    )


class _EditInteraction:
    def __init__(self) -> None:
        self.edits: list[dict] = []

        class Response:
            def __init__(self) -> None:
                self.deferred = False

            def is_done(self) -> bool:
                return self.deferred

            async def defer(self) -> None:
                self.deferred = True

        self.response = Response()

    async def edit_original_response(self, **kwargs) -> None:
        self.edits.append(kwargs)


class _DeletingBookmarkStore:
    def __init__(self) -> None:
        self.deleted: list[tuple[int, str, str]] = []

    async def delete_bookmark(self, user_id: int, website_key: str, url_name: str) -> None:
        self.deleted.append((user_id, website_key, url_name))


class _FakeBookmarkCrawler:
    async def request(self, type_: str, **kwargs):
        if type_ == "series_data":
            slug = str(kwargs.get("url_name") or kwargs.get("url") or "series")
            return {
                "website_key": kwargs.get("website_key") or "site",
                "url_name": slug,
                "url": f"https://site.test/series/{slug}",
                "title": slug.replace("-", " ").title(),
                "cover_url": None,
                "status": "Ongoing",
                "chapters": [
                    {"name": "Chapter 1", "url": "https://example.test/1"},
                    {"name": "Chapter 2", "url": "https://example.test/2"},
                    {"name": "Chapter 3", "url": "https://example.test/3"},
                ],
                "website": {"key": "site", "name": "Site", "base_url": "https://site.test"},
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


def _bookmark_browser_with_store(
    bookmarks: list[Bookmark],
    store: _DeletingBookmarkStore,
) -> bookmark.BookmarkBrowserView:
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
        store=store,
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


class _CountingBookmarkCrawler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def request(self, type_: str, **kwargs):
        self.calls.append((type_, str(kwargs.get("url_name") or kwargs.get("url") or "")))
        if type_ == "series_data":
            slug = str(kwargs.get("url_name") or kwargs.get("url") or "series")
            return {
                "website_key": kwargs.get("website_key") or "site",
                "url_name": slug,
                "url": f"https://site.test/series/{slug}",
                "title": slug.replace("-", " ").title(),
                "cover_url": None,
                "status": "Ongoing",
                "chapters": [
                    {"name": f"{slug} Chapter 1", "url": f"https://example.test/{slug}/1"},
                    {"name": f"{slug} Chapter 2", "url": f"https://example.test/{slug}/2"},
                ],
                "website": {"key": "site", "name": "Site", "base_url": "https://site.test"},
            }
        if type_ == "supported_websites":
            return {"websites": [{"key": "site", "name": "Site", "base_url": "https://site.test"}]}
        return {}


class _SeriesDataBookmarkCrawler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def request(self, type_: str, **kwargs):
        self.calls.append((type_, dict(kwargs)))
        if type_ == "series_data":
            slug = str(kwargs.get("url_name") or kwargs.get("url") or "series")
            return {
                "website_key": kwargs.get("website_key") or "site",
                "url_name": slug,
                "url": f"https://site.test/series/{slug}",
                "title": slug.replace("-", " ").title(),
                "cover_url": None,
                "status": "Ongoing",
                "synopsis": None,
                "chapter_count": 2,
                "chapters": [
                    {"name": f"{slug} Chapter 1", "url": f"https://site.test/{slug}/1"},
                    {"name": f"{slug} Chapter 2", "url": f"https://site.test/{slug}/2"},
                ],
                "latest_chapters": [
                    {"name": f"{slug} Chapter 2", "url": f"https://site.test/{slug}/2"}
                ],
                "website": {"key": "site", "name": "Site", "base_url": "https://site.test"},
                "source": "db",
            }
        raise AssertionError(f"unexpected crawler request: {type_}")


class _BlockingSeriesDataCrawler:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def request(self, type_: str, **kwargs):
        if type_ != "series_data":
            return {}
        if kwargs.get("url_name") == "series-1":
            self.started.set()
            await self.release.wait()
        slug = str(kwargs.get("url_name") or "series")
        return {
            "website_key": kwargs.get("website_key") or "site",
            "url_name": slug,
            "url": f"https://site.test/series/{slug}",
            "title": slug.replace("-", " ").title(),
            "cover_url": None,
            "status": "Ongoing",
            "chapters": [
                {"name": f"{slug} Chapter 1", "url": f"https://site.test/{slug}/1"},
            ],
            "website": {"key": "site", "name": "Site", "base_url": "https://site.test"},
        }


class _CountingTrackedStore:
    def __init__(self) -> None:
        self.find_calls: list[tuple[str, str]] = []
        self.guild_calls: list[tuple[str, str]] = []

    async def find(self, website_key: str, url_name: str) -> None:
        self.find_calls.append((website_key, url_name))
        return None

    async def list_guilds_tracking(self, website_key: str, url_name: str) -> list:
        self.guild_calls.append((website_key, url_name))
        return []


class _NoopSubscriptionStore:
    async def is_subscribed(self, *_args, **_kwargs) -> bool:
        return False


class _NoopGuildSettingsStore:
    async def list_scanlator_channels(self, _guild_id: int) -> list:
        return []

    async def get(self, _guild_id: int):
        return None


def _bookmark_series(count: int) -> list[Bookmark]:
    return [
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
        for i in range(count)
    ]


def _cached_series_names(browser: bookmark.BookmarkBrowserView) -> list[str]:
    return sorted(
        (key[1] for key in browser._series_data_cache),
        key=lambda value: int(value.rsplit("-", 1)[1]),
    )


def test_bookmark_browser_initial_render_warms_adjacent_bookmark_data() -> None:
    crawler = _CountingBookmarkCrawler()
    tracked = _CountingTrackedStore()
    browser = bookmark.BookmarkBrowserView(
        _bookmark_series(3),
        store=SimpleNamespace(),
        tracked=tracked,
        subscriptions=_NoopSubscriptionStore(),
        guild_settings=_NoopGuildSettingsStore(),
        crawler=crawler,
        invoker_id=1,
    )

    async def run() -> None:
        await browser.initial_render()
        assert browser._preload_task is not None
        await browser._preload_task

    asyncio.run(run())

    assert ("site", "series-0") in browser._chapter_cache
    assert ("site", "series-1") in browser._chapter_cache
    assert ("site", "series-0") in browser._tracking_cache
    assert ("site", "series-1") in browser._tracking_cache


def test_bookmark_browser_timeout_keeps_pagination_registered_longer_than_default_view() -> None:
    browser = _bookmark_browser(_bookmark_series(2))

    assert browser.timeout == 2 * 24 * 60 * 60


def test_bookmark_browser_keeps_existing_controls_while_rebuild_waits_for_data() -> None:
    browser = _bookmark_browser(_bookmark_series(2))

    async def run() -> dict[str, str]:
        await browser._rebuild()
        browser._index = 1
        browser._crawler = _BlockingSeriesDataCrawler()
        browser._meta.pop(("site", "series-1"), None)
        browser._series_data_cache.pop(("site", "series-1"), None)
        browser._chapter_cache.pop(("site", "series-1"), None)

        task = asyncio.create_task(browser._rebuild())
        await browser._crawler.started.wait()
        controls = _dispatchable_controls(browser)
        browser._crawler.release.set()
        await task
        return controls

    controls = asyncio.run(run())

    assert ">" in controls
    assert "<" in controls
    assert "Browsing folder: All folders" in controls


def test_bookmark_browser_initial_preload_is_limited_to_ten_around_requested() -> None:
    crawler = _SeriesDataBookmarkCrawler()
    browser = bookmark.BookmarkBrowserView(
        _bookmark_series(30),
        store=SimpleNamespace(),
        tracked=_CountingTrackedStore(),
        subscriptions=_NoopSubscriptionStore(),
        guild_settings=_NoopGuildSettingsStore(),
        crawler=crawler,
        invoker_id=1,
        index=12,
    )

    async def run() -> None:
        await browser.initial_render()
        assert browser._preload_task is not None
        await browser._preload_task

    asyncio.run(run())

    assert _cached_series_names(browser) == [f"series-{i}" for i in range(7, 17)]


def test_bookmark_browser_preloads_next_ten_when_near_window_edge() -> None:
    crawler = _SeriesDataBookmarkCrawler()
    browser = bookmark.BookmarkBrowserView(
        _bookmark_series(30),
        store=SimpleNamespace(),
        tracked=_CountingTrackedStore(),
        subscriptions=_NoopSubscriptionStore(),
        guild_settings=_NoopGuildSettingsStore(),
        crawler=crawler,
        invoker_id=1,
        index=0,
    )

    async def run() -> None:
        await browser.initial_render()
        assert browser._preload_task is not None
        await browser._preload_task
        browser._index = 7
        browser._schedule_preload()
        assert browser._preload_task is not None
        await browser._preload_task

    asyncio.run(run())

    assert _cached_series_names(browser) == [f"series-{i}" for i in range(20)]


def test_bookmark_browser_preloads_previous_ten_when_near_window_edge() -> None:
    crawler = _SeriesDataBookmarkCrawler()
    browser = bookmark.BookmarkBrowserView(
        _bookmark_series(30),
        store=SimpleNamespace(),
        tracked=_CountingTrackedStore(),
        subscriptions=_NoopSubscriptionStore(),
        guild_settings=_NoopGuildSettingsStore(),
        crawler=crawler,
        invoker_id=1,
        index=20,
    )

    async def run() -> None:
        await browser.initial_render()
        assert browser._preload_task is not None
        await browser._preload_task
        browser._index = 17
        browser._schedule_preload()
        assert browser._preload_task is not None
        await browser._preload_task

    asyncio.run(run())

    assert _cached_series_names(browser) == [f"series-{i}" for i in range(5, 25)]


def test_bookmark_browser_uses_cache_only_series_data_for_preload() -> None:
    crawler = _SeriesDataBookmarkCrawler()
    browser = bookmark.BookmarkBrowserView(
        _bookmark_series(3),
        store=SimpleNamespace(),
        tracked=_CountingTrackedStore(),
        subscriptions=_NoopSubscriptionStore(),
        guild_settings=_NoopGuildSettingsStore(),
        crawler=crawler,
        invoker_id=1,
    )

    async def run() -> None:
        await browser.initial_render()
        assert browser._preload_task is not None
        await browser._preload_task

    asyncio.run(run())

    assert {call[0] for call in crawler.calls} == {"series_data"}
    assert all(call[1]["allow_live"] is False for call in crawler.calls)
    assert [call[1]["url_name"] for call in crawler.calls[:2]] == ["series-0", "series-1"]


def test_bookmark_browser_navigation_to_warmed_bookmark_uses_cache() -> None:
    crawler = _CountingBookmarkCrawler()
    tracked = _CountingTrackedStore()
    browser = bookmark.BookmarkBrowserView(
        _bookmark_series(3),
        store=SimpleNamespace(),
        tracked=tracked,
        subscriptions=_NoopSubscriptionStore(),
        guild_settings=_NoopGuildSettingsStore(),
        crawler=crawler,
        invoker_id=1,
    )

    async def run() -> tuple[int, int, int]:
        await browser.initial_render()
        assert browser._preload_task is not None
        await browser._preload_task
        before = (len(crawler.calls), len(tracked.find_calls), len(tracked.guild_calls))

        class Response:
            def __init__(self) -> None:
                self.deferred = False

            def is_done(self) -> bool:
                return self.deferred

            async def defer(self) -> None:
                self.deferred = True

        async def edit_original_response(**_kwargs) -> None:
            return None

        interaction = SimpleNamespace(
            response=Response(),
            edit_original_response=edit_original_response,
        )
        next_button = next(
            item
            for item in browser.walk_children()
            if isinstance(item, discord.ui.Button) and item.label == ">"
        )
        await next_button.callback(interaction)
        return (
            len(crawler.calls) - before[0],
            len(tracked.find_calls) - before[1],
            len(tracked.guild_calls) - before[2],
        )

    deltas = asyncio.run(run())

    assert deltas == (0, 0, 0)


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


def test_bookmark_browser_delete_button_asks_for_confirmation_first() -> None:
    store = _DeletingBookmarkStore()
    browser = _bookmark_browser_with_store(_bookmark_series(2), store)

    async def run() -> _EditInteraction:
        await browser.initial_render()
        interaction = _EditInteraction()
        await _button(browser, "Delete bookmark").callback(interaction)
        return interaction

    interaction = asyncio.run(run())

    assert store.deleted == []
    assert interaction.response.deferred is True
    assert interaction.edits == [{"view": browser}]
    assert "Confirm delete" in _dispatchable_controls(browser)
    assert "Cancel" in _dispatchable_controls(browser)


def test_bookmark_browser_delete_cancel_returns_to_normal_controls() -> None:
    store = _DeletingBookmarkStore()
    browser = _bookmark_browser_with_store(_bookmark_series(2), store)

    async def run() -> None:
        await browser.initial_render()
        await _button(browser, "Delete bookmark").callback(_EditInteraction())
        await _button(browser, "Cancel").callback(_EditInteraction())

    asyncio.run(run())

    assert store.deleted == []
    controls = _dispatchable_controls(browser)
    assert "Delete bookmark" in controls
    assert "Confirm delete" not in controls


def test_bookmark_browser_delete_confirm_deletes_current_bookmark() -> None:
    store = _DeletingBookmarkStore()
    browser = _bookmark_browser_with_store(_bookmark_series(2), store)

    async def run() -> _EditInteraction:
        await browser.initial_render()
        await _button(browser, "Delete bookmark").callback(_EditInteraction())
        interaction = _EditInteraction()
        await _button(browser, "Confirm delete").callback(interaction)
        return interaction

    interaction = asyncio.run(run())

    assert store.deleted == [(1, "site", "series-0")]
    assert [bm.url_name for bm in browser._all] == ["series-1"]
    assert [bm.url_name for bm in browser._filtered] == ["series-1"]
    assert browser._index == 0
    assert interaction.edits == [{"view": browser}]
    assert "Delete bookmark" in _dispatchable_controls(browser)


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
