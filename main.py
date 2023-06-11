import asyncio
import logging
import os

from discord import Intents
from discord.errors import LoginFailure
from discord.utils import setup_logging

from src.core import BotCommandTree, CachedClientSession, MangaClient, ProtectedRequest
from src.utils import ensure_configs, ensure_environment, ensure_proxy, exit_bot, load_config, silence_debug_loggers


async def load_extensions(client: MangaClient, extensions: list[str]) -> None:
    for extension in extensions:
        await client.load_extension(extension)


def ensure_logs() -> None:
    if not os.path.exists("logs"):
        os.mkdir("logs")
    if not os.path.exists("logs/error.log"):
        with open("logs/error.log", "w") as f:
            f.write("")


async def main():
    # setup_logging(level=logging.INFO)

    _logger = logging.getLogger("main")
    _logger.info("Starting bot...")
    config = load_config(_logger)
    if config and config.get("debug") is True:
        setup_logging(level=logging.DEBUG)
    else:
        setup_logging(level=logging.INFO)
    config = ensure_configs(_logger, config)

    ensure_logs()

    silence_debug_loggers(
        _logger,
        [
            "pyppeteer.connection.Connection",
            "websockets.client",
            "pyppeteer.connection.CDPSession",
            "aiosqlite",
            "discord.gateway",
            "discord.client",
            "discord.http",
            "discord.webhook.async_",
        ]
    )

    CachedClientSession.set_default_cache_time(config["constants"]["cache-retention-seconds"])
    ProtectedRequest.set_default_cache_time(config["constants"]["cache-retention-seconds"])

    intents = Intents(Intents.default().value, **config["privileged-intents"])
    client = MangaClient(config["prefix"], intents, tree_cls=BotCommandTree)
    client.load_config(config)

    await ensure_environment(client, _logger)
    await ensure_proxy(config, _logger)

    async with client:
        await load_extensions(client, config["extensions"])
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


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        exit(1)
