from __future__ import annotations

import urllib
from asyncio import TimeoutError
from typing import TYPE_CHECKING, Iterable, Union, Any

if TYPE_CHECKING:
    from src.core.bot import MangaClient

import traceback as tb
from datetime import datetime
from typing import Optional
import aiohttp
import discord
from bs4 import BeautifulSoup
from discord.ext.commands import Context
from discord.ext.commands import Paginator as CommandPaginator

from abc import ABC, abstractmethod
import hashlib
import re
import json


class ChapterUpdate:
    def __init__(
            self,
            new_chapters: list[Chapter],
            new_cover_url: Optional[str] = None,
            series_completed: bool = False,
            *extra_kwargs: list[dict[str, Any]]
    ):
        self.new_chapters = new_chapters
        self.new_cover_url = new_cover_url
        self.series_completed = series_completed
        self.extra_kwargs = extra_kwargs

    def __repr__(self):
        return f"UpdateResult({len(self.new_chapters)} new chapters, series_completed={self.series_completed})"


class Chapter:
    def __init__(self, url: str, name: str, index: int):
        self.url = url
        self.name = self._fix_chapter_string(name)
        self.index = index

    @staticmethod
    def _fix_chapter_string(chapter_string: str) -> str:
        """Fixes the chapter string to be more readable."""
        result = chapter_string.replace("\n", " ").replace("Ch.", "Chapter")
        return re.sub(r"\s+", " ", result).strip()

    def __repr__(self):
        return f"[{self.name}]({self.url})"

    def to_dict(self):
        return {
            "url": self.url,
            "name": self.name,
            "index": self.index
        }

    def to_json(self):
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    @classmethod
    def from_many_dict(cls, data: list[dict]):
        return [cls.from_dict(d) for d in data]

    @classmethod
    def from_json(cls, data):
        return cls.from_dict(json.loads(data))

    @classmethod
    def from_many_json(cls, data: str):
        return [cls.from_dict(d) for d in json.loads(data)]


