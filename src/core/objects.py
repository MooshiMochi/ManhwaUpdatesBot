from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..enums import BookmarkFolderType
from ..static import Constants, Emotes

if TYPE_CHECKING:
    from src.core.bot import MangaClient

from datetime import datetime
from typing import Optional
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
            status_changed: bool = False,
            extra_kwargs: list[dict[str, Any]] = None,

    ):
        self.manga_id = manga_id
        self.new_chapters = new_chapters
        self.scanlator = scanlator
        self.new_cover_url = new_cover_url
        self.status = status
        self.status_changed: bool = status_changed
        self.extra_kwargs = extra_kwargs or []

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
    def __init__(self, url: str, name: str, index: int, is_premium: bool = False, *args, **kwargs):
        # def __init__(self, url: str, name: str, index: int, *args, **kwargs):
        self.url = url
        self.name = self._fix_chapter_string(name)
        self.index = index
        self.is_premium = is_premium
        self.args: tuple[Any, ...] = args
        self.kwargs: dict[str, Any] = kwargs

    @staticmethod
    def _fix_chapter_string(chapter_string: str) -> str:
        """Fixes the chapter string to be more readable."""
        result = chapter_string.replace("\n", " ").replace("Ch.", "Chapter")
        return re.sub(r"\s+", " ", result).strip()

    def __repr__(self):
        return f"[{{{self.index}}}|{self.name}]({self.url})"
        # return f"Chapter(url={self.url}, name={self.name}, index={self.index})"

    def __str__(self):
        if self.is_premium:
            return f"[{self.name} {Emotes.lock}]({self.url})"
        return f"[{self.name}]({self.url})"

    def to_dict(self):
        return {
            "url": self.url,
            "name": self.name,
            "index": self.index,
            "is_premium": self.is_premium,
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
            return (
                    self.url == other.url and
                    other.name == self.name and
                    other.index == self.index and
                    self.is_premium == other.is_premium
            )
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
        self._id = str(manga_id)
        self._title = title
        self._url = url
        self._scanlator = scanlator
        self._cover_url = cover_url
        self._latest_chapters: list[Chapter] | None = latest_chapters
        self._actual_url = actual_url

    def __repr__(self):
        if self._latest_chapters:
            latest_chapter_text = [f"{('🔒' if chp.is_premium else '') + chp.name}" for chp in self._latest_chapters]
        else:
            latest_chapter_text = "N/A"
        return f"PartialManga({self._title}{{{self.url}}}] - {latest_chapter_text})"

    def __str__(self):
        return f"[{self.title}]({self._url})"

    def __eq__(self, other: Manga):
        return (
                isinstance(other, (Manga, PartialManga)) and self.url == other.url and self.title == other.title
                or
                isinstance(other, MangaHeader)
        ) and self.id == other.id and self.scanlator == other.scanlator

    @property
    def id(self) -> str:
        return self._id

    @property
    def title(self) -> str:
        return self._title

    @property
    def url(self) -> str:
        return self._url

    @property
    def scanlator(self) -> str:
        return self._scanlator

    @property
    def cover_url(self) -> str:
        return self._cover_url

    @property
    def latest_chapters(self) -> list[Chapter] | None:
        return self._latest_chapters

    @property
    def actual_url(self) -> str:
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
            chapters: list[Chapter],
            status: str,
            scanlator: str,
    ) -> None:
        self._id: str = id
        self._title: str = title
        self._url: str = url
        self._synopsis: str = synopsis
        self._cover_url: str = cover_url
        self._last_chapter: Chapter = last_chapter
        self._chapters: list[Chapter] = chapters
        if isinstance(last_chapter, str):
            self._last_chapter: Chapter = Chapter.from_json(last_chapter)
        if isinstance(chapters, list):
            if len(chapters) > 0 and isinstance(chapters[0], str):
                self._chapters: list[Chapter] = [
                    Chapter.from_json(chapter) for chapter in chapters
                ]
        elif isinstance(chapters, str):
            self._chapters: list[Chapter] = Chapter.from_many_json(chapters)

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
            # If the chapter already exists (i.e. the index is within the current list),
            # update it; otherwise, append it.
            if new_latest_chapter.index < len(self._chapters):
                # Only update if the premium status is different
                if new_latest_chapter.is_premium != self._chapters[new_latest_chapter.index].is_premium:
                    self._chapters[new_latest_chapter.index] = new_latest_chapter
            else:
                self._chapters.append(new_latest_chapter)
            # Update the last chapter (you might instead want to compute the maximum by index)
            self._last_chapter = new_latest_chapter
            # Remove duplicates and sort by chapter index
            self._chapters = list(sorted(set(self._chapters), key=lambda x: x.index))

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
    def chapters(self) -> list[Chapter]:
        """Get the available chapters of the manga."""
        return self._chapters

    @property
    def status(self):
        return self._status

    @property
    def completed(self) -> bool:
        """Returns True if the manga is marked as completed on the website."""
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
        obj = cls(*data)
        obj._check_and_fix_chapters_index()
        return obj

    @classmethod
    def from_tuples(cls, data: list[tuple]) -> list["Manga"]:
        """Create a list of Manga objects from a list of tuples."""
        return [cls.from_tuple(d) for d in data] if data else []

    def to_tuple(self) -> tuple:
        """Convert a Manga object to a tuple."""
        self._check_and_fix_chapters_index()
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

    def _check_and_fix_chapters_index(self) -> None:
        """
        This method will check and fix chapter indices given the condition:
        - last_chapter.index != len(chapters) - 1 or
        - manga.chapters[-1].index != len(chapters) - one
        Returns:
            None
        """
        should_fix = False
        if not self._last_chapter and not self._chapters:
            return
        if not self._last_chapter and self._chapters:
            self._last_chapter = self._chapters[-1]
            should_fix = True
        elif self._last_chapter and not self._chapters:
            self._last_chapter = None
            return
        if self._last_chapter.index != len(self._chapters) - 1:
            should_fix = True
        elif self._chapters[-1].index != len(self._chapters) - 1:
            should_fix = True

        if not should_fix:
            return
        # Fix the chapters
        for i, chapter in enumerate(self._chapters):
            chapter.index = i
        self._last_chapter = self._chapters[-1]

    def chapters_to_text(self) -> str:
        """Convert available_chapters to TEXT (db format)"""
        return json.dumps([x.to_dict() for x in self.chapters] if self.chapters else [])

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
        desc = f"**Num of Chapters:** {len(self.chapters)}\n"
        desc += f"**Status:** {self.status}\n"
        desc += f"**Latest Chapter:** {(self.chapters or 'N/A')[-1]}\n"
        desc += f"**First Chapter:** {(self.chapters or 'N/A')[0]}\n"
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
        return (
                isinstance(other, (Manga, PartialManga)) and self.url == other.url and self.title == other.title
                or
                isinstance(other, MangaHeader)
        ) and self.id == other.id and self.scanlator == other.scanlator


