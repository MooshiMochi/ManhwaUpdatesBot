from __future__ import annotations

import hashlib
import os
import re
import traceback
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from typing import Literal, Optional, TYPE_CHECKING
from urllib.parse import quote_plus as url_encode

import bs4
import discord
from bs4 import BeautifulSoup, Tag
from discord.utils import MISSING

from src.enums import BookmarkFolderType
from src.utils import raise_and_report_for_status, time_string_to_seconds

if TYPE_CHECKING:
    from src.core import MangaClient, MissingUserAgentError

from src.core.objects import Bookmark, Chapter, ChapterUpdate, Manga, PartialManga
from src.static import Constants
from abc import ABC, abstractmethod

import json

import sys
from .json_tree import JSONTree

root_path = [x for x in sys.path if x.removesuffix("/").endswith("ManhwaUpdatesBot")][0]

__all__ = (
    "AbstractScanlator",
    "BasicScanlator",
    "NoStatusBasicScanlator",
    "DynamicURLScanlator",
    "DynamicURLNoStatusScanlator",
    "scanlators"
)


class _AbstractScanlatorUtilsMixin:
    @staticmethod
    def extract_cover_link_from_tag(tag, base_url: str) -> str | None:
        for attr in ["data-src", "src", "style", "href", "content", "data-lazy-src"]:
            result = tag.get(attr)
            if result is not None:
                if result.startswith("/"):  # partial URL, we just need to append base URL to it
                    return base_url + result
                elif not result.startswith("https://"):
                    if attr == 'style':
                        url_rx = re.compile(
                            r'https?://(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9]{1,6}\b([-a-zA-Z0-9@:%_+.~#?&/=]*)')
                        result = url_rx.search(result).group()
                        if result is not None:
                            return result
                        else:
                            continue
                    end_result = result.split(".")[-1]
                    for extension in ["jpg", "png", "jpeg", "webp", "gif", "svg", "apng"]:
                        if end_result.startswith(extension):
                            return "/".join([base_url.removesuffix("/"), result.removeprefix("/")])
                    continue
                return result

    @staticmethod
    def remove_unwanted_tags(soup: BeautifulSoup, unwanted_selectors: list[str]):
        if not unwanted_selectors:
            return
        for tag in soup.select(",".join(unwanted_selectors)):
            tag.extract()

    @staticmethod
    async def _get_status_tag(self: BasicScanlator, raw_url: str) -> bs4.Tag | None:
        if self.json_tree.properties.no_status:
            method = "POST" if self.json_tree.uses_ajax else "GET"
            if not isinstance(self, DynamicURLScanlator):
                request_url = await self.format_manga_url(raw_url, use_ajax_url=True)
            else:
                request_url = raw_url
            text = await self._get_text(request_url, method=method)  # noqa
        else:

            text = await self._get_text(
                await self.format_manga_url(raw_url) if not isinstance(self, DynamicURLScanlator) else raw_url)
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        status_selectors = self.json_tree.selectors.status
        for selector in status_selectors:
            status = soup.select_one(selector)
            if status is not None:
                return status
        return None