class ABCScan(ABC):
    MIN_TIME_BETWEEN_REQUESTS = 1.0  # In seconds
    icon_url: str = None
    base_url: str = None
    fmt_url: str = None
    name: str = "Unknown"

    @classmethod
    def _make_headers(cls, bot: MangaClient):
        user_agent = bot.config['user-agents'].get(cls.name)
        if not user_agent:
            return {}
        return {"User-Agent": user_agent}

    @classmethod
    async def report_error(cls, bot: MangaClient, error: Exception, **kwargs) -> None:
        traceback = "".join(
            tb.format_exception(type(error), error, error.__traceback__)
        )
        # message: str = f"Error in {cls.name} scan: {traceback}"
        message: str = f"{traceback}\nError in {cls.name} scan.\nURL: {kwargs.get('request_url', 'Unknown')}"
        try:
            await bot.log_to_discord(message, **kwargs)
        except AttributeError:
            bot.logger.critical(message)

    @classmethod
    def extract_error_code_n_message(cls, text: str) -> tuple[int | str, str] | None:
        """Extracts the status code and error message from the webpage text."""
        soup = BeautifulSoup(text, "html.parser")
        page_title = soup.find("title")
        if page_title is None:
            return None
        page_title = page_title.text
        re_result = re.search(r"(\b\d{3}): (\w* \w*\b)", page_title)
        if re_result:
            status_code, error_message = re_result.groups()
            try:
                return int(status_code), error_message
            except ValueError:
                return status_code, error_message
        return None

    @classmethod
    @abstractmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            manga: Manga,
            _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        """
        Summary:
            Checks whether any new releases have appeared on the scanlator's website.
            Checks whether the series is completed or not.

        Parameters:
            bot: MangaClient - The bot instance.
            manga: Manga - The manga object to check for updates.
            _manga_request_url: str - The URL to request the manga's page.

        Returns:
            ChapterUpdate - The update result.

        Raises:
            MangaNotFound - If the manga is not found in the scanlator's website.
            URLAccessFailed - If the scanlator's website is blocked by Cloudflare.
        """
        request_url = _manga_request_url or manga.url
        try:
            all_chapters = await cls.get_all_chapters(bot, manga.id, request_url)
            completed: bool = await cls.is_series_completed(bot, manga.id, manga.url)
            cover_url: str = await cls.get_cover_image(bot, manga.id, manga.url)
            if all_chapters is None:
                return ChapterUpdate([], cover_url, completed)
            new_chapters: list[Chapter] = [
                chapter for chapter in all_chapters if chapter.index > manga.last_chapter.index
            ]
            return ChapterUpdate(new_chapters, cover_url, completed)
        except (ValueError, AttributeError) as e:
            await cls.report_error(bot, e, request_url=request_url)
        except Exception as e:
            raise e

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """
        Summary:
            Checks whether a series is completed or not.

        Parameters:
            soup: BeautifulSoup - The soup object to check the series status.

        Returns:
            bool - `True` if the series is completed, otherwise `False`.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        """
        Summary:
            Checks whether a series is completed/dropped or not.

        Parameters:
            bot: MangaClient - The bot instance.
            manga_id: str - The ID of the manga.
            manga_url: str - The URL of the manga's home page.

        Returns:
            bool - `True` if the series is completed/dropped, otherwise `False`.

        Raises:
            MangaNotFound - If the manga is not found in the scanlator's website.
            URLAccessFailed - If the scanlator's website is blocked by Cloudflare.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str:
        """
        Summary:
            Gets the human-readable name of the manga.

        Parameters:
            bot: MangaClient - The bot instance.
            manga_id: str - The ID of the manga.
            manga_url: str - The URL of the manga's home page.

        Returns:
            str - The human-readable name of the manga.

        Raises:
            MangaNotFound - If the manga is not found in the scanlator's website.
            URLAccessFailed - If the scanlator's website is blocked by Cloudflare.
        """
        raise NotImplementedError

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        """
        Summary:
            Gets the ID of the manga.

        Parameters:
            bot: MangaClient - The bot instance.
            manga_url: str - The URL of the manga.

        Returns:
            str - The ID of the manga.
        """
        return hashlib.sha256(manga_url.encode()).hexdigest()

    @classmethod
    @abstractmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        """
        Summary:
            Gets the current chapter text of the manga.

        Parameters:
            bot: MangaClient - The bot instance.
            manga_id: str - The ID of the manga.
            manga_url: str - The URL of the manga's home page.

        Returns
            Chapter/None - The current chapter text of the manga.
        """
        chapters = (await cls.get_all_chapters(bot, manga_id, manga_url))
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    async def make_manga_object(cls, bot: MangaClient, manga_id: str, manga_url: str) -> Manga | None:
        """
        Summary:
            Creates a Manga object from the scanlator's website.

        Parameters:
            bot: MangaClient - The bot instance.
            manga_id: str - The ID of the manga.
            manga_url: str - The URL of the manga's home page.

        Returns:
            Manga/None - The Manga object if the manga is found, otherwise `None`.
        """
        manga_url = await cls.fmt_manga_url(bot, manga_id, manga_url)
        human_name = await cls.get_human_name(bot, manga_id, manga_url)
        cover_url = await cls.get_cover_image(bot, manga_id, manga_url)
        curr_chapter = await cls.get_curr_chapter(bot, manga_id, manga_url)
        available_chapters = await cls.get_all_chapters(bot, manga_id, manga_url)
        is_completed = await cls.is_series_completed(bot, manga_id, manga_url)
        return Manga(
            manga_id,
            human_name,
            manga_url,
            cover_url,
            curr_chapter,
            available_chapters,
            is_completed,
            cls.name,
        )

    @classmethod
    async def make_bookmark_object(
            cls,
            bot: MangaClient,
            manga_id: str,
            manga_url: str,
            user_id: int,
            guild_id: int
    ) -> Bookmark | None:
        """
        Summary:
            Creates a Bookmark object from the scanlator's website.

        Parameters:
            bot: MangaClient - The bot instance.
            manga_id: str - The ID of the manga.
            manga_url: str - The URL of the manga's home page.
            user_id: int - The ID of the user.
            guild_id: int - The ID of the guild.

        Returns:
            Bookmark/None - The Bookmark object if the manga is found, otherwise `None`.
        """
        manga_url = await cls.fmt_manga_url(bot, manga_id, manga_url)
        manga_id = await cls.get_manga_id(bot, manga_url)
        manga = await cls.make_manga_object(bot, manga_id, manga_url)
        if manga is None:
            return None

        if manga.available_chapters:
            last_read_chapter = manga.available_chapters[0]
        else:
            last_read_chapter = None

        return Bookmark(
            user_id,
            manga,
            last_read_chapter,  # last_read_chapter
            guild_id,
            datetime.utcnow().timestamp(),
        )

    @classmethod
    @abstractmethod
    async def fmt_manga_url(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        """
        Summary:
            Creates the home page URL of the manga using the class format.
        Parameters:
            bot: MangaClient - The bot instance.
            manga_id: str - The ID of the manga.
            manga_url: str - The URL of the manga's home page.

        Returns:
            str - The home page URL of the manga.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def get_all_chapters(cls, bot: MangaClient, manga_id: str, manga_url: str) -> list[Chapter] | None:
        """
        Summary:
            Gets all the chapters of the manga.

        Parameters:
            bot: MangaClient - The bot instance.
            manga_id: str - The ID of the manga.
            manga_url: str - The URL of the manga's home page.

        Returns:
            list[Chapter]/None - A list of Chapter objects (lowest to highest) if the manga is found, otherwise `None`.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def get_cover_image(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str | None:
        """
        Summary:
            Gets the cover image of the manga.

        Parameters:
            bot: MangaClient - The bot instance.
            manga_id: str - The ID of the manga.
            manga_url: str - The URL of the manga's home page.

        Returns:
            str/None - The cover image URL of the manga.
        """
        raise NotImplementedError


class PaginatorView(discord.ui.View):
    def __init__(
            self,
            items: list[Union[str, int, discord.Embed]] = None,
            interaction: Union[discord.Interaction, Context] = None,
            timeout: float = 3 * 3600  # 3 hours
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

        elif not all(isinstance(item, (str, int, discord.Embed)) for item in items):
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
            chunks.append(text[i: i + self._max_size - 300])
        return chunks


class Manga:
    def __init__(
            self,
            id: str,
            human_name: str,
            url: str,
            cover_url: str,
            last_chapter: Chapter,
            available_chapters: list[Chapter],
            completed: bool,
            scanlator: str,
    ) -> None:
        self._id: str = id
        self._human_name: str = human_name
        self._url: str = url
        self._cover_url: str = cover_url
        self._last_chapter: Chapter = last_chapter
        self._available_chapters: list[Chapter] = available_chapters
        if isinstance(last_chapter, str):
            self._last_chapter: Chapter = Chapter.from_json(last_chapter)
        if isinstance(available_chapters, list):
            if len(available_chapters) > 0 and isinstance(available_chapters[0], str):
                self._available_chapters: list[Chapter] = [
                    Chapter.from_json(chapter) for chapter in available_chapters
                ]
        elif isinstance(available_chapters, str):
            self._available_chapters: list[Chapter] = Chapter.from_many_json(available_chapters)

        self._completed: bool = completed
        self._scanlator: str = scanlator

    def update(
            self,
            new_latest_chapter: Chapter = None,
            completed: bool = None,
            new_cover_url: str = None,
    ) -> None:
        """Update the manga."""
        if new_latest_chapter is not None:
            self._last_chapter = new_latest_chapter
            self._available_chapters.append(new_latest_chapter)
            self._available_chapters = list(set(self._available_chapters))

        if completed is not None:
            self._completed = completed
        if new_cover_url is not None:
            self._cover_url = new_cover_url

    @property
    def id(self) -> str:
        """Get the database ID of the manga."""
        return self._id

    @property
    def human_name(self) -> str:
        """Get the name of the manga."""
        return self._human_name

    @property
    def url(self) -> str:
        """Get the URL of the manga.
        Example: https://toonily.net/webtoon/what-do-i-do-now/
        """
        return self._url

    @property
    def cover_url(self) -> str:
        """Get the cover URL of the manga."""
        return self._cover_url

    @property
    def last_chapter(self) -> Chapter:
        """Get the last chapter of the manga."""
        return self._last_chapter

    @property
    def available_chapters(self) -> list[Chapter]:
        """Get the available chapters of the manga."""
        return self._available_chapters

    @property
    def completed(self) -> bool:
        """Get the status of the manga."""
        return self._completed

    @property
    def scanlator(self) -> str:
        """Get the scanlator of the manga."""
        return self._scanlator

    # @property
    # def last_chapter_string(self) -> str:
    #     """Get the last chapter string of the manga."""
    #     return self._last_chapter_string

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
            self.url,
            self.cover_url,
            self.last_chapter.to_json(),
            json.dumps([x.to_dict() for x in self.available_chapters]),
            self.completed,
            self.scanlator,
        )

    def __repr__(self) -> str:
        return f"Manga({self.human_name} - {self.last_chapter.name})"


class Bookmark:
    def __init__(
            self,
            user_id: int,
            manga: Manga,
            last_read_chapter: Chapter,
            guild_id: int,
            last_updated_ts: float = None,
    ):
        self.user_id: int = user_id
        self.manga: Manga = manga
        self.last_read_chapter: Chapter = last_read_chapter
        self.guild_id: int = guild_id
        self.last_updated_ts: float = float(last_updated_ts)

    @classmethod
    def from_tuple(cls, data: tuple) -> "Bookmark":
        """Create a Bookmark object from a tuple."""
        # 0 = user_id
        # 1 = manga
        # 2 = last_read_chapter
        # 3 = guild_id
        # 4 = last_updated_ts
        last_read_chapter: Chapter = Chapter.from_dict(json.loads(data[2]))
        parsed_data = list(data)
        parsed_data[2] = last_read_chapter
        return cls(*parsed_data)

    @classmethod
    def from_tuples(cls, data: list[tuple]) -> list["Bookmark"]:
        """Create a list of Bookmark objects from a list of tuples."""
        return [cls.from_tuple(d) for d in data] if data else []

    def to_tuple(self) -> tuple:
        """Convert a Bookmark object to a tuple."""
        return (
            self.user_id,
            self.manga.id,
            self.last_read_chapter.to_json(),
            self.guild_id,
            self.last_updated_ts,
        )

    async def delete(self, bot: MangaClient) -> bool:
        """Delete the bookmark from the database."""
        return await bot.db.delete_bookmark(self.user_id, self.manga.id)

    async def update_last_read_chapter(self, bot: MangaClient, chapter: Chapter) -> bool:
        """Update the last read chapter of the bookmark."""
        self.last_read_chapter = chapter
        self.last_updated_ts = datetime.utcnow().timestamp()
        return await bot.db.upsert_bookmark(self)

    def __repr__(self) -> str:
        return f"Bookmark({self.user_id} - {self.manga.human_name} - {self.manga.id})"


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
        self.role: Optional[discord.Role] = self.guild.get_role(updates_role_id)
        self.webhook: discord.Webhook = discord.Webhook.from_url(
            webhook_url, session=bot.session, client=bot
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
            self.role.id if hasattr(self.role, "id") else None,
            self.webhook.url,
        )


class MangaUpdatesUtils:
    @staticmethod
    async def getMangaUpdatesID(
            session: aiohttp.ClientSession, manga_title: str
    ) -> str | None:
        """Scrape the series ID from CommandsCog.com

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
