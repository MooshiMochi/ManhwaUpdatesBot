from __future__ import annotations

from typing import Any, TYPE_CHECKING

from ..static import Constants

if TYPE_CHECKING:
    from src.core.bot import MangaClient

from io import BytesIO
import os
from .errors import URLAccessFailed
import traceback as tb
from datetime import datetime
from typing import Optional
import aiohttp
import discord
from bs4 import BeautifulSoup
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
            extra_kwargs: list[dict[str, Any]] = None
    ):
        self.new_chapters = new_chapters
        self.new_cover_url = new_cover_url
        self.series_completed = series_completed
        self.extra_kwargs = extra_kwargs or []

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
        # return f"Chapter(url={self.url}, name={self.name}, index={self.index})"

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

    def __eq__(self, other: Chapter):
        if isinstance(other, Chapter):
            return self.url == other.url and other.name == self.name and other.index == self.index
        return False

    def __hash__(self):
        return hash((self.url, self.name, self.index))


class ABCScan(ABC):
    icon_url: str = None
    base_url: str = None
    fmt_url: str = None
    name: str = "Unknown"
    id_first: bool = False  # whether to extract ID first when using fmt_manga_url method
    rx: re.Pattern = None
    last_known_status: tuple[int, float] | None = None

    @classmethod
    def _make_headers(cls, bot: MangaClient, manga_id: str, manga_url: str):
        user_agent = bot.config.get('user-agents', {}).get(cls.name)
        headers: dict = Constants.default_headers()
        headers[":Authority"] = cls.base_url.removeprefix("https://")
        if not user_agent:
            return headers
        headers["User-Agent"] = user_agent
        return headers

    @classmethod
    async def report_error(cls, bot: MangaClient, error: Exception, **kwargs) -> None:
        """
        Summary:
            Reports an error to the bot logger and/or Discord.

        Args:
            bot: MangaClient - The bot instance.
            error: Exception - The error to report.
            **kwargs: Any - Any extra keyword arguments to pass to the logger.

        Returns:
            None
        """
        traceback = "".join(
            tb.format_exception(type(error), error, error.__traceback__)
        )
        # message: str = f"Error in {cls.name} scan: {traceback}"
        message: str = f"{traceback}\nError in {cls.name} scan.\nURL: {kwargs.pop('request_url', 'Unknown')}"
        if len(message) > 2000:
            file = discord.File(BytesIO(message.encode()), filename="error.txt")
            if not kwargs.get("file"):
                kwargs["file"] = file
            else:
                kwargs["files"] = [kwargs["file"], file]
                kwargs.pop("file")
                if len(kwargs["files"]) > 10:
                    kwargs["files"] = kwargs["files"][:10]
                    bot.logger.warning(
                        f"Too many files to attach to error message in {cls.name} scan."
                    )
                    bot.logger.error(message)
            message = f"Error in {cls.name} scan. See attached file or logs."
        try:
            await bot.log_to_discord(message, **kwargs)
        except AttributeError:
            bot.logger.critical(message)

    @staticmethod
    def _create_chapter_embed(
            scanlator_name: str, img_url: str, human_name: str, chapter_url: str, chapter_text: str
    ) -> discord.Embed:
        """
        Summary:
            Creates a chapter embed given the method parameters.

        Args:
            scanlator_name: str - The name of the scanlator.
            img_url: str - The URL to the chapter image.
            human_name: str - The human-readable name of the chapter.
            chapter_url: str - The URL to the chapter.
            chapter_text: str - The chapter text.

        Returns:
            discord.Embed - The chapter embed.
        """
        embed = discord.Embed(
            title=f"{human_name} - {chapter_text}",
            url=chapter_url)
        embed.set_author(name=scanlator_name)
        embed.description = f"Read {human_name} online for free on {scanlator_name}!"
        embed.set_image(url=img_url)
        return embed

    @staticmethod
    async def _fetch_image_bytes(bot: MangaClient, image_url: str) -> BytesIO:
        """
        Summary:
            Fetches the image bytes from the given URL.
        Args:
            bot: MangaClient - The bot instance.
            image_url: str - The URL to fetch the image from.

        Returns:
            BytesIO - The image bytes buffer.
        Note:
            If you want to re-use the bytes, make sure you call 'buffer.seek(0)' after reading it.
        """
        async with bot.session.get(image_url) as resp:
            if resp.status != 200:
                raise URLAccessFailed(image_url, resp.status)
            buffer = BytesIO(await resp.read())
            return buffer

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
    @abstractmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        """
        Summary:
            Gets the synopsis of the manga.

        Parameters:
            bot: MangaClient - The bot instance.
            manga_id: str - The ID of the manga.
            manga_url: str - The URL of the manga's home page.

        Returns:
            str - The synopsis of the manga.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
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
        chapters = await cls.get_all_chapters(bot, manga_id, manga_url)
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
        if not manga_id:
            manga_id = await cls.get_manga_id(bot, manga_url)
        db_object: Manga = await bot.db.get_series(manga_id)
        if db_object:
            return db_object

        manga_url = await cls.fmt_manga_url(bot, manga_id, manga_url)
        human_name = await cls.get_human_name(bot, manga_id, manga_url)
        synopsis = await cls.get_synopsis(bot, manga_id, manga_url)
        cover_url = await cls.get_cover_image(bot, manga_id, manga_url)
        curr_chapter = await cls.get_curr_chapter(bot, manga_id, manga_url)
        available_chapters = await cls.get_all_chapters(bot, manga_id, manga_url)
        is_completed = await cls.is_series_completed(bot, manga_id, manga_url)
        return_obj = Manga(
            manga_id,
            human_name,
            manga_url,
            synopsis,
            cover_url,
            curr_chapter,
            available_chapters,
            is_completed,
            cls.name,
        )
        await bot.db.add_series(return_obj)  # save to the database for future use.
        return return_obj

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
            synopsis: str,
            cover_url: str,
            last_chapter: Chapter,
            available_chapters: list[Chapter],
            completed: bool,
            scanlator: str,
    ) -> None:
        self._id: str = id
        self._human_name: str = human_name
        self._url: str = url
        self._synopsis: str = synopsis
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
            self._available_chapters = list(sorted(set(self._available_chapters), key=lambda x: x.index))

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
    def synopsis(self) -> str:
        """Get the synopsis of the manga."""
        return self._synopsis

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
            self.synopsis,
            self.cover_url,
            self.last_chapter.to_json() if self.last_chapter else None,
            self.chapters_to_text(),
            self.completed,
            self.scanlator,
        )

    def chapters_to_text(self) -> str:
        """Convert available_chapters to TEXT (db format)"""
        return json.dumps([x.to_dict() for x in self.available_chapters])

    def __repr__(self) -> str:
        return f"Manga({self.human_name} - {self.last_chapter.name})"

    def __eq__(self, other: Manga):
        if isinstance(other, Manga):
            return self.url == other.url and self.human_name == other.human_name or self.id == other.id
        return False


class Bookmark:
    def __init__(
            self,
            user_id: int,
            manga: Manga,
            last_read_chapter: Chapter,
            guild_id: int,
            last_updated_ts: float = None,
            user_created: bool = False,
    ):
        self.user_id: int = user_id
        self.manga: Manga = manga
        self.last_read_chapter: Chapter = last_read_chapter
        self.guild_id: int = guild_id
        if last_updated_ts is not None:
            self.last_updated_ts: float = float(last_updated_ts)
        else:
            self.last_updated_ts: float = datetime.utcnow().timestamp()

        self.user_created: bool = user_created

    @classmethod
    def from_tuple(cls, data: tuple) -> "Bookmark":
        """Create a Bookmark object from a tuple."""
        # 0 = user_id
        # 1 = manga
        # 2 = last_read_chapter
        # 3 = guild_id
        # 4 = last_updated_ts
        # 5 = user_created
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
            self.user_created,
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
        if self.guild:
            self.channel: discord.TextChannel = self.guild.get_channel(channel_id)
            self.role: Optional[discord.Role] = self.guild.get_role(updates_role_id)
        else:
            self.channel: Optional[discord.TextChannel] = None
            self.role: Optional[discord.Role] = None
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
        >>> (Guild_id, channel_id, updates_role_id, webhook_url)
        """
        return (
            self.guild.id,
            self.channel.id,
            self.role.id if hasattr(self.role, "id") else None,
            self.webhook.url,
        )


