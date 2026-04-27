"""UpdatesCog.dispatch fan-out tests with real DB stores + mocked Discord I/O."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from manhwa_bot.cogs.updates import UpdatesCog
from manhwa_bot.config import (
    AppConfig,
    BotConfig,
    CrawlerConfig,
    DbConfig,
    DiscordPremiumConfig,
    NotificationsConfig,
    PatreonPremiumConfig,
    PremiumConfig,
    SupportedWebsitesCacheConfig,
)
from manhwa_bot.db.dm_settings import DmSettings, DmSettingsStore
from manhwa_bot.db.guild_settings import GuildSettings, GuildSettingsStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.subscriptions import SubscriptionStore
from manhwa_bot.db.tracked import TrackedStore


def _build_config(*, respect_paid_chapter: bool = True) -> AppConfig:
    return AppConfig(
        bot=BotConfig(
            owner_ids=(),
            log_level="INFO",
            dev_guild_id=0,
            command_prefix="?",
        ),
        crawler=CrawlerConfig(
            ws_url="ws://unused",
            http_base_url="http://unused",
            request_timeout_seconds=5.0,
            reconnect_initial_delay_seconds=0.1,
            reconnect_max_delay_seconds=1.0,
            reconnect_jitter_seconds=0.0,
            consumer_key="test",
            api_key="test",
        ),
        db=DbConfig(path=":memory:"),
        premium=PremiumConfig(
            enabled=False,
            owner_bypass=True,
            log_decisions=False,
            discord=DiscordPremiumConfig(
                enabled=False, user_sku_ids=(), guild_sku_ids=(), upgrade_url=""
            ),
            patreon=PatreonPremiumConfig(
                enabled=False,
                campaign_id=0,
                poll_interval_seconds=600,
                freshness_seconds=1800,
                required_tier_ids=(),
                pledge_url="",
                access_token="",
            ),
        ),
        notifications=NotificationsConfig(
            fanout_concurrency=8,
            dm_fanout_concurrency=4,
            respect_paid_chapter_setting=respect_paid_chapter,
        ),
        supported_websites_cache=SupportedWebsitesCacheConfig(ttl_seconds=3600),
        discord_bot_token="test",
    )


@dataclass
class _BotStub:
    db: DbPool
    config: AppConfig
    crawler: object  # unused in dispatch path
    get_channel: MagicMock
    fetch_user: AsyncMock


def _payload(*, website_key: str = "comick", url_name: str = "demo", premium: bool = False) -> dict:
    return {
        "id": 1,
        "website_key": website_key,
        "url_name": url_name,
        "chapter_index": 1,
        "payload": {
            "event": "new_chapter",
            "website_key": website_key,
            "url_name": url_name,
            "series_title": "Demo",
            "series_url": f"https://example.com/{url_name}",
            "chapter": {
                "index": 1,
                "name": "Chapter 1",
                "url": f"https://example.com/{url_name}/1",
                "is_premium": premium,
            },
        },
        "created_at": "2026-04-26T00:00:00+00:00",
    }


async def _setup() -> tuple[_BotStub, UpdatesCog, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    pool = await DbPool.open(str(Path(tmp.name) / "bot.db"))
    await apply_pending(pool)
    bot = _BotStub(
        db=pool,
        config=_build_config(),
        crawler=SimpleNamespace(),
        get_channel=MagicMock(),
        fetch_user=AsyncMock(),
    )
    cog = UpdatesCog(bot)  # type: ignore[arg-type]
    return bot, cog, tmp


async def _seed_tracked(
    pool: DbPool,
    *,
    guild_ids: list[int],
    website_key: str = "comick",
    url_name: str = "demo",
    ping_role_id: int | None = None,
) -> None:
    tracked = TrackedStore(pool)
    await tracked.upsert_series(
        website_key, url_name, "https://example.com/demo", "Demo", None, None
    )
    for gid in guild_ids:
        await tracked.add_to_guild(gid, website_key, url_name, ping_role_id=ping_role_id)


def _make_channel() -> MagicMock:
    """Returns a MagicMock that satisfies isinstance(..., discord.abc.Messageable)."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    return channel


