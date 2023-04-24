import asyncio
import logging
import os

from discord import Intents
from discord.errors import LoginFailure
from discord.utils import setup_logging

from src.core import BotCommandTree
from src.core import CachedClientSession, ProtectedRequest
from src.core import MangaClient
from src.utils import ensure_configs, ensure_environment, exit_bot, ensure_proxy


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
    setup_logging(level=logging.INFO)

    _logger = logging.getLogger("main")

    config = ensure_configs(_logger)

    setup_logging(level=logging.DEBUG if config["debug"] else logging.INFO)

    ensure_logs()

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
