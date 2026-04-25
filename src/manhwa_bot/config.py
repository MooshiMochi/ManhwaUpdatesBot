"""Configuration loading.

TOML config (`config.toml`) holds non-secrets; `.env` holds secrets. Environment
variables prefixed with ``MANHWABOT_`` override matching TOML keys at load time
(``MANHWABOT_CRAWLER_WS_URL`` overrides ``[crawler].ws_url``). Returns frozen
dataclasses so callers cannot mutate live config.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when config is missing or malformed."""


@dataclass(frozen=True)
class BotConfig:
    owner_ids: tuple[int, ...]
    log_level: str
    dev_guild_id: int


@dataclass(frozen=True)
class CrawlerConfig:
    ws_url: str
    http_base_url: str
    request_timeout_seconds: float
    reconnect_initial_delay_seconds: float
    reconnect_max_delay_seconds: float
    reconnect_jitter_seconds: float
    consumer_key: str
    api_key: str


@dataclass(frozen=True)
class DbConfig:
    path: str


@dataclass(frozen=True)
class DiscordPremiumConfig:
    enabled: bool
    user_sku_ids: tuple[int, ...]
    guild_sku_ids: tuple[int, ...]
    upgrade_url: str


@dataclass(frozen=True)
class PatreonPremiumConfig:
    enabled: bool
    campaign_id: int
    poll_interval_seconds: int
    freshness_seconds: int
    required_tier_ids: tuple[str, ...]
    pledge_url: str
    access_token: str


@dataclass(frozen=True)
class PremiumConfig:
    enabled: bool
    owner_bypass: bool
    log_decisions: bool
    discord: DiscordPremiumConfig
    patreon: PatreonPremiumConfig


@dataclass(frozen=True)
class NotificationsConfig:
    fanout_concurrency: int
    dm_fanout_concurrency: int
    respect_paid_chapter_setting: bool


@dataclass(frozen=True)
class SupportedWebsitesCacheConfig:
    ttl_seconds: int


@dataclass(frozen=True)
class AppConfig:
    bot: BotConfig
    crawler: CrawlerConfig
    db: DbConfig
    premium: PremiumConfig
    notifications: NotificationsConfig
    supported_websites_cache: SupportedWebsitesCacheConfig
    discord_bot_token: str


def load_dotenv(path: str | Path = ".env") -> None:
    """Populate ``os.environ`` from a .env file. No-op if the file is absent.

    Existing environment variables are not overwritten — env always wins over
    .env so deployments can override file-based defaults.
    """
    p = Path(path)
    if not p.is_file():
        return
    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_override(env_key: str, default: object) -> object:
    """Apply ``MANHWABOT_*`` env override to a TOML default, preserving type."""
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, tuple):
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    return raw


def _section(data: dict, *keys: str) -> dict:
    """Navigate nested TOML sections, returning {} for missing leaves."""
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key, {})
    return current if isinstance(current, dict) else {}


def _ints(value: object) -> tuple[int, ...]:
    if value is None:
        return ()
    if isinstance(value, list | tuple):
        return tuple(int(v) for v in value)
    return ()


def _strs(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list | tuple):
        return tuple(str(v) for v in value)
    return ()


