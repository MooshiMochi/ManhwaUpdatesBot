import io
import logging
import os
import traceback
from datetime import datetime
from typing import Optional, Union

import aiohttp
import discord
from discord import Intents
from discord.ext import commands

from .apis import APIManager
from .cache import CachedClientSession, CachedCurlCffiSession
from .database import Database
from .scanlators import scanlators


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
        self.owner_ids: set[int] = None
        self._apis: APIManager = None
        self._config = None
        self.test_guild_ids = None
        self.db = Database(self, "database.db")
        self._logger: logging.Logger = logging.getLogger("bot")

        # Placeholder values. These are set in .setup_hook() below
        self._session: Union[aiohttp.ClientSession, CachedClientSession] = None
        self.curl_session: CachedCurlCffiSession = None

        self.log_channel_id: Optional[int] = None
        self._debug_mode: bool = False
        self.proxy_addr: Optional[str] = None

        self._all_scanners: dict = scanlators.copy()  # You must not mutate this dict. Mutate scanlators instead.

        self._start_time: datetime = datetime.now()

    async def setup_hook(self):
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
            self.loop.create_task(self.sync_commands())  # noqa: No need to await a task
        self.loop.create_task(self.update_restart_message())  # noqa: No need to await a task

        self._apis = APIManager(self, CachedClientSession(proxy=self.proxy_addr, name="cache.apis", trust_env=True))
        await self._apis.webshare.async_init()
        if self._apis.webshare.is_available:
            # use static proxy for flare
            self._apis.flare.proxy = (await self._apis.webshare.get_proxy()).to_url_dict()
        await self._apis.flare.async_init()
        #  test flaresolverr. change scanlators' request_method to 'curl' that use 'flare'
        if not self._apis.flare.is_available:
            for scanlator in scanlators.keys():
                if scanlators[scanlator].json_tree.request_method == "flare":
                    self.logger.warning(f"[{scanlator}] Changed request method to 'curl' from 'flare' due to "
                                        f"FlareSolverr being unavailable.")
                    scanlators[scanlator].json_tree.request_method = "curl"

    def _remove_unavailable_scanlators(self):
        for scanlator, user_agent in self._config["user-agents"].items():
            if user_agent is None and scanlators.pop(scanlator, None) is not None:
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

    def load_scanlators(self, _scanlators: dict) -> None:
        # remove any disabled scanlators from the original scanaltors dict
        for scanlator in _scanlators.values():
            scanlator.bot = self
        self._all_scanners.update(_scanlators)

    async def unload_disabled_scanlators(self, _scanlators: dict) -> None:
        disabled: list[str] = await self.db.get_disabled_scanlators()
        for disabled_scanlator in disabled:
            _scanlators.pop(disabled_scanlator, None)

    async def on_ready(self):
        self._logger.info(f"{self.user.name}#{self.user.discriminator} is ready!")

    async def close(self):
        self.logger.info("Closing bot...")
        if self.apis.flare.is_available:
            self.logger.info("[FlareSolverr] > Begin server session cleanup...")
            await self.apis.flare.get_active_sessions()  # refresh the session cache just to be safe
            await self.apis.flare.destroy_all_sessions()  # destroy all active sessions
            self.logger.info("[FlareSolverr] > Server session cleanup complete.")
        self.logger.info("Closing aiohttp sessions...")
        await self._session.close() if self._session else None
        await self.apis.session.close() if self.apis else None
        self.logger.info("Aiohttp sessions closed.")
        if self.curl_session:
            self.logger.info("Closing curl session...")
            try:
                self.curl_session.close()
                self.logger.info("Curl session closed.")
            except TypeError:
                self.logger.error("Skipping... Curl session already closed.")
        self.logger.info("Finalising closing procedure! Goodbye!")
        await super().close()

    async def log_to_discord(
            self, content: Union[str, None] = None, *, error: Optional[Exception] = None, **kwargs
    ) -> None:
        """Log a message to a discord log channel."""
        if not self.is_ready():
            await self.wait_until_ready()

        if not content and not kwargs and error is None:
            return

        channel = self.get_channel(self.log_channel_id)

        if not channel:
            return
        try:
            if error:
                error_str = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                if not content:
                    content = error_str
                else:
                    content += "\n\n------\n\n" + error_str

            if content and len(content) > 2000:
                # try to send it as a file
                buffer = io.BytesIO(content.encode("utf-8"))
                file = discord.File(fp=buffer, filename="log.py")
                if kwargs.get("file") is None:
                    kwargs["file"] = file
                    content = None
                else:
                    files_kwarg = kwargs.get("files")
                    if files_kwarg is None:
                        kwargs["files"] = [file]
                        content = None
                    elif len(files_kwarg) < 10:
                        kwargs["files"].append(file)
                        content = None
                    else:
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
        cmd_data = interaction.data
        cmd_name = f"{cmd_data['name']} {' '.join([opt['name'] for opt in cmd_data.get('options', [])])}"
        cmd_opts: list[dict] = interaction.data.get("options", [])

        # **Key change:** Handle both subcommands and top-level options consistently
        options_list = []
        if cmd_opts:
            for opt in cmd_opts[0].get("options", []) or cmd_opts:  # Handle both cases
                if "value" in opt:
                    options_list.append(f"{opt['name']}: {opt['value']}")

        fmt_opts = f'\n{spc}'.join(options_list)
        _author_text = f"[ Author  ] > {user}"
        if interaction.guild_id is not None:
            _guild_text = f"[  Guild  ] > {interaction.guild.name} ({interaction.guild_id})"
        else:
            _guild_text = "[  Guild  ] > DM Channel"
        _cmd_text = f"[ Command ] > /{cmd_name}"
        pretty_msg = f"```\n{_author_text}\n{_guild_text}\n{_cmd_text}```"
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

    @property
    def apis(self):
        return self._apis

    @property
    def start_time(self) -> datetime:
        return self._start_time
