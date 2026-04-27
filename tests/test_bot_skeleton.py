"""Sanity checks for ManhwaBot construction — no network, no DB."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from discord.ext import commands

from manhwa_bot.bot import ManhwaBot
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
from manhwa_bot.crawler.client import CrawlerClient
from manhwa_bot.db.pool import DbPool


def _fake_config(command_prefix: str = "?") -> AppConfig:
    return AppConfig(
        bot=BotConfig(
            owner_ids=(123456789,),
            log_level="WARNING",
            dev_guild_id=0,
            command_prefix=command_prefix,
        ),
        crawler=CrawlerConfig(
            ws_url="ws://127.0.0.1:9999/ws",
            http_base_url="http://127.0.0.1:9999",
            request_timeout_seconds=5.0,
            reconnect_initial_delay_seconds=0.1,
            reconnect_max_delay_seconds=1.0,
            reconnect_jitter_seconds=0.0,
            consumer_key="test",
            api_key="test-key",
        ),
        db=DbConfig(path=":memory:"),
        premium=PremiumConfig(
            enabled=False,
            owner_bypass=True,
            log_decisions=False,
            discord=DiscordPremiumConfig(
                enabled=False,
                user_sku_ids=(),
                guild_sku_ids=(),
                upgrade_url="",
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
            fanout_concurrency=4,
            dm_fanout_concurrency=2,
            respect_paid_chapter_setting=False,
        ),
        supported_websites_cache=SupportedWebsitesCacheConfig(ttl_seconds=3600),
        discord_bot_token="fake-token",
    )


def _make_bot(command_prefix: str = "?") -> ManhwaBot:
    config = _fake_config(command_prefix=command_prefix)
    # DbPool and CrawlerClient are not connected — we only test construction.
    db = object.__new__(DbPool)
    crawler = CrawlerClient(config.crawler)
    return ManhwaBot(config, db, crawler)  # type: ignore[arg-type]


def test_intents() -> None:
    bot = _make_bot()
    assert bot.intents.members is True
    assert bot.intents.message_content is True
    assert bot.intents.presences is False


def test_command_prefix() -> None:
    bot = _make_bot()
    assert bot.command_prefix is not commands.when_mentioned


def test_command_prefix_uses_configured_prefix() -> None:
    bot = _make_bot(command_prefix="!")
    bot._connection.user = SimpleNamespace(id=42)  # type: ignore[attr-defined]
    message = SimpleNamespace(guild=object(), content="!dev help")

    prefixes = asyncio.run(bot.get_prefix(message))  # type: ignore[arg-type]

    assert "!" in prefixes
    assert "?" not in prefixes


def test_help_command_is_none() -> None:
    bot = _make_bot()
    assert bot.help_command is None


def test_process_commands_allows_question_prefix_in_guild_messages() -> None:
    bot = _make_bot()
    message = SimpleNamespace(guild=object(), mentions=[], content="?dev help")

    with patch.object(commands.Bot, "process_commands", new=AsyncMock()) as process_commands:
        asyncio.run(bot.process_commands(message))  # type: ignore[arg-type]

    process_commands.assert_awaited_once_with(message)