class AbstractScanlator(ABC):
    bot: MangaClient
    json_tree: JSONTree
    _raw_kwargs: dict

    def __init__(self, name: str):  # noqa: Invalid scope warning
        self.name: str = name

    def create_chapter_embed(
            self, manga: PartialManga | Manga, chapter: Chapter, image_url: Optional[str] = None
    ) -> discord.Embed | None:
        """
        Summary:
            Creates a chapter embed given the method parameters.

        Args:
            manga: PartialManga/Manga - The manga object to create the embed from.
            chapter: Chapter - The chapter object to create the embed from.
            image_url: str - The image URL to use for the embed.

        Returns:
            discord.Embed - The chapter embed.
            None if cls.requires_embed_for_chapter_updates is False
        """
        if not self.json_tree.properties.requires_update_embed:
            return None
        embed = discord.Embed(
            title=f"{manga.title} - {chapter.name}",
            url=chapter.url)
        embed.set_author(
            name=self.name.title(),
            url=self.json_tree.properties.base_url,
            icon_url=self.json_tree.properties.icon_url
        )
        embed.description = f"Read {manga.title} online for free on {self.name.title()}!"
        if self.json_tree.properties.can_render_cover:
            embed.set_image(url=manga.cover_url if not image_url else image_url)
        else:
            embed.set_image(url=Constants.no_img_available_url)
        return embed

    def partial_manga_to_embed(self, partial_mangas: list[PartialManga]) -> list[discord.Embed]:
        embeds: list[discord.Embed] = []
        for p_manga in partial_mangas:
            em = discord.Embed(title=p_manga.title, url=p_manga.url)
            em.set_image(url=p_manga.cover_url or Constants.no_img_available_url)
            em.set_author(
                icon_url=self.json_tree.properties.icon_url, name=self.name, url=self.json_tree.properties.base_url
            )
            embeds.append(em)
        return embeds

    @abstractmethod
    async def get_title(self, raw_url: str) -> str:
        """
        Gets the title of the manhwa

        Args:
            raw_url: str - The URL of the manhwa to request

        Returns:
            str - The title of the manhwa
        """
        raise NotImplementedError

    @abstractmethod
    async def get_id(self, raw_url: str) -> str:
        """
        Gets the ID of the manhwa.
        This is usually the encoded 'manga_url' part from the raw_url param

        Args:
            raw_url: str - The URL of the manhwa to request

        Returns:
            str - The ID of the manhwa
        """
        raise NotImplementedError

    @abstractmethod
    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        """
        Gets all the chapters a manhwa has

        Args:
            raw_url: The URL of the manhwa to request

        Returns:
            list[Chapter] - A list of Chapter objects in order (first > last)
        """
        raise NotImplementedError

    @abstractmethod
    async def get_status(self, raw_url: str) -> str:
        """
        Gets the status of the manhwa

        Args:
            raw_url: str - The URL of the manhwa to request

        Returns:
            str - The status of the manhwa
        """
        raise NotImplementedError

    @abstractmethod
    async def get_synopsis(self, raw_url: str) -> str:
        """
        Gets the synopsis/description of the manhwa

        Args:
            raw_url: str - The URL of the manhwa to request

        Returns:
            str - The synopsis/description of the manhwa
        """
        raise NotImplementedError

    @abstractmethod
    async def get_cover(self, raw_url: str) -> str:
        """
        Gets the cover URL of the manhwa

        Args:
            raw_url: str - The URL of the manhwa to request

        Returns:
            str - The manhwa's cover URL
        """
        raise NotImplementedError

    @abstractmethod
    async def get_fp_partial_manga(self) -> list[PartialManga]:
        """
        Gets the manhwa on the front page of the website (where the latest chapters are listed)

        Returns:
            list[PartialManga] - A list of PartialManga objects
        """
        raise NotImplementedError

    @abstractmethod
    async def format_manga_url(
            self, raw_url: Optional[str] = None, url_name: Optional[str] = None, _id: Optional[str] = None
    ) -> str:  # noqa: Other implementations require 'self'
        """
        Uses the user-provided manga url to format a consistent URL based on the format_url defined in the JSONTree

        Args:
            raw_url: Optional[str] - The URL of the manhwa to request
            url_name: Optional[str] - The url_name of the manhwa to request
            _id: Optional[str] - The ID of the manhwa to request

        Returns:
            str - The formatted manga URL

        Note:
            At least one of the required arguments must be provided
        """
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        """
        Searches the website for results on your 'query'

        Args:
            query: str - The string to search for
            as_em: bool - Whether to return the results as Embeds or PartialManga objects

        Returns:
            list[PartialManga] - A list of PartialManga objects containing search results
        """
        raise NotImplementedError

    @abstractmethod
    def check_ownership(self, raw_url: str) -> bool:
        """
        Checks whether the manhwa URL belongs to the current scanlator or not using the regex pattern

        Args:
            raw_url: str - The manhwa url to check

        Returns:
            bool - True or False
        """
        raise NotImplementedError

    async def load_manga(self, mangas: list[Manga]) -> list[Manga]:  # noqa: Other implementations require 'self'
        """
        *For Dynamic URL Websites*
        Sets the manga_id and chapter_id in the URLs of the Manga object

        Args:
            mangas: list[Manga] - The manga objects to set the IDs for

        Returns:
            list[Manga] - The objects with the new manga_id and chapter_id set for all URLs

        Notes:
            These properties contain a chapter/manga ID:
            - Manga.url
            - Manga.latest_chapter.url
            - Manga.available_chapters > Chapter.url
        """
        return mangas

    # @abstractmethod
    # async def download_cover(self, raw_url: str) -> BytesIO:
    #     """
    #     Downloads the cover image of the manga and save it in a local filestystem on the VPS.
    #
    #     Args:
    #         raw_url: str - The URL of the manga to request
    #
    #     Returns:
    #         BytesIO - The cover image of the manga as a BytesIO object
    #     """

    async def unload_manga(self, mangas: list[Manga | PartialManga]) -> list[
        Manga | PartialManga]:  # noqa: Other implementations require 'self'
        """
        *For Dynamic URL Websites*
        Replaces the manga_id and chapter_id in the URLs of the Manga object with a placeholder

        Args:
            mangas: list[Manga | PartialManga] - The manga objects to replace the IDs for

        Returns:
            list[Manga | PartialManga] - The objects with placeholders for IDs set for all URLs

        Notes:
            These properties contain a chapter/manga ID:
            - Manga.url
            - Manga.latest_chapter.url
            - Manga.available_chapters > Chapter.url
            - Manga.latest_chapters [.url for each chapter] for PartialManga objects
        """
        return mangas

    async def make_manga_object(self, raw_url: str, load_from_db: bool = True) -> Manga | None:
        manga_id = await self.get_id(raw_url)

        # load from database if exists.
        if load_from_db is True:
            manga_obj = await self.bot.db.get_series(manga_id, self.name)
            if manga_obj is not None:
                return manga_obj

        # load from website
        all_chapters = await self.get_all_chapters(raw_url)
        manga_obj = Manga(
            manga_id,
            await self.get_title(raw_url),
            await self.format_manga_url(raw_url),
            await self.get_synopsis(raw_url),
            await self.get_cover(raw_url),
            (all_chapters or [None])[-1],
            all_chapters,
            await self.get_status(raw_url),
            self.name
        )
        return manga_obj

    async def make_bookmark_object(
            self,
            raw_url: str,
            user_id: int,
            guild_id: int,
            folder: BookmarkFolderType = BookmarkFolderType.Subscribed,
    ) -> Bookmark | None:
        """
        Creates a Bookmark object from the scanlator's website.

        Parameters:
            raw_url: str - The URL of the manga's home page.
            user_id: int - The ID of the user.
            guild_id: int - The ID of the guild.
            folder: BookmarkFolderType - The folder in which to place this bookmark.

        Returns:
            Bookmark/None - The Bookmark object if the manga is found, otherwise `None`.
        """
        manga = await self.make_manga_object(raw_url)
        if manga is None:
            return None

        if manga.chapters:
            last_read_chapter = manga.chapters[0]
        else:
            last_read_chapter = None

        return Bookmark(
            user_id,
            manga,
            last_read_chapter,  # last_read_chapter
            guild_id,
            datetime.now().timestamp(),
            folder
        )

    async def check_updates(
            self,
            manga: Manga,
    ) -> ChapterUpdate:
        """
        Summary:
            Checks whether any new releases have appeared on the scanlator's website.
            Checks whether the series is completed or not.

        Parameters:
            manga: Manga - The manga object to check for updates.

        Returns:
            ChapterUpdate - The update result.

        Raises:
            MangaNotFoundError - If the manga is not found in the scanlator's website.
            URLAccessFailed - If the scanlator's website is blocked by Cloudflare.
        """
        all_chapters = await self.get_all_chapters(manga.url)
        status: str = await self.get_status(manga.url)
        cover_url: str = await self.get_cover(manga.url)
        status_changed: bool = status != manga.status
        if all_chapters is None:
            return ChapterUpdate(manga.id, [], manga.scanlator, cover_url, status, status_changed)
        if manga.last_chapter:
            new_chapters: list[Chapter] = [
                chapter for chapter in all_chapters if chapter.index > manga.last_chapter.index
            ]
            # chapters that were previously premium and are now free.
            spoiled_chapters = [c for i, c in enumerate(all_chapters) if
                                not c.is_premium and  # only care about them if they're free on the website
                                i < len(manga.chapters) and  # only care about chapters that are also in the db.
                                manga.chapters[i].is_premium  # only care about paid chapters from the db
                                ]
            for chapter in spoiled_chapters:
                # add a flag to the chapter to indicate that it was previously premium.
                # this is used when notifications for new releases are being sent out.
                chapter.kwargs["was_premium"] = True

            # below is the same as: new_chapters = spoiled_chapters + new_chapters
            spoiled_chapters.extend(new_chapters)
            new_chapters = spoiled_chapters

        else:
            new_chapters: list[Chapter] = all_chapters
        return ChapterUpdate(
            manga.id, new_chapters, manga.scanlator, cover_url, status, status_changed,
            extra_kwargs=[
                {"embed": self.create_chapter_embed(manga, chapter, cover_url)}
                for chapter in new_chapters
            ] if self.json_tree.properties.requires_update_embed else None
        )

    async def report_error(
            self,
            error: Exception,
            *,
            request_url: str = "not provided",
            **kwargs) -> None:  # noqa: Invalid scope warning
        """
        Summary:
            Reports an error to the bot logger and/or Discord.

        Args:
            error: Exception - The error to report.
            request_url: str - The URL that was requested which led to the error
            **kwargs: Any - Any extra keyword arguments to pass to channel.send() function.

        Returns:
            None
        """
        caller_func = traceback.extract_stack(limit=2)[0].name
        tb = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        message: str = f"Error in {self.name.capitalize()}.{caller_func}.\nURL: {request_url}\n\n{tb}"
        if len(message) > 2000:
            file = discord.File(BytesIO(message.encode()), filename="error.txt")
            if not kwargs.get("file"):
                kwargs["file"] = file
            else:
                kwargs["files"] = [kwargs["file"], file]
                kwargs.pop("file")
                if len(kwargs["files"]) > 10:
                    kwargs["files"] = kwargs["files"][:10]
                    self.bot.logger.warning(
                        f"Too many files to attach to error message in {self.name} scan."
                    )
                    self.bot.logger.error(message)
            message = f"Error in {self.name.capitalize()}.{caller_func}. See attached file or logs."
        try:
            await self.bot.log_to_discord(message, **kwargs)
        except AttributeError:
            self.bot.logger.critical(message)


