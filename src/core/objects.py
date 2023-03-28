from __future__ import annotations

import asyncio
import logging
import random
import time
import urllib
from asyncio import TimeoutError
from typing import TYPE_CHECKING, Iterable, Union

if TYPE_CHECKING:
    from src.core.bot import MangaClient

from typing import Optional
import aiohttp
import discord
from bs4 import BeautifulSoup
from discord.ext.commands import Context
from discord.ext.commands import Paginator as CommandPaginator
from src.core.scanners import SCANLATORS, ABCScan


class PaginatorView(discord.ui.View):
    def __init__(
        self,
        items: list[Union[str, int, discord.Embed]] = None,
        interaction: Union[discord.Interaction, Context] = None,
        timeout: float = 60.0,
    ) -> None:
        self.items = items
        self.interaction: discord.Interaction = interaction
        self.page: int = 0
        self.message: Optional[discord.Message] = None

        if not self.items and not self.interaction:
            raise AttributeError(
                "A list of items of type 'Union[str, int, discord.Embed]' was not provided to iterate through as well "
                "as the interaction."
            )

        elif not items:
            raise AttributeError(
                "A list of items of type 'Union[str, int, discord.Embed]' was not provided to iterate through."
            )

        elif not interaction:
            raise AttributeError("The command interaction was not provided.")

        if not isinstance(items, Iterable):
            raise AttributeError(
                "An iterable containing items of type 'Union[str, int, discord.Embed]' classes is required."
            )

        elif False in [
            isinstance(item, (str, int, discord.Embed)) for item in items
        ]:
            raise AttributeError(
                "All items within the iterable must be of type 'str', 'int' or 'discord.Embed'."
            )

        super().__init__(timeout=timeout)
        self.items = list(self.items)

    def __get_response_kwargs(self):
        if isinstance(self.items[self.page], discord.Embed):
            return {"embed": self.items[self.page]}
        else:
            return {"content": self.items[self.page]}

    @discord.ui.button(label=f"⏮️", style=discord.ButtonStyle.blurple)
    async def _first_page(
        self, interaction: discord.Interaction, _
    ):
        self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple)
    async def back(self, interaction: discord.Interaction, _):
        self.page -= 1
        if self.page == -1:
            self.page = len(self.items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red)
    async def _stop(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple)
    async def forward(self, interaction: discord.Interaction, _):
        self.page += 1
        if self.page == len(self.items):
            self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple)
    async def _last_page(
        self, interaction: discord.Interaction, _
    ):
        self.page = len(self.items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        author = None
        if isinstance(self.interaction, discord.Interaction):
            author = self.interaction.user
        else:
            author = self.interaction.author

        if author.id == interaction.user.id:
            return True
        else:
            embed = discord.Embed(title=f"🚫 You cannot use this menu!", color=0xFF0000)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False

    async def on_timeout(self) -> None:
        if self.message is not None:
            await self.message.edit(view=None)
        self.stop()

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item
    ) -> None:
        if isinstance(error, TimeoutError):
            pass
        else:
            em = discord.Embed(
                title=f"🚫 An unknown error occurred!",
                description=f"{str(error)[-1500:]}",
                color=0xFF0000,
            )
            await interaction.response.send_message(embed=em, ephemeral=True)


class TextPageSource:
    """Get pages for text paginator"""

    def __init__(
        self,
        text,
        *,
        prefix="```",
        suffix="```",
        max_size=2000,
        code_block=False,
        block_prefix="py",
    ):
        self._max_size = max_size

        if code_block:
            prefix += (
                block_prefix + "\n" if not block_prefix.endswith("\n") else block_prefix
            )
        pages = CommandPaginator(prefix=prefix, suffix=suffix, max_size=max_size - 200)
        for line in text.split("\n"):
            try:
                pages.add_line(line)
            except RuntimeError:
                converted_lines = self.__convert_to_chunks(line)
                for line in converted_lines:
                    pages.add_line(line)
        self.pages = pages

    def getPages(self, *, page_number=True):
        """Gets the pages."""
        pages = []
        pagenum = 1
        for page in self.pages.pages:
            if page_number:
                page += f"\nPage {pagenum}/{len(self.pages.pages)}"
                pagenum += 1
            pages.append(page)
        return pages

    def __convert_to_chunks(self, text):
        """Convert the text to chunks of size max_size-300"""
        chunks = []
        for i in range(0, len(text), self._max_size - 300):
            chunks.append(text[i : i + self._max_size - 300])
        return chunks


