import asyncio
import logging
import os

from aiohttp import ClientConnectorError
from discord import Intents
from discord.errors import LoginFailure

from src.core import BotCommandTree, CachedClientSession, MangaClient
from src.core.cache import CachedCurlCffiSession
from src.core.config_loader import ensure_configs, load_config
from src.core.scanlators import scanlators
from src.utils import (
    ensure_environment, ensure_proxy, exit_bot, setup_logging, silence_debug_loggers, test_logger
)


async def load_extensions(client: MangaClient, extensions: list[str]) -> None:
    for extension in extensions:
        await client.load_extension(extension)


def ensure_logs() -> None:
    if not os.path.exists("logs"):
        os.mkdir("logs")
    if not os.path.exists("logs/error.log"):
        with open("logs/error.log", "w") as f:
            f.write("")


async def custom_initializer(bot: MangaClient, _logger: logging.Logger) -> None:
    """
    Summary:
        This function is called after the bot has been initialized and before it logs in.

    Args:
        bot: The bot instance.
        _logger: The logger instance.

    Returns:
        None
    """
    _logger.info("Running custom initializer...")


async def main():
    _logger = logging.getLogger("main")
    config = load_config(_logger)
    if config and config.get("debug") is True:
        setup_logging(level=logging.DEBUG)
    else:
        setup_logging(level=logging.INFO)

    test_logger(_logger)

    _logger.info("Starting bot...")
    config = ensure_configs(_logger, config, scanlators)

    ensure_logs()

    silence_debug_loggers(
        _logger,
        [
            "websockets.client",
            "aiosqlite",
            "discord.gateway",
            "discord.client",
            "discord.http",
            "discord.webhook.async_",
            "discord.state",
            "filelock",
        ]
    )

    CachedClientSession.set_default_cache_time(config["constants"]["cache-retention-seconds"])
    CachedCurlCffiSession.set_default_cache_time(config["constants"]["cache-retention-seconds"])
    # if flaresolverr_url := config.get("flaresolverr", {}).get("base_url"):
    #     BaseCacheSessionMixin.ignore_url(flaresolverr_url)

    intents = Intents(Intents.default().value, **config["privileged-intents"])
    client = MangaClient(config["prefix"], intents, tree_cls=BotCommandTree)
    client.load_config(config)
    client.load_scanlators(scanlators)

    await ensure_environment(client, _logger)
    await ensure_proxy(config, _logger)

    async with client:
        await custom_initializer(client, _logger)
        await load_extensions(client, config["extensions"])
        await client.db.async_init()
        await client.unload_disabled_scanlators(scanlators)
        try:
            await client.start(config["token"])
        except LoginFailure as e:
            _logger.critical(f"{e}")
            _logger.critical(
                "    - Please run the setup.bat file if you're on "
                "windows or the setup.sh file if you're on linux/macOS."
            )
            await client.close()
            exit_bot()
        except ClientConnectorError as e:
            if e.strerror == "getaddrinfo failed":
                _logger.critical("You are offline! Please connect to a network and try again!")


if __name__ == "__main__":
    import sys

    try:
        if os.name == "nt" and sys.version_info >= (3, 8):
            import tracemalloc

            tracemalloc.start()

        asyncio.run(main())
    except KeyboardInterrupt:
        exit(1)