class Bookmark:
    def __init__(
            self,
            user_id: int,
            manga: Manga,
            last_read_chapter: Chapter,
            guild_id: int,
            last_updated_ts: float = None,
            folder: BookmarkFolderType = BookmarkFolderType.Reading,
    ):
        self.user_id: int = user_id
        self.manga: Manga = manga
        self.last_read_chapter: Chapter = last_read_chapter
        self.guild_id: int = guild_id
        if last_updated_ts is not None:
            self.last_updated_ts: float = float(last_updated_ts)
        else:
            self.last_updated_ts: float = datetime.now().timestamp()
        self.folder = folder

    @classmethod
    def from_tuple(cls, data: tuple) -> "Bookmark":
        """Create a Bookmark object from a tuple."""
        # 0 = user_id
        # 1 = manga
        # 2 = last_read_chapter_index
        # 3 = guild_id
        # 4 = last_updated_ts
        # 5 = folder
        last_read_chapter: Chapter = data[1].chapters[data[2]]
        parsed_data = list(data)
        parsed_data[2] = last_read_chapter
        parsed_data[5] = BookmarkFolderType(data[5])
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
            self.manga.scanlator,
            self.folder.value,
        )

    async def delete(self, bot: MangaClient) -> bool:
        """Delete the bookmark from the database."""
        return await bot.db.delete_bookmark(self.user_id, self.manga.id, self.manga.scanlator)

    async def update_last_read_chapter(self, bot: MangaClient, chapter: Chapter) -> bool:
        """Update the last read chapter of the bookmark."""
        self.last_read_chapter = chapter
        self.last_updated_ts = datetime.now().timestamp()
        return await bot.db.upsert_bookmark(self)

    async def move_to_folder(self, bot: MangaClient, new_folder: BookmarkFolderType) -> bool:
        """Move the bookmark to a different folder"""
        self.folder = new_folder
        return await bot.db.upsert_bookmark(self)

    def __repr__(self) -> str:
        return f"Bookmark({self.user_id} - {self.manga.title} - {self.manga.id})"


