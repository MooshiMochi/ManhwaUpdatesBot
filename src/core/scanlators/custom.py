import json
import re

import discord
from bs4 import BeautifulSoup

from src.core.objects import Chapter, PartialManga
from .classes import BasicScanlator, scanlators

__all__ = (
    "scanlators",
)

from ...html_json_parser import Parser

from ...static import Constants

from ...utils import raise_and_report_for_status, find_values_by_key


class _OmegaScans(BasicScanlator):
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

    async def get_id(self, raw_url: str) -> str | None:
        resp = await self.bot.session.get(raw_url)
        await raise_and_report_for_status(self.bot, resp)
        manga_id = re.search(r'\\"series_id\\":(\d+),', resp.text).group(1)
        return manga_id

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        fp_mangas: list[PartialManga] = await super().get_fp_partial_manga()
        fixed_fp_mangas: list[PartialManga] = []
        for manga in fp_mangas:
            # Sor the chapters in ascending order based on their url
            manga._latest_chapters = list(sorted(manga.latest_chapters, key=lambda x: x.url))
            # Fix the index of the chapters
            for i, chapter in enumerate(manga.latest_chapters):
                chapter.index = i
            fixed_fp_mangas.append(manga)
        return fixed_fp_mangas

    async def get_cover(self, raw_url: str) -> str:
        url_name = await super()._get_url_name(raw_url)
        return await self.bot.apis.omegascans.get_cover(url_name)

    async def get_synopsis(self, raw_url: str) -> str:
        url_name = await super()._get_url_name(raw_url)
        return await self.bot.apis.omegascans.get_synopsis(url_name)

    async def get_title(self, raw_url: str) -> str:
        url_name = await super()._get_url_name(raw_url)
        return await self.bot.apis.omegascans.get_title(url_name)

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        search_results = await self.bot.apis.omegascans.search(query)
        found_manga: list[PartialManga] = []

        for item_dict in search_results:
            title = item_dict["title"]
            url = self.json_tree.properties.format_urls.manga.format(url_name=item_dict["series_slug"])
            cover = item_dict["thumbnail"]
            _id = await self.get_id(url)

            chapters: list[Chapter] = []
            # omega is giving out all the chapters in the search results
            # so we can just use the chapters from the search results
            paid_chapters: list[dict] = item_dict["paid_chapters"]
            free_chapters: list[dict] = item_dict["free_chapters"]
            num_free_chapters = len(free_chapters)
            for i, chapter in enumerate(reversed(paid_chapters + free_chapters)):
                chapter_url = url.removesuffix("/") + "/" + chapter["chapter_slug"]
                chapter_name = chapter["chapter_name"]
                is_premium_chapter = i >= num_free_chapters
                if chapter.get("chapter_title") is not None:
                    chapter_name += f" - {chapter['chapter_title']}"
                chapters.append(Chapter(chapter_url, chapter_name, i, is_premium=is_premium_chapter))

            p_manga = PartialManga(_id, title, url, self.name, cover, chapters)
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga

    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        url_name = await self._get_url_name(raw_url)  # noqa: Dupliacted code
        series_id = await self.get_id(raw_url)
        chapters: list[dict] = await self.bot.apis.omegascans.get_chapters_list(series_id)
        found_chapters: list[Chapter] = []
        for i, chapter in enumerate(chapters):
            base_chapter_url = await self.format_manga_url(url_name=url_name)
            chapter_url = base_chapter_url.removesuffix("/") + "/" + chapter["chapter_slug"]
            chapter_name = chapter["chapter_name"]
            is_premium_chapter = "price" in chapter.keys() and chapter["price"] > 0
            if chapter.get("chapter_title") is not None:
                chapter_name += f" - {chapter['chapter_title']}"
            found_chapters.append(Chapter(chapter_url, chapter_name, i, is_premium=is_premium_chapter))
        return found_chapters

    async def get_status(self, raw_url: str) -> str:
        url_name = await self._get_url_name(raw_url)
        status = await self.bot.apis.omegascans.get_status(url_name)
        return status


