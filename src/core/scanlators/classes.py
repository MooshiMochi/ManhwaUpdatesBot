from __future__ import annotations

import hashlib
import os
import re
import traceback
from datetime import datetime
from io import BytesIO
from typing import Literal, Optional, TYPE_CHECKING
from urllib.parse import quote_plus as url_encode

import discord
from bs4 import BeautifulSoup, Tag
from discord.utils import MISSING

from src.utils import time_string_to_seconds

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
    def extract_cover_link_from_tag(tag) -> str | None:
        for attr in ["data-src", "src", "href", "content", "data-lazy-src"]:
            result = tag.get(attr)
            if result and result.startswith("https://"):
                return result

    @staticmethod
    def remove_unwanted_tags(soup: BeautifulSoup, unwanted_selectors: list[str]):
        if not unwanted_selectors:
            return
        for tag in soup.select(",".join(unwanted_selectors)):
            tag.extract()


class AbstractScanlator(ABC):
    bot: MangaClient
    json_tree: JSONTree

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
        embed.set_author(name=self.name.title())
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
            em.set_image(url=p_manga.cover_url)
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

    async def unload_manga(self, mangas: list[Manga]) -> list[Manga]:  # noqa: Other implementations require 'self'
        """
        *For Dynamic URL Websites*
        Replaces the manga_id and chapter_id in the URLs of the Manga object with a placeholder

        Args:
            mangas: list[Manga] - The manga objects to replace the IDs for

        Returns:
            list[Manga] - The objects with placeholders for IDs set for all URLs

        Notes:
            These properties contain a chapter/manga ID:
            - Manga.url
            - Manga.latest_chapter.url
            - Manga.available_chapters > Chapter.url
        """
        return mangas

    async def make_manga_object(self, raw_url: str) -> Manga | None:
        manga_id = await self.get_id(raw_url)

        # load from database if exists.
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
            user_created: bool = False,
    ) -> Bookmark | None:
        """
        Creates a Bookmark object from the scanlator's website.

        Parameters:
            raw_url: str - The URL of the manga's home page.
            user_id: int - The ID of the user.
            guild_id: int - The ID of the guild.
            user_created: bool - Whether the user created the bookmark or not.

        Returns:
            Bookmark/None - The Bookmark object if the manga is found, otherwise `None`.
        """
        manga = await self.make_manga_object(raw_url)
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
            datetime.now().timestamp(),
            user_created,
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
        try:
            all_chapters = await self.get_all_chapters(manga.url)
            status: str = await self.get_status(manga.url)
            cover_url: str = await self.get_cover(manga.url)
            if all_chapters is None:
                return ChapterUpdate(manga.id, [], manga.scanlator, cover_url, status)
            if manga.last_chapter:
                new_chapters: list[Chapter] = [
                    chapter for chapter in all_chapters if chapter.index > manga.last_chapter.index
                ]
            else:
                new_chapters: list[Chapter] = all_chapters
            return ChapterUpdate(
                manga.id, new_chapters, manga.scanlator, cover_url, status,
                [
                    {"embed": self.create_chapter_embed(manga, chapter)}
                    for chapter in new_chapters
                ] if self.json_tree.properties.requires_update_embed else None
            )
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            await self.bot.log_to_discord(tb)
            raise e

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
        provided_headers = params.pop("headers", None)
        if not provided_headers: provided_headers = {}  # noqa: Allow inline operation
        headers = ((self.create_headers() or {}) | provided_headers) or None
        if self.json_tree.request_method == "http":
            async with self.bot.session.request(
                    method, url, headers=headers, **self.get_extra_req_kwargs(), **params
            ) as resp:
                resp.raise_for_status()
                return await resp.text()
        else:
            resp = await self.bot.curl_session.request(
                method, url, headers=headers, **self.get_extra_req_kwargs(), **params
            )
            resp.raise_for_status()
            return resp.text

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
            return self.json_tree.properties.format_urls.ajax.format(url_name=url_name, id=_id)
        return self.json_tree.properties.format_urls.manga.format(url_name=url_name, id=_id)

    async def _get_url_name(self, raw_url: str) -> str:
        try:
            return self.json_tree.rx.search(raw_url).groupdict().get("url_name")
        except AttributeError as e:
            self.bot.logger.error(raw_url)
            raise e

    def check_ownership(self, raw_url: str) -> bool:
        try:
            return self.json_tree.rx.search(raw_url) is not None
        except AttributeError as e:
            self.bot.logger.error(raw_url)
            raise e

    async def get_id(self, raw_url: str) -> str:
        try:
            url_id = self.json_tree.rx.search(raw_url).groupdict().get("id")
        except AttributeError as e:
            self.bot.logger.error(raw_url)
            raise e
        if url_id is None or self.json_tree.properties.dynamic_url is True:
            key = await self._get_url_name(raw_url)
            return hashlib.sha256(key.encode()).hexdigest()
        return url_id

    async def get_title(self, raw_url: str) -> str | None:
        text = await self._get_text(await self.format_manga_url(raw_url))
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        selectors = self.json_tree.selectors.title
        for selector in selectors:
            title = soup.select_one(selector)
            if title:
                return title.get_text(strip=True)

    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        req_url = await self.format_manga_url(raw_url, use_ajax_url=True)
        method = "POST" if self.json_tree.uses_ajax else "GET"
        text = await self._get_text(req_url, method=method)  # noqa
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        chapter_selector = self.json_tree.selectors.chapters
        chapters: list[Tag] = soup.select(chapter_selector["container"])
        found_chapters: list[Chapter] = []
        for i, chapter in enumerate(reversed(chapters)):
            if chapter_selector["url"] == "_container_":
                url = chapter.get("href")
            else:
                url = chapter.select_one(chapter_selector["url"]).get("href")
            if not url.startswith(self.json_tree.properties.base_url):
                url = self.json_tree.properties.base_url + url
            if chapter_selector["name"] == "_container_":
                name = chapter.get_text(strip=True)  # noqa: Invalid scope warning
            else:
                name = chapter.select_one(chapter_selector["name"]).get_text(strip=True)  # noqa: Invalid scope warning
            found_chapters.append(Chapter(url, name, i))
        return found_chapters

    async def get_status(self, raw_url: str) -> str:
        if self.json_tree.properties.no_status:
            method = "POST" if self.json_tree.uses_ajax else "GET"
            text = await self._get_text(await self.format_manga_url(raw_url, use_ajax_url=True), method=method)  # noqa
        else:
            text = await self._get_text(await self.format_manga_url(raw_url))
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        status_selector = self.json_tree.selectors.status
        status = soup.select_one(status_selector)
        if status:
            return status.get_text(strip=True)

    async def get_synopsis(self, raw_url: str) -> str:
        text = await self._get_text(await self.format_manga_url(raw_url))
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        synopsis_selector = self.json_tree.selectors.synopsis
        synopsis = soup.select_one(synopsis_selector)
        if synopsis:
            return synopsis.get_text(strip=True, separator="\n")

    async def get_cover(self, raw_url: str) -> str:
        text = await self._get_text(await self.format_manga_url(raw_url))
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        selectors = self.json_tree.selectors.cover
        for selector in selectors:
            cover_tag = soup.select_one(selector)
            if cover_tag:
                cover_url = self.extract_cover_link_from_tag(cover_tag)
                # this is mainly bc of asura
                start_idx = max(0, cover_url.rfind("https://"))
                return cover_url[start_idx:]

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        text = await self._get_text(self.json_tree.properties.latest_updates_url)
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        manga_tags = soup.select(self.json_tree.selectors.front_page.container)

        found_manga: list[PartialManga] = []
        for manga_tag in manga_tags:
            manga_tag: Tag
            url = manga_tag.select_one(self.json_tree.selectors.front_page.url).get("href")
            if not url.startswith(self.json_tree.properties.base_url):
                url = self.json_tree.properties.base_url + url
            name = manga_tag.select_one(  # noqa: Invalid scope warning
                self.json_tree.selectors.front_page.title
            ).get_text(strip=True)

            cover_url = self.extract_cover_link_from_tag(
                manga_tag.select_one(self.json_tree.selectors.front_page.cover))
            chapter_tags: list[Tag] = manga_tag.select(self.json_tree.selectors.front_page.chapters["container"])
            chapters: list[Chapter] = []

            for i, ch_tag in enumerate(reversed(chapter_tags)):
                if self.json_tree.selectors.front_page.chapters["name"] == "_container_":
                    ch_name = ch_tag.get_text(strip=True)
                else:
                    ch_name = ch_tag.select_one(self.json_tree.selectors.front_page.chapters["name"]).get_text(
                        strip=True
                    )
                if self.json_tree.selectors.front_page.chapters["url"] == "_container_":
                    ch_url = ch_tag.get("href")
                else:
                    ch_url = ch_tag.select_one(self.json_tree.selectors.front_page.chapters["url"]).get("href")
                if not ch_url.startswith(self.json_tree.properties.base_url):
                    ch_url = self.json_tree.properties.base_url + url
                chapters.append(Chapter(ch_url, ch_name, i))
            manga_id = await self.get_id(url)
            found_manga.append(PartialManga(manga_id, name, url, self.name, cover_url, chapters, actual_url=url))
        return found_manga

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
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
        if self.json_tree.search.as_type == "path":
            params = "?" + "&".join([f"{k}={v}" for k, v in extra_params.items() if v is not None])
            null_params = {k: v for k, v in extra_params.items() if v is None}
            if null_params:
                params += "&".join([f"{k}" for k, v in null_params.items()])
            query += params
            text = await self._get_text(search_url + query, method=self.json_tree.search.request_method)
        else:  # as param
            params = {self.json_tree.search.search_param_name: query} | extra_params
            text = await self._get_text(search_url, params=params, method=self.json_tree.search.request_method)

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
            if not url.startswith("https://") and not url.startswith("http://"):
                url = self.json_tree.properties.base_url + url
            name = manga_tag.select_one(  # noqa: Invalid scope warning
                self.json_tree.selectors.search.title
            ).get_text(strip=True)

            cover_url = self.extract_cover_link_from_tag(
                manga_tag.select_one(self.json_tree.selectors.search.cover))
            start_idx = max(0, cover_url.rfind(self.json_tree.properties.base_url))
            cover_url = cover_url[start_idx:]

            chapters: list[Chapter] = []
            if (chapters_selector := self.json_tree.selectors.search.chapters) is not None:
                chapter_tags: list[Tag] = manga_tag.select(chapters_selector["container"])

                for i, ch_tag in enumerate(reversed(chapter_tags)):
                    if chapters_selector["name"] == "_container_":
                        ch_name = ch_tag.get_text(strip=True)
                    else:
                        ch_name = ch_tag.select_one(chapters_selector["name"]).get_text(
                            strip=True
                        )
                    if chapters_selector["url"] == "_container_":
                        ch_url = ch_tag.get("href")
                    else:
                        ch_url = ch_tag.select_one(chapters_selector["url"]).get("href")
                    if not ch_url.startswith(self.json_tree.properties.base_url):
                        ch_url = self.json_tree.properties.base_url + url
                    chapters.append(Chapter(ch_url, ch_name, i))
            manga_id = await self.get_id(url)
            found_manga.append(PartialManga(manga_id, name, url, self.name, cover_url, chapters))
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class NoStatusBasicScanlator(BasicScanlator):
    def __init__(self, name: str, **kwargs):  # noqa: Invalid scope warning
        super().__init__(name, **kwargs)

    async def get_status(self, raw_url: str) -> str:
        if self.json_tree.properties.no_status:
            method = "POST" if self.json_tree.uses_ajax else "GET"
            text = await self._get_text(await self.format_manga_url(raw_url, use_ajax_url=True), method=method)  # noqa
        else:
            text = await self._get_text(await self.format_manga_url(raw_url))
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        date_selector = self.json_tree.selectors.status
        date_str = soup.select_one(date_selector)
        if date_str:
            latest_release_date = date_str.get_text(strip=True)
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
        for manga_url, chapter_urls in [(x.url, [y.url for y in x.latest_chapters]) for x in partial_manhwas]:
            manga_id_found = chapter_id_found = False
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

    async def format_manga_url(
            self, raw_url: Optional[str] = None, url_name: Optional[str] = None, _id: Optional[str] = None,
            *, use_ajax_url: bool = False
    ) -> str:
        if not any([raw_url is not None, url_name is not None, _id is not None]):
            raise ValueError("At least one of the arguments must be provided.")
        if raw_url is not None:
            url_name = await self._get_url_name(raw_url)
            if not self.manga_id:
                await self.get_fp_partial_manga()
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
            manga._last_chapter.url = manga.last_chapter.url.replace(self.id_placeholder, self.chapter_id)
            for chapter in manga._available_chapters:
                chapter.url = chapter.url.replace(self.id_placeholder, self.chapter_id)
        return mangas

    async def _insert_id_placeholder(self, url: str) -> str:
        """Used to add the placeholder to URLs that should have an ID but don't.
        For example, https://luminousscans.com/manga/nano-machine should be
        https://luminousscans.com/manga/{id}-nano-machine
        """
        if self.id_placeholder in url:  # already exists in the URL: do nothing
            return url
        chapter_rx = self.json_tree.properties.chapter_regex
        if chapter_rx is not None and (res := chapter_rx.search(url)) is not None:
            groups = res.groupdict()
            return (
                    groups["before_id"] + self.id_placeholder + self.json_tree.properties.missing_id_connector_char
                    + groups["after_id"]
            )
        else:
            url_name = await self._get_url_name(url)
            return await self.format_manga_url(url_name=url_name, _id=self.id_placeholder)

    # noinspection PyProtectedMember
    async def unload_manga(self, mangas: list[Manga]) -> list[Manga]:
        unloaded_manga: list[Manga] = []

        for actual_manga in mangas:
            manga = actual_manga.copy()  # don't want to mutate the actual loaded manga
            manga._url = await self._insert_id_placeholder(manga.url)
            manga._last_chapter.url = await self._insert_id_placeholder(manga.last_chapter.url)
            for chapter in manga._available_chapters:
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
    raise RuntimeError("This file is not meant to be run directly.")