class BasicScanlator(AbstractScanlator, _AbstractScanlatorUtilsMixin):

    def __init__(self, name, **kwargs):  # noqa: Invalid scope warning
        self.name = name
        self.json_tree = JSONTree(**kwargs)
        self._raw_kwargs = kwargs
        super().__init__(name)

    def create_headers(self) -> dict | None:
        headers = self.json_tree.custom_headers.headers
        user_agents_config = self.bot.config.get("user-agents")
        if user_agents_config is None:
            return headers or None  # defaults to None if headers is an empty dict
        user_agent = user_agents_config.get(self.name, MISSING)
        if user_agent is MISSING:
            return headers or None
        elif user_agent is None:
            raise MissingUserAgentError(self.name)
        else:
            headers["User-Agent"] = user_agent
        return headers or None

    def get_extra_req_kwargs(self) -> dict:
        extra_kwargs = {}
        if self.json_tree.custom_headers.cookies is not None:
            extra_kwargs["cookies"] = self.json_tree.custom_headers.cookies
        return extra_kwargs

    async def _get_text(self, url: str, method: Literal["GET", "POST"] = "GET", **params) -> str:
        request_method = self.json_tree.request_method
        if "overwrite_req_method" in params:
            request_method = params.pop("overwrite_req_method")

        provided_headers = params.pop("headers", None)
        if not provided_headers: provided_headers = {}  # noqa: Allow inline operation
        headers = ((self.create_headers() or {}) | provided_headers) or None
        if request_method == "curl":
            if self.json_tree.verify_ssl is False:
                params["verify"] = False
            resp = await self.bot.session.request(
                method, url, headers=headers, **self.get_extra_req_kwargs(), **params
            )
            await raise_and_report_for_status(self.bot, resp)
            return resp.text
        elif request_method == "fox":
            resp = await self.bot.fox_session.get(url, headers=headers, **params)
            await raise_and_report_for_status(self.bot, resp)
            return resp.text
        else:
            raise ValueError(f"Unknown {request_method} request method.")

    # async def download_cover(self, raw_url: str) -> BytesIO:
    #     cover_url = await self.get_cover(raw_url)
    #     cover = await self._get_text(cover_url)
    #     return BytesIO(cover.encode())

    async def format_manga_url(
            self, raw_url: Optional[str] = None, url_name: Optional[str] = None, _id: Optional[str] = None,
            *, use_ajax_url: bool = False
    ) -> str:
        if not any([raw_url is not None, url_name is not None, _id is not None]):
            raise ValueError("At least one of the arguments must be provided.")
        if raw_url is not None:
            url_name = await self._get_url_name(raw_url)
            _id = await self.get_id(raw_url)
        if use_ajax_url and self.json_tree.uses_ajax:
            fmt_url = self.json_tree.properties.format_urls.ajax.format(url_name=url_name, id=_id)
        else:
            fmt_url = self.json_tree.properties.format_urls.manga.format(url_name=url_name, id=_id)
        if url_name is None:
            fmt_url = fmt_url.removesuffix("None" if not fmt_url.endswith("None/") else "None/")
        return fmt_url

    async def _get_url_name(self, raw_url: str) -> str:
        try:
            return self.json_tree.rx.search(raw_url).groupdict().get("url_name")
        except (AttributeError, TypeError) as e:
            self.bot.logger.error(raw_url)
            raise e

    def check_ownership(self, raw_url: str) -> bool:
        try:
            return self.json_tree.rx.search(raw_url) is not None
        except (AttributeError, TypeError) as e:
            self.bot.logger.error(raw_url)
            raise e

    async def get_id(self, raw_url: str) -> str:
        try:
            url_id = self.json_tree.rx.search(raw_url).groupdict().get("id")
        except (AttributeError, TypeError) as e:
            self.bot.logger.error(raw_url)
            raise e
        if url_id is None or self.json_tree.properties.dynamic_url is True:
            key = await self._get_url_name(raw_url)
            return hashlib.sha256(key.encode()).hexdigest()
        return url_id

    async def get_title(self, raw_url: str) -> str | None:
        if not isinstance(self, DynamicURLScanlator):
            raw_url = await self.format_manga_url(raw_url)
        text = await self._get_text(raw_url)

        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        selectors = self.json_tree.selectors.title
        for selector in selectors:
            title = soup.select_one(selector)
            if title:
                if selector.endswith("]") and "=" not in selector:
                    return title.get(selector.split("[")[-1].removesuffix("]"))
                else:
                    return title.get_text(strip=True)

    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        if not isinstance(self, DynamicURLScanlator):
            raw_url = await self.format_manga_url(raw_url, use_ajax_url=True)
        method = "POST" if self.json_tree.uses_ajax else "GET"
        text = await self._get_text(raw_url, method=method)  # noqa
        url_name = await self._get_url_name(raw_url)
        return self._extract_chapters_from_html(text, url_name)

    def _build_paid_chapter_url(self, tag: Tag, url_name: str, _tools) -> str:
        if _tools.string_selector == "_container_":
            value = tag.get_text()
        else:
            value = tag.select_one(_tools.string_selector).get_text()
        chapter_part_url = _tools.regex.search(value).groupdict().get("num")
        if chapter_part_url is None:
            raise ValueError(f"Failed to get premium chapter for {url_name} of {self.name}")
        fmt_info = {"base_url": self.json_tree.properties.base_url.removesuffix('/'),
                    "url_name": url_name,
                    "ch_part": chapter_part_url
                    }
        url_result = _tools.url_fmt
        for sub_key, sub_val in list(fmt_info.items()):
            if "{" + sub_key + "}" not in url_result:
                del fmt_info[sub_key]
        url = _tools.url_fmt.format(**fmt_info)
        return url

    def _extract_chapters_from_html(self, text: str, url_name: str = None) -> list[Chapter]:
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        chapter_selector = self.json_tree.selectors.chapters
        chapters: list[Tag] = soup.select(chapter_selector.container)
        found_chapters: list[Chapter] = []
        for i, chapter in enumerate(reversed(chapters)):
            # ------- extracting whether the chapter is premium or not -------
            premium_selector = self.json_tree.selectors.chapters.premium_status
            is_premium = False
            if premium_selector is not None:
                is_premium = chapter.select_one(premium_selector) is not None
            # ------- extracting chapter url -------
            if chapter_selector.url == "_container_":
                url = chapter.get("href")
            else:
                url = chapter.select_one(chapter_selector.url).get("href")
            if (_tools := self.json_tree.selectors.chapters.no_premium_chapter_url) is not None and is_premium is True:
                url = self._build_paid_chapter_url(chapter, url_name, _tools)
            if not url.startswith(self.json_tree.properties.base_url):
                if self.json_tree.properties.url_chapter_prefix is not None:
                    url = self.json_tree.properties.base_url + self.json_tree.properties.url_chapter_prefix + url
                else:
                    if self.json_tree.properties.missing_id_connector.exists:
                        url = self.json_tree.properties.base_url.removesuffix(
                            "/") + self.json_tree.properties.missing_id_connector.char + "/" + url.removeprefix("/")
                    else:
                        url = self.json_tree.properties.base_url.removesuffix("/") + "/" + url.removeprefix("/")
            # ------- extracting chapter name -------
            if chapter_selector.name == "_container_":
                name = chapter.get_text().replace("\n", " ")  # noqa: Invalid scope warning
            else:
                name = chapter.select_one(chapter_selector.name).get_text().replace("\n",  # noqa: Invalid scope warning
                                                                                    " ")

            found_chapters.append(Chapter(url, name, i, is_premium))
        return found_chapters

    async def get_status(self, raw_url: str) -> Optional[str]:
        status_tag = await self._get_status_tag(self, raw_url)
        if status_tag:
            status_text = status_tag.get_text(strip=True)
            return re.sub(r"\W", "", status_text).lower().removeprefix("status").strip().title()

    async def get_synopsis(self, raw_url: str) -> Optional[str]:
        if not isinstance(self, DynamicURLScanlator):
            raw_url = await self.format_manga_url(raw_url)
        text = await self._get_text(raw_url)
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        synopsis_selector = self.json_tree.selectors.synopsis
        synopsis = soup.select_one(synopsis_selector)
        if synopsis:
            return synopsis.get_text(strip=True, separator="\n")

    async def get_cover(self, raw_url: str) -> Optional[str]:
        if not isinstance(self, DynamicURLScanlator):
            raw_url = await self.format_manga_url(raw_url)
        text = await self._get_text(raw_url)
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        selectors = self.json_tree.selectors.cover
        for selector in selectors:
            cover_tag = soup.select_one(selector)
            if cover_tag:
                cover_url = self.extract_cover_link_from_tag(cover_tag, self.json_tree.properties.base_url)
                # this is mainly bc of asura
                start_idx = max(0, cover_url.rfind(self.json_tree.properties.base_url))
                return cover_url[start_idx:].replace(" ", "%20")

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        text = await self._get_text(self.json_tree.properties.latest_updates_url)
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)
        manga_tags: list[Tag] = soup.select(self.json_tree.selectors.front_page.container)

        found_manga: list[PartialManga] = []
        for manga_tag in manga_tags:
            url = manga_tag.select_one(self.json_tree.selectors.front_page.url).get("href")
            if not url.startswith("https://"):
                url = self.json_tree.properties.base_url.removesuffix("/") + "/" + url.removeprefix("/")
            url_name = await self._get_url_name(url)
            _title_selector = self.json_tree.selectors.front_page.title  # noqa: Invalid scope warning
            if _title_selector == "_container_":
                name = manga_tag.get_text(strip=True)  # noqa: Invalid scope warning
            else:
                title_tag = manga_tag.select_one(_title_selector)
                if _title_selector.endswith("]") and "=" not in _title_selector:
                    name = title_tag.get(  # noqa: Invalid scope warning
                        _title_selector.split("[")[-1].removesuffix("]"))
                else:
                    name = title_tag.get_text(strip=True)  # noqa: Invalid scope warning

            cover_url = self.extract_cover_link_from_tag(
                manga_tag.select_one(self.json_tree.selectors.front_page.cover),
                self.json_tree.properties.base_url
            )
            start_idx = max(0, cover_url.rfind(self.json_tree.properties.base_url))
            cover_url = cover_url[start_idx:]

            chapters: Optional[list[Chapter]] = None
            # The reason we allow optional chapters for FP is that some websites may not have chapters on the FP,
            # or the website has premium chapters,
            # but they don't tell us on the front page, so, we make chapters
            # optional.
            # That way, if the manga is on the FP, we know it has an update, so it will do an individual check
            # for the chapters.
            if self.json_tree.selectors.front_page.chapters is not None:
                chapter_tags: list[Tag] = manga_tag.select(self.json_tree.selectors.front_page.chapters.container)
                chapters = []

                for i, ch_tag in enumerate(reversed(chapter_tags)):
                    # ------- extracting chapter name -------
                    if self.json_tree.selectors.front_page.chapters.name == "_container_":
                        ch_name = ch_tag.get_text(strip=True)
                    else:
                        ch_name = ch_tag.select_one(self.json_tree.selectors.front_page.chapters.name)
                        if ch_name is not None:
                            ch_name = ch_name.get_text(strip=True)
                        else:
                            continue
                    # ------- extracting whether the chapter is premium or not -------
                    premium_selector = self.json_tree.selectors.front_page.chapters.premium_status
                    is_premium = False
                    if premium_selector is not None:
                        is_premium = ch_tag.select_one(premium_selector) is not None

                    # ------- extracting chapter url -------
                    if self.json_tree.selectors.front_page.chapters.url == "_container_":
                        ch_url = ch_tag.get("href")
                    else:
                        ch_url = ch_tag.select_one(self.json_tree.selectors.front_page.chapters.url).get("href")
                    if (
                            is_premium is True and
                            (_tools := self.json_tree.selectors.front_page.chapters.no_premium_chapter_url) is not None
                    ):
                        url = self._build_paid_chapter_url(ch_tag, url_name, _tools)
                    if not ch_url.startswith(self.json_tree.properties.base_url):
                        ch_url = self.json_tree.properties.base_url + ch_url
                    # ------- appending chapter to list -------
                    chapters.append(Chapter(ch_url, ch_name, i, is_premium))
            manga_id = await self.get_id(url)
            found_manga.append(PartialManga(manga_id, name, url, self.name, cover_url, chapters, actual_url=url))
        return found_manga

    async def _search_req(self, query: str) -> str:
        """
        Summar:
            Performs the search request and returns the text of the response.

        Args:
            query: The search term

        Returns:
            str: The webpage text
        """
        search_url = self.json_tree.search.url
        if self.json_tree.search.query_parsing.encoding == "url":
            query = url_encode(query)
        elif self.json_tree.search.query_parsing.encoding is None:
            for pattern_val_dict in self.json_tree.search.query_parsing.regex:
                pattern = re.compile(pattern_val_dict["pattern"])
                sub_value = pattern_val_dict["sub_value"]
                query = pattern.sub(sub_value, query)
        # if encoding is == "raw" then we do nothing
        extra_params: dict = self.json_tree.search.extra_params
        request_kwargs = {
            "url": search_url,
            "method": self.json_tree.search.request_method
        }
        if self.json_tree.search.as_type == "path":
            params = "?" + "&".join([f"{k}={v}" for k, v in extra_params.items() if v is not None])
            null_params = {k: v for k, v in extra_params.items() if v is None}
            if null_params:
                params += "&".join([f"{k}" for k, v in null_params.items()])
            if extra_params:
                query += params
            request_kwargs["url"] += query

        elif self.json_tree.search.as_type == "data":
            params = {self.json_tree.search.search_param_name: query} | extra_params
            request_kwargs["data"] = params

        else:  # as param
            params = {self.json_tree.search.search_param_name: query} | extra_params
            request_kwargs["params"] = params

        search_session_type = self.json_tree.search.session_type
        if search_session_type is not None and search_session_type != self.json_tree.request_method:
            request_kwargs["overwrite_req_method"] = search_session_type
        text = await self._get_text(**request_kwargs)
        return text

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        text = await self._search_req(query)
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        manga_tags = soup.select(self.json_tree.selectors.search.container)

        found_manga: list[PartialManga] = []
        for manga_tag in manga_tags:
            manga_tag: Tag
            if self.json_tree.selectors.search.url == "_container_":
                url = manga_tag.get("href")
            else:
                url = manga_tag.select_one(self.json_tree.selectors.search.url).get("href")
            if not (url.startswith("https://") or url.startswith("http://")):  # noqa
                url = self.json_tree.properties.base_url.removesuffix("/") + "/" + url.removeprefix("/")
            url_name = await self._get_url_name(url)
            _title_selector = self.json_tree.selectors.search.title  # noqa: Invalid scope warning
            if _title_selector == "_container_":
                name = manga_tag.get_text(strip=True)  # noqa: Invalid scope warning
            else:
                title_tag = manga_tag.select_one(_title_selector)
                if _title_selector.endswith("]") and "=" not in _title_selector:
                    name = title_tag.get(  # noqa: Invalid scope warning
                        _title_selector.split("[")[-1].removesuffix("]"))
                else:
                    name = title_tag.get_text(strip=True)  # noqa: Invalid scope warning

            cover_url: str | None = None
            if (selector := self.json_tree.selectors.search.cover) is not None:
                cover_url = self.extract_cover_link_from_tag(
                    manga_tag.select_one(selector), self.json_tree.properties.base_url
                )
                start_idx = max(0, cover_url.rfind(self.json_tree.properties.base_url))
                cover_url = cover_url[start_idx:]
                if " " in cover_url:
                    cover_url = cover_url.replace(" ", "%20")

            chapters: list[Chapter] = []
            if (chapters_selector := self.json_tree.selectors.search.chapters) is not None:
                chapter_tags: list[Tag] = manga_tag.select(chapters_selector.container)

                for i, ch_tag in enumerate(reversed(chapter_tags)):
                    # ------- extracting chapter name -------
                    if chapters_selector.name == "_container_":
                        ch_name = ch_tag.get_text(strip=True)
                    else:
                        ch_name = ch_tag.select_one(chapters_selector.name).get_text(
                            strip=True
                        )
                    # ------- extracting whether the chapter is premium or not -------
                    premium_selector = self.json_tree.selectors.chapters.premium_status
                    is_premium = False
                    if premium_selector is not None:
                        is_premium = ch_tag.select_one(premium_selector) is not None
                    # ------- extracting chapter url -------
                    if chapters_selector.url == "_container_":
                        ch_url = ch_tag.get("href")
                    else:
                        ch_url = ch_tag.select_one(chapters_selector.url).get("href")
                    if (
                            (_tools := self.json_tree.selectors.search.chapters.no_premium_chapter_url) is not None and
                            is_premium is True
                    ):
                        url = self._build_paid_chapter_url(ch_tag, url_name, _tools)
                    if not ch_url.startswith(self.json_tree.properties.base_url):
                        ch_url = self.json_tree.properties.base_url.removesuffix("/") + "/" + url.removeprefix("/")

                    chapters.append(Chapter(ch_url, ch_name, i, is_premium))
            manga_id = await self.get_id(url)
            found_manga.append(PartialManga(manga_id, name, url, self.name, cover_url, chapters))
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class NoStatusBasicScanlator(BasicScanlator):
    def __init__(self, name: str, **kwargs):  # noqa: Invalid scope warning
        super().__init__(name, **kwargs)

    async def get_status(self, raw_url: str) -> Optional[str]:
        date_tag = await self._get_status_tag(self, raw_url)
        if date_tag:
            latest_release_date = date_tag.get_text(strip=True)

            # The next line is to check in case the manga does in fact have a status
            # (i.e., Drakescans - some have status, and some don't)
            probably_real_status = ":" not in latest_release_date and " " not in latest_release_date and not bool(
                re.search(r"\d+", latest_release_date))
            if probably_real_status:
                return await super().get_status(
                    raw_url)  # ideally, the request is cached, so this should not be a problem

            timestamp = time_string_to_seconds(latest_release_date, formats=self.json_tree.properties.time_formats)
            if (
                    datetime.now().timestamp() - timestamp
                    > self.bot.config["constants"]["time-for-manga-to-be-considered-stale"]
            ):
                return "Completed"
            else:
                return "Ongoing"