class DMSettings:
    def __init__(
            self,
            bot: MangaClient,
            *args,
            **kwargs,
    ) -> None:
        """

        Args:
            bot: MangaClient - The bot instance
            args[0] -> user_id: int - The user ID
            args[1..4] -> arbitrary values, they aren't considered
            args[5] -> show_update_buttons: bool - Whether to show the buttons view on a chapter update
            args[6] -> paid_chapter_notifs: bool - Whether to receive notifications for premium chapters.
            **kwargs:
        """
        self._bot: MangaClient = bot
        self.user_id: int = args[0]
        if len(args) >= 6:
            self.show_update_buttons: bool = bool(args[5])
        else:
            self.show_update_buttons: bool = True
        if len(args) >= 7:
            self.paid_chapter_notifs: bool = bool(args[6])
        else:
            self.paid_chapter_notifs: bool = False

    @classmethod
    def from_tuple(cls, bot: MangaClient, data: tuple) -> "DMSettings":
        return cls(bot, data[0], show_update_buttons=data[5], paid_chapter_notifs=data[6])

    @classmethod
    def from_tuples(cls, bot: MangaClient, data: list[tuple]) -> list["DMSettings"]:
        return [cls.from_tuple(bot, d) for d in data] if data else []

    def to_tuple(self) -> tuple:
        return (
            self.user_id,
            None,  # notif channel
            None,  # default ping role
            0,  # auto create role
            None,  # system channel
            self.show_update_buttons,
            self.paid_chapter_notifs,
            None  # bot manager role ID
        )


class GuildSettings:
    def __init__(
            self,
            bot: MangaClient,
            guild_id: int,
            notifications_channel_id: int,
            default_ping_role_id: int,
            auto_create_role: bool = False,
            system_channel: int | None = None,
            show_update_buttons: bool = True,
            paid_chapter_notifs: bool = False,
            bot_manager_role: int | None = None,
            *args,
            **kwargs,
    ) -> None:
        self._bot: MangaClient = bot
        self.guild: discord.Guild = bot.get_guild(guild_id)
        self.default_ping_role_id = default_ping_role_id
        if self.guild:
            self.notifications_channel: Optional[discord.TextChannel] = self.guild.get_channel(notifications_channel_id)
            self.default_ping_role: Optional[discord.Role] = self.guild.get_role(default_ping_role_id)
            self.bot_manager_role: Optional[discord.Role] = self.guild.get_role(bot_manager_role)
            self.system_channel: Optional[discord.TextChannel] = self.guild.get_channel(system_channel)
        else:
            self.notifications_channel: Optional[discord.TextChannel] = None
            self.default_ping_role: Optional[discord.Role] = None
            self.bot_manager_role: Optional[discord.Role] = None
            self.system_channel: Optional[discord.TextChannel] = None
        self.auto_create_role: bool = bool(auto_create_role)
        self.show_update_buttons: bool = bool(show_update_buttons)
        self.paid_chapter_notifs: bool = bool(paid_chapter_notifs)
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
            self.notifications_channel.id if self.notifications_channel else None,
            self.default_ping_role.id if self.default_ping_role else None,
            1 if self.auto_create_role else 0,
            self.system_channel.id if self.system_channel else None,
            1 if self.show_update_buttons else 0,
            1 if self.paid_chapter_notifs else 0,
            self.bot_manager_role.id if self.bot_manager_role else None,

        )


