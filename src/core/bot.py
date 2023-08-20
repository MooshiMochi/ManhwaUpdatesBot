import logging
import os
from typing import Optional, Union

import aiohttp
import discord
from curl_cffi.requests import AsyncSession
from discord import Intents
from discord.ext import commands

from .cache import CachedClientSession, CachedCurlCffiSession
from .comickAPI import ComickAppAPI
from .database import Database
from .mangadexAPI import MangaDexAPI
from .objects import GuildSettings
from .scanners import SCANLATORS


class MangaClient(commands.Bot):
    # noinspection PyTypeChecker
    def __init__(
            self, prefix: str = "!", intents: Intents = Intents.default(), *args, **kwargs
    ):
        # noinspection PyTypeChecker
        super().__init__(
            command_prefix=commands.when_mentioned_or(prefix or "!"),
            intents=intents,
            *args,
            **kwargs,
        )
        self._config = None
        self.test_guild_ids = None
        self.db = Database(self, "database.db")
        self._logger: logging.Logger = logging.getLogger("bot")

        # Placeholder values. These are set in .setup_hook() below
        self._session: Union[aiohttp.ClientSession, CachedClientSession] = None
        self.curl_session: AsyncSession = None
        self.mangadex_api: MangaDexAPI = None
        self.comick_api: ComickAppAPI = None

        self.log_channel_id: Optional[int] = None
        self._debug_mode: bool = False
        self.proxy_addr: Optional[str] = None

        self._all_scanners: dict = SCANLATORS.copy()  # You must not mutate this dict. Mutate SCANLATORS instead.

    async def setup_hook(self):
        await self.db.async_init()
        if self._config["proxy"]["enabled"]:
            if self.config["proxy"]["username"] and self.config["proxy"]["password"]:
                self.proxy_addr = (
                    f"http://{self._config['proxy']['username']}:{self._config['proxy']['password']}@"
                    f"{self._config['proxy']['ip']}:{self._config['proxy']['port']}"
                )
            else:
                self.proxy_addr = f"http://{self._config['proxy']['ip']}:{self._config['proxy']['port']}"

        self._remove_unavailable_scanlators()

        self._session = CachedClientSession(proxy=self.proxy_addr, name="cache.bot", trust_env=True)
        self.curl_session = CachedCurlCffiSession(impersonate="chrome101", name="cache.curl_cffi", proxies={
            "http": self.proxy_addr,
            "https": self.proxy_addr
        })

        if self._config["constants"]["first_bot_startup"] or self._config["constants"]["autosync"]:
            self.loop.create_task(self.sync_commands())
        self.loop.create_task(self.update_restart_message())

        self._session.ignored_urls = self._session.ignored_urls.union(await self.db.get_webhooks())
        self.mangadex_api = MangaDexAPI(
            CachedClientSession(proxy=self.proxy_addr, name="cache.dex", trust_env=True)
        )
        self.comick_api = ComickAppAPI(
            CachedClientSession(proxy=self.proxy_addr, name="cache.comick", trust_env=True)
        )

    def _remove_unavailable_scanlators(self):
        for scanlator, user_agent in self._config["user-agents"].items():
            if user_agent is None and SCANLATORS.pop(scanlator, None) is not None:
                self._logger.warning(f"Removed {scanlator} from scanlators (requires approved user agent).")

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
            try:
                msg = await channel.fetch_message(int(msg_id))
            except discord.NotFound:
                return
            if msg is None:
                return
            em = msg.embeds[0]
            em.description = f"✅ `Bot is now online.`"
            return await msg.edit(embed=em)

    async def sync_commands(self):
        await self.wait_until_ready()
        fmt = await self.tree.sync()
        self._logger.info(f"Synced {len(fmt)} commands globally.")

        if self._config["constants"]["first_bot_startup"]:
            self._config["constants"]["first_bot_startup"] = False
            import yaml

            with open("config.yml", "w") as f:
                yaml.dump(self._config, f, default_flow_style=False)

    def load_config(self, config: dict):
        self.owner_ids = config["constants"].get("owner-ids", [self.owner_id])
        self.test_guild_ids = config["constants"].get("test-guild-ids")
        self.log_channel_id: int = config["constants"].get("log-channel-id")
        self._debug_mode: bool = config.get("debug", False)

        self._config: dict = config

    async def on_ready(self):
        self._logger.info(f"{self.user.name}#{self.user.discriminator} is ready!")

    async def close(self):
        await self._session.close() if self._session else None
        await self.mangadex_api.session.close() if self.mangadex_api else None
        self.curl_session.close() if self.curl_session else None
        await super().close()

    async def log_to_discord(self, content: Union[str, None] = None, **kwargs) -> None:
        """Log a message to a discord log channel."""
        if not self.is_ready():
            await self.wait_until_ready()

        if not content and not kwargs:
            return

        channel = self.get_channel(self.log_channel_id)

        if not channel:
            return
        try:
            if content and len(content) > 1997:
                content = "..." + content[-1997:]

            await channel.send(content, **kwargs)
        except Exception as e:
            self._logger.error(f"Error while logging: {e}")

    async def log_command_usage(self, interaction: discord.Interaction) -> None:
        if not self.is_ready():
            await self.wait_until_ready()
        if interaction.type != discord.InteractionType.application_command:
            return

        spc = "\u200b \u200b > "
        user = interaction.user
        cmd_name = interaction.data["name"]
        cmd_opts: list[dict] = interaction.data.get("options", [])

        if len(cmd_opts) == 1:
            cmd_opts = cmd_opts[0].get("options", [])
            cmd_name += f" {interaction.data['options'][0]['name']}"
            options_list = [f"{opt['name']}: {opt['value']}" for opt in cmd_opts]
        elif len(cmd_opts) > 1:
            options_list = [f"{opt['name']}: {opt['value']}" for opt in cmd_opts]
        else:
            options_list = []

        fmt_opts = f'\n{spc}'.join(options_list)
        pretty_msg = f"```\n[ Author  ] > {user}\n[ Command ] > /{cmd_name}```"
        cmd_log_channel_id = self._config["constants"].get("command-log-channel-id")
        cmd_log = f"[Command: {user}] > /{cmd_name}"
        if fmt_opts:
            cmd_log += f" {' '.join(options_list)}"
            pretty_msg = pretty_msg[:-3] + f"\n[ Options ] > (see below)\n{spc}{fmt_opts}```"

        self.logger.debug(cmd_log)
        if not cmd_log_channel_id:
            return
        else:
            channel = self.get_channel(cmd_log_channel_id)
            if not channel:
                return
            try:
                pretty_msg = pretty_msg[:4000]
                em = discord.Embed(color=0x000000, description=pretty_msg)
                await channel.send(embed=em)
            except Exception as e:
                self.logger.error(f"Error while logging command usage: {e}")

    async def on_message(self, message: discord.Message, /) -> None:
        await self.process_commands(message)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        guild_config: GuildSettings = await self.db.get_guild_config(guild.id)
        if not guild_config:
            return

        if (
                guild_config.notifications_channel is None
        ):  # if we can't find the channel, we can't send updates so delete guild config entirely
            await self.db.delete_config(guild.id)
            return

        try:
            channel_webhooks = await guild_config.notifications_channel.webhooks()
        except discord.Forbidden:
            await self.db.delete_config(guild.id)
            return

        if channel_webhooks and guild_config.notifications_webhook in channel_webhooks:
            return  # Everything is fine, we have a webhook in the channel
        else:
            try:
                guild_config.notifications_webhook = await guild_config.notifications_channel.create_webhook(
                    name="Manhwa Updates",
                    avatar=await self.user.avatar.read(),
                    reason="Manhwa Updates",
                )
                await self.db.upsert_config(guild_config)
            except discord.Forbidden:
                await self.db.delete_config(guild.id)
            finally:
                return

    @property
    def debug(self):
        return self._debug_mode

    @property
    def session(self):
        return self._session

    @property
    def logger(self):
        return self._logger

    @property
    def config(self):
        return self._config