class DynamicURLScanlator(BasicScanlator):
    def __init__(self, name: str, **kwargs):  # noqa: Invalid scope warning
        super().__init__(name, **kwargs)
        self.chapter_id: str | None = None
        self.manga_id: str | None = None
        self.id_placeholder: str = "{id}"  # leaving it as {id} as it allows for formatting if needed

    def _extract_dynamic_ids(self, partial_manhwas: list[PartialManga]):
        """
        This method must only be used in the 'DynamicURLScanlator.get_fp_partial_manga' method

        Args:
            partial_manhwas: list[PartialManga] - The manhwa objects used to fetch the url IDs.

        Returns:
            None
        """
        manga_id_found = chapter_id_found = False
        # Reversed to use old IDs first. Guarantees older series will work
        for manga_url, chapter_urls in [(x.url, [y.url for y in x.latest_chapters]) for x in reversed(partial_manhwas)]:
            if chapter_id_found is False:
                for url in chapter_urls:
                    if (rx_result := self.json_tree.rx.search(url)) is not None:
                        chapter_id_found = True
                        self.chapter_id = rx_result.groupdict().get("id")  # allowed to be None
                        if not self.chapter_id:
                            chapter_id_found = False
                            continue
                        break
            if manga_id_found is False:
                if (rx_result := self.json_tree.rx.search(manga_url)) is not None:
                    manga_id_found = True
                    self.manga_id = rx_result.groupdict().get("id")  # allowed to be None
                    if not self.manga_id:
                        manga_id_found = False
            if (manga_id_found and chapter_id_found) is True:
                break

    async def _get_text(self, url: str, method: Literal["GET", "POST"] = "GET", **params) -> str:
        # one thing to note:
        # headers are only really required to let websites that gave us special access to identify us.
        # so, realistically, we can ignore headers in the flare request, as it's intended to be used for websites that
        # block us.
        provided_headers = params.pop("headers", None)
        if not provided_headers: provided_headers = {}  # noqa: Allow inline operation
        headers = ((self.create_headers() or {}) | provided_headers) or None
        if self.json_tree.request_method == "curl":
            resp = await self.bot.session.request(
                method, url, headers=headers, **self.get_extra_req_kwargs(), **params
            )
            if resp.status_code == 404 and self.manga_id is not None:
                if self.manga_id in url:
                    self.bot.logger.warning(f"404 error on {url}. Removing manga_id from URL and trying again.")
                    if self.json_tree.properties.missing_id_connector.before_id:
                        url = url.replace(self.json_tree.properties.missing_id_connector.char + self.manga_id, "")
                    else:
                        url = url.replace(self.manga_id + self.json_tree.properties.missing_id_connector.char, "")
                    return await self._get_text(url, method, **params)

            await raise_and_report_for_status(self.bot, resp)
            return resp.text

        else:
            raise ValueError(f"Unknown {self.json_tree.request_method} request method.")

    async def format_manga_url(
            self, raw_url: Optional[str] = None, url_name: Optional[str] = None, _id: Optional[str] = None,
            *, use_ajax_url: bool = False
    ) -> str:
        if not any([raw_url is not None, url_name is not None, _id is not None]):
            raise ValueError("At least one of the arguments must be provided.")
        if raw_url is not None:
            url_name = await self._get_url_name(raw_url)
            await self.get_fp_partial_manga()
            # if not self.manga_id:
            _id = self.manga_id
        if use_ajax_url and self.json_tree.uses_ajax:
            return self.json_tree.properties.format_urls.ajax.format(url_name=url_name, id=_id)
        return self.json_tree.properties.format_urls.manga.format(url_name=url_name, id=_id)

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        found_manga: list[PartialManga] = await super().get_fp_partial_manga()
        self._extract_dynamic_ids(found_manga)
        return found_manga

    # noinspection PyProtectedMember
    async def load_manga(self, mangas: list[Manga]) -> list[Manga]:
        if not self.manga_id and not self.chapter_id:
            # fetch the latest manga_id and chapter_id available on the website
            await self.get_fp_partial_manga()  # this function calls the '_extract_dynamic_ids' method
        for manga in mangas:
            manga._url = manga.url.replace(self.id_placeholder, self.manga_id)

            # if the chapter id is None, remove the placeholder and connecting character
            to_replace = self.id_placeholder
            replace_with = self.chapter_id
            if self.chapter_id is None:
                if self.json_tree.properties.missing_id_connector.before_id:
                    to_replace = self.json_tree.properties.missing_id_connector.char + self.id_placeholder
                else:
                    to_replace = self.id_placeholder + self.json_tree.properties.missing_id_connector.char
                replace_with = ""
            manga._last_chapter.url = manga.last_chapter.url.replace(to_replace, replace_with)
            for chapter in manga._chapters:
                chapter.url = chapter.url.replace(to_replace, replace_with)
        return mangas

    async def _insert_id_placeholder(self, url: str) -> str:
        """Used to add the placeholder to URLs that should have an ID but don't.
        For example, https://luminousscans.gg/series/nano-machine should be
        https://luminousscans.gg/series/{id}-nano-machine
        """
        if self.id_placeholder in url:  # already exists in the URL: do nothing
            return url
        chapter_rx = self.json_tree.properties.chapter_regex
        if chapter_rx is not None and (res := chapter_rx.search(url)) is not None:
            groups = res.groupdict()
            if self.json_tree.properties.missing_id_connector.before_id:
                id_placeholder_str = self.json_tree.properties.missing_id_connector.char + self.id_placeholder
            else:
                id_placeholder_str = self.id_placeholder + self.json_tree.properties.missing_id_connector.char
            return (
                    groups["before_id"] + id_placeholder_str + groups["after_id"]
            )
        else:
            url_name = await self._get_url_name(url)
            return await self.format_manga_url(url_name=url_name, _id=self.id_placeholder)

    # noinspection PyProtectedMember
    async def unload_manga(self, mangas: list[Manga | PartialManga]) -> list[Manga | PartialManga]:
        unloaded_manga: list[Manga] = []

        for actual_manga in mangas:
            manga = deepcopy(actual_manga)  # don't want to mutate the actual loaded manga
            manga._url = await self._insert_id_placeholder(manga.url)
            if isinstance(manga, PartialManga):
                for chapter in manga._latest_chapters:
                    chapter.url = await self._insert_id_placeholder(chapter.url)
            else:
                manga._last_chapter.url = await self._insert_id_placeholder(manga.last_chapter.url)
                for chapter in manga._chapters:
                    chapter.url = await self._insert_id_placeholder(chapter.url)
            unloaded_manga.append(manga)
        return unloaded_manga


