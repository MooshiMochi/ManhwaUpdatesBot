import json
import re
from typing import Optional

import discord
from bs4 import BeautifulSoup
from discord import Embed

from src.core.objects import Chapter, PartialManga
from .classes import BasicScanlator, scanlators

__all__ = (
    "scanlators",
)

from ...html_json_parser import Parser

from ...static import Constants

from ...utils import raise_and_report_for_status, sort_key


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

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        text = await self._search_req(query)
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        manga_tags = soup.select(self.json_tree.selectors.search.container)
        found_manga: list[PartialManga | discord.Embed] = []
        for manga_tag in manga_tags:
            title = manga_tag.select_one(self.json_tree.selectors.search.title).get_text(strip=True)
            url = (self.json_tree.properties.base_url.removesuffix("/") +
                   manga_tag.select_one(self.json_tree.selectors.search.url).get("href"))
            cover = manga_tag.select_one(self.json_tree.selectors.search.cover).get("src")
            _id = await self.get_id(url)

            found_manga.append(PartialManga(_id, title, url, self.name, cover))

        # sort the manga by the closest match of the title to the query
        found_manga = sorted(found_manga, key=lambda x: sort_key(query, x.title), reverse=False)
        if len(found_manga) >= 10:
            found_manga = found_manga[:10]
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class _Hivetoon(BasicScanlator):

    @staticmethod
    def _parse_text_to_json(text: str) -> dict:
        raw_json_data = Parser.extract_balanced_json(text, start_key='"post":{')
        json_data = json.loads(raw_json_data)
        return json_data

    def _extract_chapters_from_html(self, text: str, url_name: str = None) -> list[Chapter]:
        data: dict = self._parse_text_to_json(text)
        found_chapters: list[Chapter] = []
        for i, ch in enumerate(reversed(data.get("chapters", []))):
            manga_url = self.json_tree.properties.format_urls.manga.format(url_name=url_name)
            chapter_url = manga_url + ch["slug"]
            chapter_name = ch["title"] or f"Chapter {ch['number']}"
            is_premium = ch["isPermanentlyLocked"] or (ch.get("price", 0) > 0) or ch["isLocked"] or not ch[
                "isAccessible"]
            found_chapters.append(Chapter(chapter_url, chapter_name, i, is_premium))
        return found_chapters

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        text = await self._get_text(self.json_tree.properties.latest_updates_url)
        # the reason we're doing the blow is that hivetoon shows both novels and magna in the same key,
        # so combining both basically allows us to track novels as well.
        all_results = []
        while True:
            start_key = '"initalPosts":['
            try:
                json_result = Parser.extract_balanced_json(text, start_key=start_key)
            except ValueError:
                break
            text = text.replace(start_key, "remove_start_key", 1)
            all_results.extend(json.loads(json_result))

        return await self._extract_partial_manga_from_json_list(all_results)

    async def _extract_partial_manga_from_json_list(self, json_list: list[dict]) -> list[PartialManga]:
        found_manga: list[PartialManga] = []
        for item_dict in json_list:
            title = item_dict["postTitle"]
            url = await self.format_manga_url(url_name=item_dict["slug"])
            cover = item_dict["featuredImage"]
            _id = await self.get_id(url)

            latest_chapters: list[Chapter] = []
            latest_chapters_resp: list[dict] = item_dict["chapters"]
            for i, chapter in enumerate(latest_chapters_resp):
                if i >= 3:  # only get the latest 3 chapters
                    break
                # the reason we only get the 1st 3 chapters is because hivetoon splits the chapters
                # into the latest 3 + 2 older chapters for some reason
                chapter_url = url.removesuffix("/") + "/" + chapter["slug"]
                chapter_name = f"Chapter {chapter['number']}"
                is_premium = chapter.get("isPermanentlyLocked", False) or (chapter.get("price", 0) > 0) or chapter[
                    "isLocked"] or not chapter[
                    "isAccessible"]
                latest_chapters.append(Chapter(chapter_url, chapter_name, 3 - i, is_premium))

            p_manga = PartialManga(_id, title, url, self.name, cover, latest_chapters[::-1])
            found_manga.append(p_manga)
        return found_manga

    async def get_synopsis(self, url):
        text = await self._get_text(url)
        synopsis = re.search(self.json_tree.selectors.synopsis, text).group(1)
        soup = BeautifulSoup(Parser.repair_mojibake(synopsis), "html.parser")
        synopsis = soup.get_text(separator=' ', strip=True)  # noqa: linter is confused about the method signature
        return ' '.join(synopsis.replace('\xa0', ' ').split())

    async def get_title(self, raw_url: str) -> str | None:
        text = await self._get_text(raw_url)
        title = re.search(self.json_tree.selectors.title[0], text).group(1)
        return title.strip()

    async def get_status(self, raw_url: str) -> Optional[str]:
        text = await self._get_text(raw_url)
        status = re.search(self.json_tree.selectors.status[0], text).group(1)
        return status.lower().title().strip()

    async def get_cover(self, raw_url: str) -> Optional[str]:
        text = await self._get_text(raw_url)
        cover = re.search(self.json_tree.selectors.cover[0], text).group(1)
        return cover.strip()

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        text = await self._search_req(query)
        search_results = json.loads(text)
        found_manga: list[PartialManga] = await self._extract_partial_manga_from_json_list(
            search_results.get("posts", []))
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class _VortexScans(_Hivetoon):
    pass


