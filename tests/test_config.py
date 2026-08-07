"""Tests for TOML configuration loading."""

from __future__ import annotations

import pytest

from manhwa_bot.config import ConfigError, load_config


def test_load_config_reads_bot_command_prefix(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[bot]
command_prefix = "!"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("CRAWLER_API_KEY", "fake-crawler-key")

    config = load_config(config_path, env_path=tmp_path / ".env")

    assert config.bot.command_prefix == "!"


def test_load_config_defaults_bot_command_prefix(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[bot]\n", encoding="utf-8")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("CRAWLER_API_KEY", "fake-crawler-key")

    config = load_config(config_path, env_path=tmp_path / ".env")

    assert config.bot.command_prefix == "?"
    assert config.bot.logger_levels == (("aiohttp", "WARNING"), ("discord", "WARNING"))


def test_load_config_reads_bot_logger_levels(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[bot]

[bot.logger_levels]
discord = "ERROR"
aiosqlite = "INFO"
sqlite3 = "WARNING"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("CRAWLER_API_KEY", "fake-crawler-key")

    config = load_config(config_path, env_path=tmp_path / ".env")

    assert config.bot.logger_levels == (
        ("aiosqlite", "INFO"),
        ("discord", "ERROR"),
        ("sqlite3", "WARNING"),
    )


def test_load_config_defaults_crawler_transport_watchdog(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[crawler]\n", encoding="utf-8")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("CRAWLER_API_KEY", "fake-crawler-key")

    config = load_config(config_path, env_path=tmp_path / ".env")

    assert config.crawler.transport_watchdog_seconds == 180.0


def test_load_config_overrides_crawler_transport_watchdog(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[crawler]
transport_watchdog_seconds = 180.0
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("CRAWLER_API_KEY", "fake-crawler-key")
    monkeypatch.setenv("MANHWABOT_CRAWLER_TRANSPORT_WATCHDOG", "240")

    config = load_config(config_path, env_path=tmp_path / ".env")

    assert config.crawler.transport_watchdog_seconds == 240.0


def test_load_config_defaults_cover_attachment_relay(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[notifications]\n", encoding="utf-8")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("CRAWLER_API_KEY", "fake-crawler-key")

    config = load_config(config_path, env_path=tmp_path / ".env")

    assert config.notifications.cover_attachment_enabled is True
    assert config.notifications.cover_attachment_hosts == ("i.ibb.co",)
    assert config.notifications.cover_attachment_timeout_seconds == 3.0
    assert config.notifications.cover_attachment_max_bytes == 2 * 1024 * 1024
    assert config.notifications.cover_attachment_cache_ttl_seconds == 6 * 60 * 60
    assert config.notifications.cover_attachment_cache_max_bytes == 32 * 1024 * 1024


def test_load_config_reads_cover_attachment_relay_values(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[notifications]
cover_attachment_enabled = false
cover_attachment_hosts = ["covers.example"]
cover_attachment_timeout_seconds = 1.5
cover_attachment_max_bytes = 1024
cover_attachment_cache_ttl_seconds = 60
cover_attachment_cache_max_bytes = 4096
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("CRAWLER_API_KEY", "fake-crawler-key")

    config = load_config(config_path, env_path=tmp_path / ".env")

    assert config.notifications.cover_attachment_enabled is False
    assert config.notifications.cover_attachment_hosts == ("covers.example",)
    assert config.notifications.cover_attachment_timeout_seconds == 1.5
    assert config.notifications.cover_attachment_max_bytes == 1024
    assert config.notifications.cover_attachment_cache_ttl_seconds == 60
    assert config.notifications.cover_attachment_cache_max_bytes == 4096


@pytest.mark.parametrize(
    "setting",
    [
        "cover_attachment_timeout_seconds = 0",
        "cover_attachment_max_bytes = 0",
        "cover_attachment_cache_ttl_seconds = 0",
        "cover_attachment_cache_max_bytes = 0",
    ],
)
def test_load_config_rejects_non_positive_cover_attachment_limits(
    tmp_path, monkeypatch, setting: str
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(f"[notifications]\n{setting}\n", encoding="utf-8")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("CRAWLER_API_KEY", "fake-crawler-key")

    with pytest.raises(ConfigError, match="cover_attachment"):
        load_config(config_path, env_path=tmp_path / ".env")
