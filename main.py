import asyncio
import os

import yaml
from discord import Intents
from discord.utils import setup_logging

from src.core.bot import MangaClient
from src.core.command_tree import BotCommandTree


async def load_extensions(client: MangaClient, extensions: list[str]) -> None:
    for extension in extensions:
        await client.load_extension(extension)


with open("config.yml", "r") as f:
    config = yaml.safe_load(f)


async def main(config):

    intents = Intents(Intents.default().value, **config["privileged-intents"])
    client = MangaClient(config["prefix"], intents, tree_cls=BotCommandTree)
    client.load_config(config)
    setup_logging()

    async with client:
        await load_extensions(client, config["extensions"])
        await client.start(config["token"])


if __name__ == "__main__":
    if not os.path.exists("logs"):
        os.mkdir("logs")
    if not os.path.exists("logs/error.log"):
        with open("logs/error.log", "w") as f:
            f.write("")

    asyncio.run(main(config), debug=config["debug"]["state"])