class DynamicURLNoStatusScanlator(DynamicURLScanlator, NoStatusBasicScanlator):
    def __init__(self, name: str, **kwargs):  # noqa: Invalid scope warning
        super().__init__(name, **kwargs)


map_path = os.path.join(root_path, "src/core/scanlators/lookup_map.json")
with open(map_path, "r") as f:
    lookup_map = json.load(f)

scanlators: dict[str, BasicScanlator | AbstractScanlator] = {
    # name: BasicScanlator(name, **kwargs) for name, kwargs in lookup_map.items()
}
for _type, _map in lookup_map.items():
    if _type == "static":
        for name, kwargs in _map.items():
            _object = BasicScanlator(name, **kwargs)
            if _object.json_tree.properties.dynamic_url and _object.json_tree.properties.no_status:
                _object = DynamicURLNoStatusScanlator(name, **kwargs)
            elif _object.json_tree.properties.dynamic_url:
                _object = DynamicURLScanlator(name, **kwargs)
            elif _object.json_tree.properties.no_status:
                _object = NoStatusBasicScanlator(name, **kwargs)
            scanlators[name] = _object
    elif _type == "custom":
        # We're setting the name to the actual kwargs here for ease of access when setting the custom classes
        # from 'custom.py'
        for name, kwargs in _map.items():
            scanlators[name] = kwargs

if __name__ == "__main__":
    raise RuntimeError("This file is not meant to be run directly. Please start main.py from the root dir instead.")