class _QiScans(_Hivetoon):
    @staticmethod
    def _parse_text_to_json(text: str) -> dict:
        raw_json_data = Parser.extract_balanced_json(text, start_key=r'\"series\":{')
        json_data = json.loads(raw_json_data)
        return json_data

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[Embed]:
        return await super(_Hivetoon, self).search(query, as_em)


class _Templescan(BasicScanlator):
    async def _search_req(self, query: str) -> list[dict]:
        search_url = self.json_tree.search.url
        resp = await self.bot.session.get(search_url)
        await raise_and_report_for_status(self.bot, resp)
        return resp.json()

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        search_result: list[dict] = await self._search_req(query)
        found_manga: list[PartialManga] = []

        for item_dict in search_result:
            title = item_dict["title"]
            url = self.json_tree.properties.format_urls.manga.format(url_name=item_dict["series_slug"])
            cover = item_dict["thumbnail"]
            _id = await self.get_id(url)
            # This endpoint does support the latest 2 chapters,
            # but we can't tell if they're premium, so we won't use them
            p_manga = PartialManga(_id, title, url, self.name, cover)
            found_manga.append(p_manga)
        # sort the manga by closest match of the title to the query
        found_manga = sorted(found_manga, key=lambda x: sort_key(query, x.title), reverse=False)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class CustomKeys:
    flamecomics: str = "flamecomics"
    omegascans: str = "omegascans"
    novelmic: str = "novelmic"
    mangapark: str = "mangapark"
    bato: str = "bato"
    gourmet: str = "gourmet"
    hivescans: str = "hivescans"
    templescan: str = "templescan"
    vortexscans: str = "vortexscans"
    qiscans: str = "qiscans"


keys = CustomKeys()

scanlators[keys.flamecomics] = _Flamecomics(keys.flamecomics, **scanlators[keys.flamecomics])  # noqa: This is a dict
scanlators[keys.omegascans] = _OmegaScans(keys.omegascans, **scanlators[keys.omegascans])  # noqa: This is a dict
scanlators[keys.novelmic] = _NovelMic(keys.novelmic, **scanlators[keys.novelmic])  # noqa: This is a dict
scanlators[keys.mangapark] = _Mangapark(keys.mangapark, **scanlators[keys.mangapark])  # noqa: This is a dict
scanlators[keys.bato] = _Bato(keys.bato, **scanlators[keys.bato])  # noqa: This is a dict
scanlators[keys.gourmet] = _GourmetScans(keys.gourmet, **scanlators[keys.gourmet])  # noqa: This is a dict
scanlators[keys.hivescans] = _Hivetoon(keys.hivescans, **scanlators[keys.hivescans])  # noqa: This is a dict
scanlators[keys.templescan] = _Templescan(keys.templescan, **scanlators[keys.templescan])  # noqa: This is a dict
scanlators[keys.vortexscans] = _VortexScans(keys.vortexscans, **scanlators[keys.vortexscans])  # noqa: This is a dict
scanlators[keys.qiscans] = _QiScans(keys.qiscans, **scanlators[keys.qiscans])  # noqa: This is a dict