def load_config(
    config_path: str | Path = "config.toml",
    env_path: str | Path = ".env",
) -> AppConfig:
    """Read .env, then config.toml, then apply ``MANHWABOT_*`` env overrides.

    Raises :class:`ConfigError` if a required secret is missing.
    """
    load_dotenv(env_path)

    cfg_path = Path(config_path)
    if not cfg_path.is_file():
        raise ConfigError(f"config file not found: {cfg_path}")
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))

    bot_section = _section(raw, "bot")
    crawler_section = _section(raw, "crawler")
    db_section = _section(raw, "db")
    premium_section = _section(raw, "premium")
    discord_premium_section = _section(raw, "premium", "discord")
    patreon_premium_section = _section(raw, "premium", "patreon")
    notifications_section = _section(raw, "notifications")
    websites_cache_section = _section(raw, "supported_websites_cache")

    bot = BotConfig(
        owner_ids=tuple(_ints(bot_section.get("owner_ids", []))),
        log_level=str(
            _env_override("MANHWABOT_BOT_LOG_LEVEL", bot_section.get("log_level", "INFO"))
        ),
        dev_guild_id=int(
            _env_override("MANHWABOT_BOT_DEV_GUILD_ID", bot_section.get("dev_guild_id", 0))
        ),
    )

    crawler_api_key = os.environ.get("CRAWLER_API_KEY", "").strip()
    if not crawler_api_key:
        raise ConfigError("CRAWLER_API_KEY is required (set in .env)")
    crawler = CrawlerConfig(
        ws_url=str(
            _env_override(
                "MANHWABOT_CRAWLER_WS_URL", crawler_section.get("ws_url", "ws://127.0.0.1:8000/ws")
            )
        ),
        http_base_url=str(
            _env_override(
                "MANHWABOT_CRAWLER_HTTP_BASE_URL",
                crawler_section.get("http_base_url", "http://127.0.0.1:8000"),
            )
        ),
        request_timeout_seconds=float(
            _env_override(
                "MANHWABOT_CRAWLER_REQUEST_TIMEOUT",
                crawler_section.get("request_timeout_seconds", 30.0),
            )
        ),
        reconnect_initial_delay_seconds=float(
            _env_override(
                "MANHWABOT_CRAWLER_RECONNECT_INITIAL_DELAY",
                crawler_section.get("reconnect_initial_delay_seconds", 1.0),
            )
        ),
        reconnect_max_delay_seconds=float(
            _env_override(
                "MANHWABOT_CRAWLER_RECONNECT_MAX_DELAY",
                crawler_section.get("reconnect_max_delay_seconds", 60.0),
            )
        ),
        reconnect_jitter_seconds=float(
            _env_override(
                "MANHWABOT_CRAWLER_RECONNECT_JITTER",
                crawler_section.get("reconnect_jitter_seconds", 1.5),
            )
        ),
        consumer_key=str(
            _env_override(
                "MANHWABOT_CRAWLER_CONSUMER_KEY",
                crawler_section.get("consumer_key", "manhwa-bot-default"),
            )
        ),
        api_key=crawler_api_key,
    )

    db = DbConfig(
        path=str(_env_override("MANHWABOT_DB_PATH", db_section.get("path", "manhwa_bot.db"))),
    )

    discord_premium = DiscordPremiumConfig(
        enabled=bool(discord_premium_section.get("enabled", True)),
        user_sku_ids=tuple(_ints(discord_premium_section.get("user_sku_ids", []))),
        guild_sku_ids=tuple(_ints(discord_premium_section.get("guild_sku_ids", []))),
        upgrade_url=str(discord_premium_section.get("upgrade_url", "")),
    )
    patreon_premium = PatreonPremiumConfig(
        enabled=bool(patreon_premium_section.get("enabled", False)),
        campaign_id=int(patreon_premium_section.get("campaign_id", 0)),
        poll_interval_seconds=int(patreon_premium_section.get("poll_interval_seconds", 600)),
        freshness_seconds=int(patreon_premium_section.get("freshness_seconds", 1800)),
        required_tier_ids=tuple(_strs(patreon_premium_section.get("required_tier_ids", []))),
        pledge_url=str(patreon_premium_section.get("pledge_url", "")),
        access_token=os.environ.get("PATREON_ACCESS_TOKEN", "").strip(),
    )
    premium = PremiumConfig(
        enabled=bool(premium_section.get("enabled", True)),
        owner_bypass=bool(premium_section.get("owner_bypass", True)),
        log_decisions=bool(premium_section.get("log_decisions", False)),
        discord=discord_premium,
        patreon=patreon_premium,
    )

    notifications = NotificationsConfig(
        fanout_concurrency=int(notifications_section.get("fanout_concurrency", 8)),
        dm_fanout_concurrency=int(notifications_section.get("dm_fanout_concurrency", 4)),
        respect_paid_chapter_setting=bool(
            notifications_section.get("respect_paid_chapter_setting", True)
        ),
    )
    websites_cache = SupportedWebsitesCacheConfig(
        ttl_seconds=int(websites_cache_section.get("ttl_seconds", 3600)),
    )

    discord_bot_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not discord_bot_token:
        raise ConfigError("DISCORD_BOT_TOKEN is required (set in .env)")

    return AppConfig(
        bot=bot,
        crawler=crawler,
        db=db,
        premium=premium,
        notifications=notifications,
        supported_websites_cache=websites_cache,
        discord_bot_token=discord_bot_token,
    )
