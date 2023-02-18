import logging

import aiohttp
import discord
from discord import Intents
from discord.ext import commands

from .database import Database


class MangaClient(commands.Bot):
    def __init__(
        self, prefix: str = "!", intents: Intents = Intents.default(), *args, **kwargs
    ):
        super().__init__(
            command_prefix=commands.when_mentioned_or(prefix or "!"),
            intents=intents,
            *args,
            **kwargs,
        )
        self.db = Database(self, "database.db")
        self._logger: logging.Logger = logging.getLogger("bot")
        self._session: aiohttp.ClientSession = None
        self.log_channel_id: int = None
        self._debug_mode: bool = False

    async def setup_hook(self):
        await self.db.async_init()
        self._session = aiohttp.ClientSession()

        if not self.__config["constants"]["synced"]:
            self.loop.create_task(self.sync_commands())

    async def sync_commands(self):
        await self.wait_until_ready()
        fmt = await self.tree.sync()
        self._logger.info(f"Synced {len(fmt)} commands globally.")

        self.__config["constants"]["synced"] = True
        import yaml

        with open("config.yml", "w") as f:
            yaml.dump(self.__config, f, default_flow_style=False)

    def load_config(self, config: dict):
        self.owner_ids = config["constants"]["owner-ids"]
        self.test_guild_id = config["constants"]["test-guild-id"]
        self.log_channel_id: int = config["constants"]["log-channel-id"]
        self._debug_mode: bool = config["debug"]["state"]

        self.__config: dict = config

    async def on_ready(self):
        self._logger.info("Ready!")

    async def close(self):
        await self._session.close()
        await super().close()

    async def log_to_discord(self, *args, **kwargs) -> None:
        """Log a message to a discord log channel."""
        if not self.is_ready():
            await self.wait_until_ready()

        channel = self.get_channel(self.log_channel_id)
        try:
            await channel.send(**kwargs)
        except Exception as e:
            self._logger.error(f"Error while logging: {e}")

    async def on_message(self, message: discord.Message, /) -> None:
        await self.process_commands(message)