class Manga:
    def __init__(
        self,
        id: str,
        human_name: str,
        manga_url: str,
        last_chapter_url_hash: str,
        last_chapter_string: str,
        completed: bool,
        scanlator: str,
    ) -> None:
        self._id: str = id
        self._human_name: str = human_name
        self._manga_url: str = manga_url
        self._last_chapter_url_hash: str = last_chapter_url_hash
        self._last_chapter_string: str = last_chapter_string
        self._completed: bool = completed
        self._scanlator: str = scanlator

    def update(
        self,
        last_chapter_url_hash: int = None,
        last_chapter_string: str = None,
        completed: bool = None,
    ) -> None:
        """Update the manga."""
        if last_chapter_url_hash is not None:
            self._last_chapter_url_hash = last_chapter_url_hash
        if last_chapter_string is not None:
            self._last_chapter_string = last_chapter_string
        if completed is not None:
            self._completed = completed

    @property
    def id(self) -> str:
        """Get the database ID of the manga."""
        return self._id

    @property
    def human_name(self) -> str:
        """Get the name of the manga."""
        return self._human_name

    @property
    def manga_url(self) -> str:
        """Get the URL of the manga.
        Example: https://toonily.net/webtoon/what-do-i-do-now/
        """
        return self._manga_url

    @property
    def last_chapter_url_hash(self) -> str:
        """Get the last chapter url hash of the manga."""
        return self._last_chapter_url_hash

    @property
    def completed(self) -> bool:
        """Get the status of the manga."""
        return self._completed

    @property
    def scanlator(self) -> str:
        """Get the scanlator of the manga."""
        return self._scanlator

    @property
    def last_chapter_string(self) -> str:
        """Get the last chapter string of the manga."""
        return self._last_chapter_string

    @classmethod
    def from_tuple(cls, data: tuple) -> "Manga":
        """Create a Manga object from a tuple."""
        return cls(*data)

    @classmethod
    def from_tuples(cls, data: list[tuple]) -> list["Manga"]:
        """Create a list of Manga objects from a list of tuples."""
        return [cls.from_tuple(d) for d in data] if data else []

    def to_tuple(self) -> tuple:
        """Convert a Manga object to a tuple."""
        return (
            self.id,
            self.human_name,
            self.manga_url,
            self.last_chapter_url_hash,
            self.last_chapter_string,
            self.completed,
            self.scanlator,
        )

    def __repr__(self) -> str:
        return f"Manga({self.human_name} - {self.last_chapter_string})"


class GuildSettings:
    def __init__(
        self,
        bot: MangaClient,
        guild_id: int,
        channel_id: int,
        updates_role_id: int,
        webhook_url: str,
        *args,
        **kwargs,
    ) -> None:
        self._bot: MangaClient = bot
        self.guild: discord.Guild = bot.get_guild(guild_id)
        self.channel: discord.TextChannel = self.guild.get_channel(channel_id)
        self.role: discord.Role = self.guild.get_role(updates_role_id)
        self.webhook: discord.Webhook = discord.Webhook.from_url(
            webhook_url, session=bot.session
        )
        self._args = args
        self._kwargs = kwargs

    @classmethod
    def from_tuple(cls, bot: MangaClient, data: tuple) -> "GuildSettings":
        return cls(bot, *data)

    @classmethod
    def from_tuples(cls, bot: MangaClient, data: list[tuple]) -> list["GuildSettings"]:
        return [cls.from_tuple(bot, d) for d in data] if data else []

    def to_tuple(self) -> tuple:
        """
        Returns a tuple containing the guild settings.
        >>> (guild_id, channel_id, updates_role_id, webhook_url)
        """
        return (
            self.guild.id,
            self.channel.id,
            self.role.id,
            self.webhook.url,
        )


class MangaUpdatesUtils:
    @staticmethod
    async def getMangaUpdatesID(
        session: aiohttp.ClientSession, manga_title: str
    ) -> str | None:
        """Scrape the series ID from MangaUpdates.com

        Returns:
            >>> str if found
            >>> None if not found
        """
        encoded_title = urllib.parse.quote(manga_title)
        async with session.get(
            f"https://www.mangaupdates.com/search.html?search={encoded_title}"
        ) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")

            series_info = soup.find("div", {"class": "col-6 py-1 py-md-0 text"})
            first_title = series_info.find("a")
            url = first_title["href"]
            _id = url.split("/")[-2]
            return _id

    @staticmethod
    async def is_series_completed(
        session: aiohttp.ClientSession, manga_id: str
    ) -> bool:
        """Check if the series is completed or not."""
        api_url = "https://api.mangaupdates.com/v1/series/{id}"

        async with session.get(api_url.format(id=manga_id)) as resp:
            if resp.status != 200:
                return None

            data = await resp.json()
            return data["completed"]


class RateLimiter:
    SCANLATORS: dict[str, ABCScan] = SCANLATORS
    _logger = logging.getLogger("RateLimiter")

    def __init__(self):
        self._last_request_times = {}

    @staticmethod
    def get_scanlator_key(manga: Manga):
        """
        Returns the scanlator key for a given Manga object, which corresponds to one of the keys in self.SCANLATORS.
        """
        return manga.scanlator

    async def delay_if_necessary(self, manga: Manga):
        """
        Delays the current coroutine if the previous request to the same scanlator was made not too long ago.
        """

        scanlators_to_ignore_rate_limits_for = ["mangadex"]

        scanlator_key = self.get_scanlator_key(manga)
        if scanlator_key in scanlators_to_ignore_rate_limits_for:
            return

        last_request_time = self._last_request_times.get(scanlator_key, None)

        if last_request_time is not None:
            time_since_last_request = time.monotonic() - last_request_time
            min_time_between_requests = self.SCANLATORS[
                scanlator_key
            ].MIN_TIME_BETWEEN_REQUESTS
            if time_since_last_request < min_time_between_requests:
                time_to_sleep = (
                    min_time_between_requests
                    - time_since_last_request
                    + random.uniform(0.5, 1.5)
                )
                self._logger.debug(
                    f"Delaying request to {scanlator_key} for {time_to_sleep} seconds."
                )
                await asyncio.sleep(time_to_sleep)

        self._last_request_times[scanlator_key] = time.monotonic()
