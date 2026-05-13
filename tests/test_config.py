"""Tests for TOML configuration loading."""

from __future__ import annotations

from manhwa_bot.config import load_config


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