class _ReaperScans(BasicScanlator):
    cover_url_fmt = "https://media.reaperscans.com/file/4SRBHm/"

    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        text = await self._get_text(self.json_tree.properties.latest_updates_url)
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)
        json_result = Parser.parse_text(str(soup))
        fp_mangas: list[dict] = find_values_by_key(json_result, "initialValue")
        found_manga: list[PartialManga] = []
        for item_dict in fp_mangas:
            title = item_dict["title"]
            url = self.json_tree.properties.format_urls.manga.format(url_name=item_dict["series_slug"])
            cover = self.cover_url_fmt + item_dict["thumbnail"]
            _id = item_dict["id"]

            latest_chapters: list[Chapter] = []
            latest_chapters_resp: list[dict] = item_dict["free_chapters"]
            latest_paid_chapters: list[dict] = item_dict["paid_chapters"]

            if latest_paid_chapters:
                # Force the update checker to do a full check for the manhwa.
                # As of now, reaper does not make paid chapters for manga.
                # Everything is free.
                # However, in case they start doing paid chapters for manga,
                # it looks like their paid chapter is way off from the free chapters.
                # For example,
                # Free chapters: [Chapter 157, Chapter 158]
                # Paid chapters: [Chapter 167, Chapter 168]
                # To avoid confusion for the bot and missing chapters,
                # we will just use the highest numbered chapters
                # as the latest chapters.
                # This should force the bot to do a full update check.
                latest_chapters_resp = latest_paid_chapters

            for i, chapter in enumerate(latest_chapters_resp):
                chapter_url = url.removesuffix("/") + "/" + chapter["chapter_slug"]
                chapter_name = chapter["chapter_name"]
                is_premium_chapter = False
                if chapter.get("chapter_title") is not None:
                    chapter_name += f" - {chapter['chapter_title']}"
                latest_chapters.append(
                    Chapter(chapter_url, chapter_name, 987654321 - i, is_premium=is_premium_chapter)
                )

            # latest_chapters must be in ascending order in the PartialManga object for consistency’s sake
            p_manga = PartialManga(_id, title, url, self.name, cover, latest_chapters[::-1])
            found_manga.append(p_manga)
        return found_manga

    async def get_id(self, raw_url: str) -> str | None:
        resp = await self.bot.session.get(raw_url)
        await raise_and_report_for_status(self.bot, resp)
        manga_id = re.search(r'\\"series_id\\":(\d+),', resp.text).group(1)
        return manga_id

    async def get_cover(self, raw_url: str) -> str:
        url_name = await super()._get_url_name(raw_url)
        return await self.bot.apis.reaperscans.get_cover(url_name)

    async def get_synopsis(self, raw_url: str) -> str:
        url_name = await super()._get_url_name(raw_url)
        return await self.bot.apis.reaperscans.get_synopsis(url_name)

    async def get_title(self, raw_url: str) -> str:
        url_name = await super()._get_url_name(raw_url)
        return await self.bot.apis.reaperscans.get_title(url_name)

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        search_results = await self.bot.apis.reaperscans.search(query)
        found_manga: list[PartialManga] = []

        for item_dict in search_results:
            title = item_dict["title"]
            url = self.json_tree.properties.format_urls.manga.format(url_name=item_dict["series_slug"])
            cover = item_dict["thumbnail"]
            _id = await self.get_id(url)

            base_chapter_url = await self.format_manga_url(url_name=item_dict["series_slug"])
            base_chapter_url = base_chapter_url.removesuffix("/")

            latest_chapters: list[Chapter] = []
            latest_chapters_resp: list[dict] = item_dict["free_chapters"]

            for i, chapter in enumerate(latest_chapters_resp):
                chapter_url = base_chapter_url + "/" + chapter["chapter_slug"]
                chapter_name = chapter["chapter_name"]
                is_premium_chapter = False  # because we are reading from the "free_chapters" key.
                # The latest paid chapters are found in the "paid_chaptesr" key, however, that does not contain
                # all the paid chapters after the free chapters,
                # so merging the two dicts would mean we lose some chapters

                if chapter.get("chapter_title") is not None:
                    chapter_name += f" - {chapter['chapter_title']}"

                latest_chapters.append(
                    Chapter(chapter_url, chapter_name, 987654321 - i, is_premium=is_premium_chapter)
                )

            # latest_chapters must be in ascending order in the PartialManga object for consistency’s sake
            p_manga = PartialManga(_id, title, url, self.name, cover, latest_chapters[::-1])
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga

    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        url_name = await self._get_url_name(raw_url)  # noqa: Duplicated code
        series_id = await self.get_id(raw_url)
        chapters: list[dict] = await self.bot.apis.reaperscans.get_chapters_list(series_id)
        found_chapters: list[Chapter] = []
        for i, chapter in enumerate(chapters):
            base_chapter_url = await self.format_manga_url(url_name=url_name)
            chapter_url = base_chapter_url.removesuffix("/") + "/" + chapter["chapter_slug"]
            chapter_name = chapter["chapter_name"]
            is_premium_chapter = "price" in chapter.keys() and chapter["price"] > 0
            if chapter.get("chapter_title") is not None:
                chapter_name += f" - {chapter['chapter_title']}"
            found_chapters.append(Chapter(chapter_url, chapter_name, i, is_premium=is_premium_chapter))
        return found_chapters

    async def get_status(self, raw_url: str) -> str:
        url_name = await self._get_url_name(raw_url)
        status = await self.bot.apis.reaperscans.get_status(url_name)
        return status