class CachedResponse:
    """
    A class that patches the response of an aiohttp.ClientResponse to work with
    the cache system.

    Note: the .apply_patch() method must be called before using the response object.

    Example:
    >>> async with aiohttp.ClientSession() as session:
    >>>     async with session.get("https://example.com") as response:
    >>>         cached_response = await CachedResponse(response).apply_patch()
    >>>         await cached_response.json()
    """

    def __init__(self, response: aiohttp.ClientResponse):
        self._response = response
        self._data_dict = {}
        self._original_methods = {
            "json": response.json,
            "text": response.text,
            "read": response.read,
        }

    async def try_return(self, key: str):
        stored = self._data_dict.get(key)

        if stored is None:
            try:
                self._data_dict[key] = {"content": await self._original_methods[key](), "type": "data"}
                stored = self._data_dict[key]
            except Exception as e:
                self._data_dict[key] = {"type": "error", "content": e}
                if isinstance(e, aiohttp.ContentTypeError):
                    self._write_maybe_403()
                stored = self._data_dict[key]

        if stored["type"] == "error":
            if isinstance(stored["content"], aiohttp.ContentTypeError):
                self._write_maybe_403()
            raise stored["content"]
        else:
            return stored["content"]

    def _write_maybe_403(self):
        print("Received a potential 403 error when attempting to decode JSON.")
        folder = "logs/403s"
        if not os.path.exists(folder):
            os.makedirs(folder)
        filename = folder + "/" + str(len(os.listdir(folder))) + ".html"

        with open(filename, "w") as f:
            f.write(self._data_dict.get("text"))
        # print(self._data_dict.get("text"))  # log the text response if it's from mangadex for future debugs

    async def json(self):
        return await self.try_return("json")

    async def text(self):
        return await self.try_return("text")

    async def read(self):
        return await self.try_return("read")

    async def _async_init(self):
        keys = ["json", "text", "read"]
        for key in keys:
            try:
                self._data_dict[key] = {"content": await self._original_methods[key](), "type": "data"}
            except Exception as e:
                self._data_dict[key] = {"type": "error", "content": e}
        return self

    async def apply_patch(self, preload_data: bool = False):
        if preload_data:
            await self._async_init()

        attributes = [("_data_dict", self._data_dict), ("json", self.json), ("text", self.text), ("read", self.read)]
        for attr, value in attributes:
            setattr(self._response, attr, value)
        return self._response
