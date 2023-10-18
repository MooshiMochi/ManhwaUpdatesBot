from __future__ import annotations

from typing import Any, TYPE_CHECKING

from ..static import Constants

if TYPE_CHECKING:
    from src.core.bot import MangaClient

import os
from datetime import datetime
from typing import Optional
import aiohttp
import discord
from discord.ext.commands import Paginator as CommandPaginator
import re
import json


class ChapterUpdate:
    def __init__(
            self,
            manga_id: str,
            new_chapters: list[Chapter],
            scanlator: str,
            new_cover_url: Optional[str] = None,
            status: str = "Ongoing",
            extra_kwargs: list[dict[str, Any]] = None,
    ):
        self.manga_id = manga_id
        self.new_chapters = new_chapters
        self.new_cover_url = new_cover_url
        self.status = status
        self.extra_kwargs = extra_kwargs or []
        self.scanlator = scanlator

    def __repr__(self):
        return (
            f"ChapterUpdate({len(self.new_chapters)} new chapters, "
            f"status={self.status} | {[x.url for x in self.new_chapters]})"
        )

    def __str__(self):
        return f"ChapterUpdate(new_chapters: {len(self.new_chapters)}, status: {self.status})"

    @property
    def is_completed(self):
        return self.status is not None and self.status.lower() in Constants.completed_status_set


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
        return f"[{{{self.index}}}|{self.name}]({self.url})"
        # return f"Chapter(url={self.url}, name={self.name}, index={self.index})"

    def __str__(self):
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

    def __eq__(self, other: Chapter):
        if isinstance(other, Chapter):
            return self.url == other.url and other.name == self.name and other.index == self.index
        return False

    def __hash__(self):
        return hash((self.url, self.name, self.index))


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
                for line in converted_lines:  # noqa
                    pages.add_line(line)
        self.pages = pages

    def getPages(self, *, page_number=True):
        """Gets the pages."""
        pages = []
        pagenum = 1  # noqa
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


class PartialManga:
    def __init__(
            self,
            manga_id: str,
            title: str,
            url: str,
            scanlator: str,
            cover_url: Optional[str] = None,
            latest_chapters: list[Chapter] = None,
            actual_url: Optional[str] = None,
    ):
        self._id = manga_id
        self._title = title
        self._url = url
        self._scanlator = scanlator
        self._cover_url = cover_url
        self._latest_chapters: list[Chapter] | None = latest_chapters
        self._actual_url = actual_url

    def __repr__(self):
        if self._latest_chapters:
            latest_chapter_text = [f"{chp.name}" for chp in self._latest_chapters]
        else:
            latest_chapter_text = "N/A"
        return f"PartialManga({self._title}{{{self.url}}}] - {latest_chapter_text})"

    def __str__(self):
        return f"[{self.title}]({self._url})"

    def __eq__(self, other: Manga):
        return isinstance(other, (Manga, PartialManga)) and (
                self.url == other.url and
                self.title == other.title or
                self.id == other.id and
                self.scanlator == other.scanlator
        )

    @property
    def id(self):
        return self._id

    @property
    def title(self):
        return self._title

    @property
    def url(self):
        return self._url

    @property
    def scanlator(self):
        return self._scanlator

    @property
    def cover_url(self):
        return self._cover_url

    @property
    def latest_chapters(self):
        return self._latest_chapters

    @property
    def actual_url(self):
        return self._actual_url