class _GourmetScans(BasicScanlator):
    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        search_result = json.loads(await self._search_req(query))
        found_manga: list[PartialManga] = []

        for item_dict in search_result.get("data", []):
            title = item_dict["title"]
            url = item_dict["url"]
            _id = await self.get_id(url)

            p_manga = PartialManga(_id, title, url, self.name)
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class _NovelMic(BasicScanlator):
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

    async def get_id(self, raw_url: str) -> str:
        text = await super()._get_text(raw_url, "GET")
        soup = BeautifulSoup(text, "html.parser")
        id_ = soup.select_one("input.rating-post-id").get("value")
        return id_

    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        id_ = await self.get_id(raw_url)
        chapters_req_url = self.json_tree.properties.format_urls.ajax
        chapters_html = await self._get_text(
            chapters_req_url, "POST", data={"action": "manga_get_chapters", "manga": id_}
        )
        return self._extract_chapters_from_html(chapters_html)


class _Mangapark(BasicScanlator):
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

    async def get_status(self, raw_url: str) -> str:
        text = await self._get_text(await self.format_manga_url(raw_url))
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        status_selectors = self.json_tree.selectors.status
        # if both statuses show completed, then return any of the avaialble statuses
        # otherwise return the one that is not completed!
        found_statuses = []
        for selector in status_selectors:
            statuses = soup.select(selector)
            if statuses:
                for status in statuses:
                    status_text = status.get_text(strip=True)
                    found_status = re.sub(r"\W", "", status_text).lower().removeprefix("status").strip().title()
                    found_statuses.append(found_status)
        if not found_statuses:
            return "Unknown"
        for _status in found_statuses:
            if _status.lower() not in Constants.completed_status_set:
                return _status
        return found_statuses[0]


class _Bato(_Mangapark):
    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        chapters = await super().get_all_chapters(raw_url)
        # reverse the index
        for i, chap in enumerate(reversed(chapters)):
            chap.index = i
        return chapters[::-1]  # could sort based on index, but that will require more processing


class _Flamecomics(BasicScanlator):
    def _extract_chapters_from_html(self, text: str, url_name: str = None) -> list[Chapter]:
        token_rx = re.compile(r"\"token\":\"(?P<id>[a-z\d]+)\"")
        chapter_num_rx = re.compile(r"\"chapter\":\"(?P<num>(?:\d*[.])?\d+)\"")
        series_id_rx = re.compile(r"\"series_id\":(?P<id>\d+)")
        url_base = self.json_tree.properties.base_url + "/series/"
        series_id = series_id_rx.search(text).group("id")
        url_base += series_id + "/"

        found_chapters: list[Chapter] = []
        for i, (name_match, token_match) in enumerate(
                reversed(list(zip(chapter_num_rx.finditer(text), token_rx.finditer(text))))):
            url = url_base + token_match.group("id")
            name = name_match.group("num")
            found_chapters.append(Chapter(url, name, i))
        return found_chapters


