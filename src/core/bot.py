import logging
import os
from typing import Optional, Union

import aiohttp
import discord
from discord import Intents
from discord.ext import commands

from .database import Database
from .mangadexAPI import MangaDexAPI
from .cache import CachedClientSession
from .objects import GuildSettings


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
        self._config = None
        self.test_guild_id = None
        self.db = Database(self, "database.db")
        self._logger: logging.Logger = logging.getLogger("bot")
        self._session: Optional[Union[aiohttp.ClientSession, CachedClientSession]] = None
        self.log_channel_id: Optional[int] = None
        self._debug_mode: bool = False
        self.mangadex_api: Optional[MangaDexAPI] = None

    async def setup_hook(self):
        await self.db.async_init()
        if os.name == "nt":
            self._session = CachedClientSession()
        else:
            self._session = CachedClientSession(None, trust_env=True)

        if not self._config["constants"]["synced"]:
            self.loop.create_task(self.sync_commands())
        self.loop.create_task(self.update_restart_message())

        self._session.ignored_urls = self._session.ignored_urls.union(await self.db.get_webhooks())

    async def update_restart_message(self):
        await self.wait_until_ready()

        if os.path.exists("logs/restart.txt"):
            with open("logs/restart.txt", "r") as f:
                contents = f.read()
                if not contents:
                    return
                channel_id, msg_id = contents.split("/")[5:]

            with open("logs/restart.txt", "w") as f:  # clear the file
                f.write("")
            channel = self.get_channel(int(channel_id))
            if channel is None:
                return
            msg = await channel.fetch_message(int(msg_id))
            if msg is None:
                return
            em = msg.embeds[0]
            em.description = f"✅ `Bot is now online.`"
            return await msg.edit(embed=em)

    async def sync_commands(self):
        await self.wait_until_ready()
        fmt = await self.tree.sync()
        self._logger.info(f"Synced {len(fmt)} commands globally.")

        self._config["constants"]["synced"] = True
        import yaml

        with open("config.yml", "w") as f:
            yaml.dump(self._config, f, default_flow_style=False)

    def load_config(self, config: dict):
        self.owner_ids = config["constants"].get("owner-ids", [self.owner_id])
        self.test_guild_id = config["constants"].get("test-guild-id")
        self.log_channel_id: int = config["constants"].get("log-channel-id")
        self._debug_mode: bool = config.get("debug", False)

        self.mangadex_api = MangaDexAPI(
            CachedClientSession(trust_env=True if os.name != "nt" else False)
        )

        self._config: dict = config

    async def on_ready(self):
        self._logger.info("Ready!")

    async def close(self):
        await self._session.close() if self._session else None
        await self.mangadex_api.session.close() if self.mangadex_api else None
        await super().close()

    async def log_to_discord(self, **kwargs) -> None:
        """Log a message to a discord log channel."""
        if not self.is_ready():
            await self.wait_until_ready()

        channel = self.get_channel(self.log_channel_id)
        if not channel:
            return
        try:
            await channel.send(**kwargs)
        except Exception as e:
            self._logger.error(f"Error while logging: {e}")

    async def on_message(self, message: discord.Message, /) -> None:
        await self.process_commands(message)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        guild_config: GuildSettings = await self.db.get_guild_config(guild.id)
        if not guild_config:
            return

        if (
                guild_config.channel is None or guild_config.role is None
        ):  # if we can't find the channel or role, we can't send updates so delete guild config entirely
            await self.db.delete_config(guild.id)
            return

        try:
            channel_webhooks = await guild_config.channel.webhooks()
        except discord.Forbidden:
            await self.db.delete_config(guild.id)
            return

        if channel_webhooks and guild_config.webhook in channel_webhooks:
            return  # Everything is fine, we have a webhook in the channel
        else:
            try:
                guild_config.webhook = await guild_config.channel.create_webhook(
                    name="Manga Updates",
                    avatar=await self.user.avatar.read(),
                    reason="Manga Updates",
                )
                await self.db.upsert_config(guild_config)
            except discord.Forbidden:
                await self.db.delete_config(guild.id)
            finally:
                return

    @property
    def session(self):
        return self._session

    @property
    def logger(self):
        return self._logger

    @property
    def config(self):
        return self._config