def test_three_guilds_one_missing_channel_skipped() -> None:
    async def _run() -> None:
        bot, cog, tmp = await _setup()
        try:
            await _seed_tracked(bot.db, guild_ids=[1, 2, 3])
            settings_store = GuildSettingsStore(bot.db)
            await settings_store.set_notifications_channel(1, 100)
            await settings_store.set_notifications_channel(2, 200)
            # guild 3: no notification channel set

            channels = {100: _make_channel(), 200: _make_channel()}
            bot.get_channel.side_effect = lambda cid: channels.get(cid)

            await cog.dispatch(_payload())

            assert channels[100].send.await_count == 1
            assert channels[200].send.await_count == 1
            # No channel resolved for guild 3 → no extra sends.
            assert sum(c.send.await_count for c in channels.values()) == 2
        finally:
            await bot.db.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_premium_chapter_skipped_when_paid_disabled() -> None:
    async def _run() -> None:
        bot, cog, tmp = await _setup()
        try:
            await _seed_tracked(bot.db, guild_ids=[1])
            settings_store = GuildSettingsStore(bot.db)
            await settings_store.set_notifications_channel(1, 100)
            await settings_store.set_paid_chapter_notifs(1, False)

            channel = _make_channel()
            bot.get_channel.side_effect = lambda cid: channel if cid == 100 else None

            await cog.dispatch(_payload(premium=True))
            assert channel.send.await_count == 0
        finally:
            await bot.db.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_per_scanlator_channel_overrides_default() -> None:
    async def _run() -> None:
        bot, cog, tmp = await _setup()
        try:
            await _seed_tracked(bot.db, guild_ids=[1])
            settings_store = GuildSettingsStore(bot.db)
            await settings_store.set_notifications_channel(1, 100)
            await settings_store.set_scanlator_channel(1, "comick", 200)

            channels = {100: _make_channel(), 200: _make_channel()}
            bot.get_channel.side_effect = lambda cid: channels.get(cid)

            await cog.dispatch(_payload())
            assert channels[200].send.await_count == 1
            assert channels[100].send.await_count == 0
        finally:
            await bot.db.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_dm_forbidden_does_not_fail_dispatch() -> None:
    async def _run() -> None:
        bot, cog, tmp = await _setup()
        try:
            await _seed_tracked(bot.db, guild_ids=[1])
            settings_store = GuildSettingsStore(bot.db)
            await settings_store.set_notifications_channel(1, 100)
            await SubscriptionStore(bot.db).subscribe(42, 1, "comick", "demo")

            channel = _make_channel()
            bot.get_channel.side_effect = lambda cid: channel if cid == 100 else None

            user = MagicMock()
            user.send = AsyncMock(
                side_effect=discord.Forbidden(MagicMock(status=403), "DMs disabled")
            )
            bot.fetch_user.return_value = user

            await cog.dispatch(_payload())  # must not raise
            assert channel.send.await_count == 1
            assert user.send.await_count == 1
        finally:
            await bot.db.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_ping_role_resolution_uses_row_ping_role() -> None:
    async def _run() -> None:
        bot, cog, tmp = await _setup()
        try:
            await _seed_tracked(bot.db, guild_ids=[1], ping_role_id=42)
            settings_store = GuildSettingsStore(bot.db)
            await settings_store.set_notifications_channel(1, 100)
            await settings_store.set_default_ping_role(1, 99)  # should NOT win

            channel = _make_channel()
            bot.get_channel.side_effect = lambda cid: channel if cid == 100 else None

            await cog.dispatch(_payload())
            assert channel.send.await_count == 1
            kwargs = channel.send.await_args.kwargs
            assert kwargs["content"] == "<@&42>"
        finally:
            await bot.db.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_ping_role_falls_back_to_default() -> None:
    async def _run() -> None:
        bot, cog, tmp = await _setup()
        try:
            await _seed_tracked(bot.db, guild_ids=[1], ping_role_id=None)
            settings_store = GuildSettingsStore(bot.db)
            await settings_store.set_notifications_channel(1, 100)
            await settings_store.set_default_ping_role(1, 99)

            channel = _make_channel()
            bot.get_channel.side_effect = lambda cid: channel if cid == 100 else None

            await cog.dispatch(_payload())
            kwargs = channel.send.await_args.kwargs
            assert kwargs["content"] == "<@&99>"
        finally:
            await bot.db.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_dm_disabled_user_is_skipped() -> None:
    async def _run() -> None:
        bot, cog, tmp = await _setup()
        try:
            await _seed_tracked(bot.db, guild_ids=[1])
            settings_store = GuildSettingsStore(bot.db)
            await settings_store.set_notifications_channel(1, 100)
            await SubscriptionStore(bot.db).subscribe(42, 1, "comick", "demo")
            await DmSettingsStore(bot.db).upsert(
                DmSettings(
                    user_id=42,
                    notifications_enabled=False,
                    paid_chapter_notifs=True,
                    updated_at="",
                )
            )

            channel = _make_channel()
            bot.get_channel.side_effect = lambda cid: channel if cid == 100 else None

            user = MagicMock()
            user.send = AsyncMock()
            bot.fetch_user.return_value = user

            await cog.dispatch(_payload())
            assert user.send.await_count == 0
            assert bot.fetch_user.await_count == 0
        finally:
            await bot.db.close()
            tmp.cleanup()

    asyncio.run(_run())


def test_default_paid_chapter_setting_allows_premium() -> None:
    """Default settings (paid_chapter_notifs=True) must let premium chapters through."""

    async def _run() -> None:
        bot, cog, tmp = await _setup()
        try:
            await _seed_tracked(bot.db, guild_ids=[1])
            settings_store = GuildSettingsStore(bot.db)
            await settings_store.set_notifications_channel(1, 100)
            # Don't toggle paid_chapter_notifs — defaults to True via guild_settings.

            channel = _make_channel()
            bot.get_channel.side_effect = lambda cid: channel if cid == 100 else None

            await cog.dispatch(_payload(premium=True))
            assert channel.send.await_count == 1
        finally:
            await bot.db.close()
            tmp.cleanup()

    asyncio.run(_run())


# Ensure the imports above are not flagged as unused by linters.
_ = (GuildSettings,)