@dataclass
class Patron:
    email: str
    user_id: int | None
    first_name: str
    last_name: str

    def __post_init__(self):
        self.user_id = int(self.user_id) if self.user_id else None

    def to_tuple(self) -> tuple[str, int | None, str, str]:
        return self.email, int(self.user_id) if self.user_id else None, self.first_name, self.last_name

    @classmethod
    def from_tuple(cls, data: tuple[str, int | None, str, str]) -> "Patron":
        return cls(*data)

    @classmethod
    def from_tuples(cls, data: list[tuple[str, int | None, str, str]]) -> list["Patron"]:
        return [cls.from_tuple(d) for d in data] if data else []


@dataclass
class SubscriptionObject:
    user_id: int
    guild_id: int
    manga_id: str
    scanlator: str
    role: discord.Role | None

    def to_tuple(self) -> tuple[int, str, int, str]:
        return self.user_id, self.manga_id, self.guild_id, self.scanlator

    @classmethod
    async def sub_to_all(
            cls, bot: MangaClient, sub_objects: list["SubscriptionObject"]
    ) -> tuple[int, int] | None:
        """
        Summary: Subscribes the user to all tracked series in the server.

        Args:
            bot: The bot instance
            sub_objects: The list of SubscriptionObjects

        Returns:
            tuple[int, int] - (num_success_added_roles, num_failed_add_roles)
        """

        user_id = sub_objects[0].user_id
        guild_id = sub_objects[0].guild_id
        is_dm_invoked = user_id == guild_id
        if is_dm_invoked:
            return len(sub_objects), 0

        config = await bot.db.get_guild_config(guild_id)
        user = config.guild.get_member(user_id)
        num_target_subs = len(sub_objects)

        if not config.default_ping_role:
            roles_to_add: list[discord.Role] = list(filter(
                lambda y: y is not None and y not in user.roles, map(lambda x: x.role, sub_objects)
            ))
            unassignable_roles = [x for x in roles_to_add if not x.is_assignable()]
            num_failed_subs = len(unassignable_roles)

            await user.add_roles(
                *filter(lambda x: x not in unassignable_roles, roles_to_add),
                reason=f"Subscribed to {num_target_subs - num_failed_subs} tracked series")
            database_entries = list(filter(
                lambda x: x.role is None or x.role not in unassignable_roles, sub_objects
            ))
            await bot.db.subscribe_user_to_tracked_series(database_entries)
            return num_target_subs - num_failed_subs, num_failed_subs
        else:
            await user.add_roles(config.default_ping_role, reason="Subscribed to all trakced series.")
            await bot.db.subscribe_user_to_tracked_series(sub_objects)
            # await bot.db.subscribe_user_to_all_tracked_series(user_id, guild_id)
            return num_target_subs, 0

    @classmethod
    async def unsub_from_all(cls, bot: MangaClient, sub_objects: list["SubscriptionObject"]
                             ) -> tuple[int, int] | None:
        """
        Summary: Unsubscriebe the user from all subsribed series in the server.

        Args:
            bot: The bot instance
            sub_objects: The list of SubscriptionObjects

        Returns:
            tuple[int, int] - (num_success_removed_roles, num_failed_removed_roles)
        """
        user_id = sub_objects[0].user_id
        guild_id = sub_objects[0].guild_id
        is_dm_invoked = user_id == guild_id
        if is_dm_invoked:
            return len(sub_objects), 0

        config = await bot.db.get_guild_config(guild_id)
        user = config.guild.get_member(user_id)
        num_target_unsubs = len(sub_objects)

        # if not config.default_ping_role:
        roles_to_remove: list[discord.Role] = list(filter(
            lambda y: y is not None and y in user.roles, map(lambda x: x.role, sub_objects)
        ))
        if config.default_ping_role and config.default_ping_role in user.roles:
            roles_to_remove.append(config.default_ping_role)

        unassignable_roles = [x for x in roles_to_remove if not x.is_assignable()]
        num_failed_subs = len(unassignable_roles)

        await user.remove_roles(
            *filter(lambda x: x not in unassignable_roles, roles_to_remove),
            reason=f"Unsubscribed from {num_target_unsubs - num_failed_subs} subbed series")
        database_entries = list(filter(
            lambda x: x.role is None or x.role not in unassignable_roles, sub_objects
        ))
        await bot.db.unsubscribe_user_to_tracked_series(database_entries)
        return num_target_unsubs - num_failed_subs, num_failed_subs
        # else:
        #     await user.remove_roles(config.default_ping_role, reason="Unsubscribed from all subbed series.")
        #     await bot.db.unsubscribe_user_to_tracked_series(sub_objects)
        #     return num_target_unsubs, 0


