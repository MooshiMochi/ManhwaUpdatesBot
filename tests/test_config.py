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