class Manga:
    def __init__(
            self,
            id: str,
            title: str,
            url: str,
            synopsis: str,
            cover_url: str,
            last_chapter: Chapter,
            available_chapters: list[Chapter],
            status: str,
            scanlator: str,
    ) -> None:
        self._id: str = id
        self._title: str = title
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

        self._status: str = status
        self._scanlator: str = scanlator

    def copy(self) -> "Manga":
        return Manga.from_tuple(self.to_tuple())

    def update(
            self,
            new_latest_chapter: Chapter = None,
            status: str = None,
            new_cover_url: str = None,
    ) -> None:
        """Update the manga."""
        if new_latest_chapter is not None:
            self._last_chapter = new_latest_chapter
            self._available_chapters.append(new_latest_chapter)
            self._available_chapters = list(sorted(set(self._available_chapters), key=lambda x: x.index))

        if status is not None:
            self._status = status
        if new_cover_url is not None:
            self._cover_url = new_cover_url

    @property
    def id(self) -> str:
        """Get the database ID of the manga."""
        return self._id

    @property
    def title(self) -> str:
        """Get the title of the manga."""
        return self._title

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
    def last_chapter(self) -> Chapter | None:
        """Get the last chapter of the manga."""
        return self._last_chapter

    @property
    def available_chapters(self) -> list[Chapter]:
        """Get the available chapters of the manga."""
        return self._available_chapters

    @property
    def status(self):
        return self._status

    @property
    def completed(self) -> bool:
        """Get the status of the manga."""
        return self._status.lower() in Constants.completed_status_set

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
            self.title,
            self.url,
            self.synopsis,
            self.cover_url,
            self.last_chapter.to_json() if self.last_chapter else None,
            self.chapters_to_text(),
            self.status,
            self.scanlator,
        )

    def chapters_to_text(self) -> str:
        """Convert available_chapters to TEXT (db format)"""
        return json.dumps([x.to_dict() for x in self.available_chapters] if self.available_chapters else [])

    def get_display_embed(self, scanlators: dict):
        _scanlator = scanlators[self.scanlator]
        cover_url = (
            self.cover_url if _scanlator.json_tree.properties.can_render_cover else Constants.no_img_available_url
        )
        em = discord.Embed(title=self.title, url=self.url)
        em.set_image(url=cover_url)
        em.set_author(
            icon_url=_scanlator.json_tree.properties.icon_url,
            name=_scanlator.name,
            url=_scanlator.json_tree.properties.base_url
        )
        synopsis_text = self.synopsis
        if synopsis_text:
            if len(synopsis_text) > 1024:
                extra = f"... [(read more)]({self.url})"
                len_url = len(extra)
                synopsis_text = synopsis_text[: 1024 - len_url] + extra
            em.add_field(name="Synopsis:", value=synopsis_text, inline=False)

        scanlator_text = f"[{self.scanlator.title()}]({_scanlator.json_tree.properties.base_url})"
        desc = f"**Num of Chapters:** {len(self.available_chapters)}\n"
        desc += f"**Status:** {self.status}\n"
        desc += f"**Latest Chapter:** {(self.available_chapters or 'N/A')[-1]}\n"
        desc += f"**First Chapter:** {(self.available_chapters or 'N/A')[0]}\n"
        desc += f"**Scanlator:** {scanlator_text}"
        em.description = desc
        return em

    def __repr__(self) -> str:
        if self._last_chapter:
            last_chapter_text = self._last_chapter.name
        else:
            last_chapter_text = "None"
        return f"Manga({self.title} - {last_chapter_text})"

    def __str__(self) -> str:
        return f"[{self.title}]({self.url})"

    def __eq__(self, other: Manga):
        return isinstance(other, (Manga, PartialManga)) and (
                self.url == other.url and
                self.title == other.title or
                self.id == other.id and
                self.scanlator == other.scanlator
        )


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
            self.last_updated_ts: float = datetime.now().timestamp()
        self.user_created: bool = bool(user_created)

    @classmethod
    def from_tuple(cls, data: tuple) -> "Bookmark":
        """Create a Bookmark object from a tuple."""
        # 0 = user_id
        # 1 = manga
        # 2 = last_read_chapter_index
        # 3 = guild_id
        # 4 = last_updated_ts
        # 5 = user_created
        last_read_chapter: Chapter = data[1].available_chapters[data[2]]
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
            self.last_read_chapter.index,
            self.guild_id,
            self.last_updated_ts,
            bool(self.user_created),
            self.manga.scanlator
        )

    async def delete(self, bot: MangaClient) -> bool:
        """Delete the bookmark from the database."""
        return await bot.db.delete_bookmark(self.user_id, self.manga.id, self.manga.scanlator)

    async def update_last_read_chapter(self, bot: MangaClient, chapter: Chapter) -> bool:
        """Update the last read chapter of the bookmark."""
        self.last_read_chapter = chapter
        self.last_updated_ts = datetime.now().timestamp()
        return await bot.db.upsert_bookmark(self)

    def __repr__(self) -> str:
        return f"Bookmark({self.user_id} - {self.manga.title} - {self.manga.id})"


class GuildSettings:
    def __init__(
            self,
            bot: MangaClient,
            guild_id: int,
            notifications_channel_id: int,
            default_ping_role_id: int,
            auto_create_role: bool = False,
            dev_notifications_ping: bool = True,
            show_update_buttons: bool = True,
            *args,
            **kwargs,
    ) -> None:
        self._bot: MangaClient = bot
        self.guild: discord.Guild = bot.get_guild(guild_id)
        if self.guild:
            self.notifications_channel: discord.TextChannel = self.guild.get_channel(notifications_channel_id)
            self.default_ping_role: Optional[discord.Role] = self.guild.get_role(default_ping_role_id)
        else:
            self.notifications_channel: Optional[discord.TextChannel] = None
            self.default_ping_role: Optional[discord.Role] = None
        self.auto_create_role: bool = bool(auto_create_role)
        self.dev_notifications_ping: bool = bool(dev_notifications_ping)
        self.show_update_buttons: bool = bool(show_update_buttons)
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
        """
        return (
            self.guild.id,
            self.notifications_channel.id,
            self.default_ping_role.id if self.default_ping_role else None,
            1 if self.auto_create_role else 0,
            1 if self.dev_notifications_ping else 0,
            1 if self.show_update_buttons else 0,
        )


class CachedResponse:
    """
    A class that patches the response of an aiohttp.ClientResponse to work with
    the cache system.

    Note: the .apply_patch() method must be called before using the response object.

    Example:
    >>> async with aiohttp.ClientSession() as session:
    >>>     async with session.get("https://example.com") as response:
    >>>         cached_response = await CachedResponse(response).apply_patch()  # noqa
    >>>         await cached_response.json()  # noqa
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

        text = self._data_dict.get("text")
        if text is None:
            return
        else:
            with open(filename, "w", encoding="utf8") as f:
                if isinstance(text, str):
                    f.write(text)
                else:
                    f.write(json.dumps(text))
            print("Wrote 403 response to " + filename)
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

        attributes = [("_data_dict", self._data_dict), ("text", self.text), ("json", self.json), ("read", self.read)]
        for attr, value in attributes:
            setattr(self._response, attr, value)
        return self._response