class _Hivetoon(BasicScanlator):
    chapters_path = "/api/chapters"
    search_path = "/api/search"

    def _extract_fp_manga_from_api_response(self, json_list: list[dict]) -> list[PartialManga]:
        found_manga: list[PartialManga] = []
        for item_dict in json_list:
            title = item_dict["postTitle"]
            url = self.json_tree.properties.format_urls.manga.format(url_name=item_dict["slug"])
            cover = item_dict["featuredImage"]
            _id = item_dict["id"]

            latest_chapters: list[Chapter] = []
            latest_chapters_resp: list[dict] = item_dict["chapters"]

            for i, chapter in enumerate(latest_chapters_resp):
                chapter_url = url.removesuffix("/") + "/" + chapter["slug"]
                chapter_name = f"Chapter {chapter['number']}"
                is_premium = chapter["isLocked"] is True
                latest_chapters.append(Chapter(chapter_url, chapter_name, i, is_premium))

            p_manga = PartialManga(_id, title, url, self.name, cover, latest_chapters[::-1])
            found_manga.append(p_manga)
        return found_manga

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        text = await self._get_text(self.json_tree.properties.latest_updates_url)
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)
        json_result = Parser.parse_text(str(soup))
        fp_mangas: list[dict] = find_values_by_key(json_result, "initalPosts")
        found_manga: list[PartialManga] = self._extract_fp_manga_from_api_response(fp_mangas)
        return found_manga

    async def get_id(self, raw_url: str) -> str:
        resp = await self.bot.session.get(raw_url)
        await raise_and_report_for_status(self.bot, resp)
        manga_id = re.search(r'\\"postId\\":(\d+)', resp.text).group(1)
        return manga_id.strip()

    async def get_title(self, raw_url: str) -> str | None:
        resp = await self.bot.session.get(raw_url)
        await raise_and_report_for_status(self.bot, resp)
        title = re.search(self.json_tree.selectors.title[0], resp.text).group(1)
        return title.strip()

    async def get_synopsis(self, raw_url: str) -> str | None:
        resp = await self.bot.session.get(raw_url)
        await raise_and_report_for_status(self.bot, resp)
        synopsis = re.search(self.json_tree.selectors.synopsis, resp.text).group(1)
        return synopsis.strip()

    async def get_cover(self, raw_url: str) -> str:
        resp = await self.bot.session.get(raw_url)
        await raise_and_report_for_status(self.bot, resp)
        cover = re.search(self.json_tree.selectors.cover[0], resp.text).group(1)
        if not cover:  # if the cover is not found, then use the default method
            return await super().get_cover(raw_url)
        return cover.strip()

    async def get_status(self, raw_url: str) -> str:
        resp = await self.bot.session.get(raw_url)
        await raise_and_report_for_status(self.bot, resp)
        status = re.search(self.json_tree.selectors.status[0], resp.text).group(1)
        return status.lower().title().strip()

    async def get_all_chapters(self, raw_url: str, skip: int = 0, series_id: str | None = None) -> list[Chapter]:
        """
        Get all chapters of a manga from the given URL

        Args:
            raw_url: the url to request
            skip: the number of chapters to skip when fetching them
            series_id: the series id of the manga passed as a parameter
                in recursive calls to avoid extra api calls

        Returns:
            list[Chapter]: a list of Chapter objects
        """

        if series_id is None:  # do this once on the first call to avoid repetitive api calls for the same info
            # even though this is not necessary since the first request will be cached, and any later requests
            # to the same endpoint would just be grabbed from cache
            series_id = await self.get_id(raw_url)

        # "https://hivetoon.com/api/chapters?postId=15&skip=0&take=50&order=desc"
        req_params = f"postId={series_id}&skip={skip}&take=50&order=asc"
        req_url = self.json_tree.properties.base_url + self.chapters_path + '?' + req_params
        all_chapters: list[Chapter] = []

        resp = await self.bot.session.get(req_url)
        data = resp.json()

        chapters = data["post"]["chapters"]
        total_chapters_count = data["totalChapterCount"]
        for i, chapter in enumerate(chapters):
            chapter_url = f"{raw_url.removesuffix('/')}/{chapter['slug']}"
            chapter_name = chapter["title"] or f"Chapter {chapter['number']}"
            is_premium = chapter["isLocked"] is True
            all_chapters.append(Chapter(chapter_url, chapter_name, skip + i, is_premium))
        if skip < total_chapters_count:
            all_chapters += await self.get_all_chapters(raw_url, skip + 50, series_id)
        return all_chapters

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        text = await self._search_req(query)
        search_results = json.loads(text)
        found_manga: list[PartialManga] = self._extract_fp_manga_from_api_response(search_results.get("posts", []))
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class CustomKeys:
    reaperscans: str = "reaperscans"
    flamecomics: str = "flamecomics"
    omegascans: str = "omegascans"
    novelmic: str = "novelmic"
    mangapark: str = "mangapark"
    bato: str = "bato"
    gourmet: str = "gourmet"
    hivescans: str = "hivescans"


keys = CustomKeys()

scanlators[keys.reaperscans] = _ReaperScans(keys.reaperscans, **scanlators[keys.reaperscans])  # noqa: This is a dict
scanlators[keys.flamecomics] = _Flamecomics(keys.flamecomics, **scanlators[keys.flamecomics])  # noqa: This is a dict
scanlators[keys.omegascans] = _OmegaScans(keys.omegascans, **scanlators[keys.omegascans])  # noqa: This is a dict
scanlators[keys.novelmic] = _NovelMic(keys.novelmic, **scanlators[keys.novelmic])  # noqa: This is a dict
scanlators[keys.mangapark] = _Mangapark(keys.mangapark, **scanlators[keys.mangapark])  # noqa: This is a dict
scanlators[keys.bato] = _Bato(keys.bato, **scanlators[keys.bato])  # noqa: This is a dict
scanlators[keys.gourmet] = _GourmetScans(keys.gourmet, **scanlators[keys.gourmet])  # noqa: This is a dict
scanlators[keys.hivescans] = _Hivetoon(keys.hivescans, **scanlators[keys.hivescans])  # noqa: This is a dict