@dataclass
class MangaHeader:
    id: str
    scanlator: str

    def __eq__(self, other: Manga | MangaHeader) -> bool:
        return isinstance(
            other, (MangaHeader, PartialManga, Manga)
        ) and self.id == other.id and self.scanlator == other.scanlator


@dataclass
class ScanlatorChannelAssociation:
    bot: MangaClient
    guild_id: int
    scanlator: str
    channel_id: int

    guild: discord.Guild | None = field(default=None, init=False)
    channel: discord.TextChannel | None = field(default=None, init=False)

    def __post_init__(self):
        self.guild = self.bot.get_guild(self.guild_id)
        self.channel = self.guild.get_channel(self.channel_id) if self.guild else None

    def to_tuple(self) -> tuple[int, str, int]:
        return self.guild_id, self.scanlator, self.channel_id

    @classmethod
    def from_tuple(cls, bot: MangaClient, data: tuple[int, str, int]) -> "ScanlatorChannelAssociation":
        return cls(bot, *data)

    @classmethod
    def from_tuples(cls, bot: MangaClient, data: list[tuple[int, str, int]]) -> list["ScanlatorChannelAssociation"]:
        return [cls.from_tuple(bot, d) for d in data] if data else []

    async def delete(self) -> bool:
        return await self.bot.db.delete_scanlator_channel_association(self.guild_id, self.scanlator)

    async def upsert(self) -> bool:
        return await self.bot.db.upsert_scanlator_channel_association(self)

    async def get_channel(self) -> discord.TextChannel | None:
        guild = self.bot.get_guild(self.guild_id)
        return guild.get_channel(self.channel_id) if guild else None

    @classmethod
    async def upsert_many(cls, bot: MangaClient, data: list["ScanlatorChannelAssociation"]) -> None:
        await bot.db.upsert_scanlator_channel_associations(data)

    @classmethod
    async def delete_many(cls, data: list["ScanlatorChannelAssociation"]) -> None:
        for d in data:
            await d.delete()

    def __hash__(self):
        return hash((self.guild_id, self.scanlator, self.channel_id))

    def __repr__(self):
        return f"ScanlatorChannelAssociation({self.guild.name} [{self.guild_id}] - {self.scanlator} - {self.channel_id})"

    def __eq__(self, other):
        return (
                isinstance(other, ScanlatorChannelAssociation) and
                self.guild_id == other.guild_id and
                self.scanlator == other.scanlator and
                self.channel_id == other.channel_id
        )
