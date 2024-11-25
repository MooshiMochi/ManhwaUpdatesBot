import json
import re

import discord
from bs4 import BeautifulSoup

from src.core.objects import Chapter, PartialManga
from .classes import BasicScanlator, scanlators

__all__ = (
    "scanlators",
)

from ...static import Constants

from ...utils import raise_and_report_for_status


class _OmegaScans(BasicScanlator):
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

    async def get_id(self, raw_url: str) -> str | None:
        async with self.bot.session.get(raw_url) as resp:
            await raise_and_report_for_status(self.bot, resp)
            manga_id = re.search(r'\\"series_id\\":(\d+),', await resp.text()).group(1)
            return manga_id

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

            chapter = item_dict["latest_chapter"]
            base_chapter_url = await self.format_manga_url(url_name=item_dict["series_slug"])
            chapter_url = base_chapter_url.removesuffix("/") + "/" + chapter["chapter_slug"]
            chapter_name = chapter["chapter_name"]
            is_premium_chapter = "price" in chapter.keys() and chapter["price"] > 0
            if chapter.get("chapter_title") is not None:
                chapter_name += f" - {chapter['chapter_title']}"
            last_chapter = Chapter(chapter_url, chapter_name, 987654321, is_premium=is_premium_chapter)

            p_manga = PartialManga(_id, title, url, self.name, cover, [last_chapter])
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga

    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        url_name = await self._get_url_name(raw_url)
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
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

    async def get_id(self, raw_url: str) -> str | None:
        async with self.bot.session.get(raw_url) as resp:
            await raise_and_report_for_status(self.bot, resp)
            manga_id = re.search(r'\\"series_id\\":(\d+),', await resp.text()).group(1)
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
        url_name = await self._get_url_name(raw_url)
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


class _Zinmanga(BasicScanlator):
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

    async def get_all_chapters(self, raw_url: str, current_page: int = 1, max_page: int | None = None) -> list[Chapter]:
        url_name = await self._get_url_name(raw_url)
        _id = await self.get_id(raw_url)
        is_1st_request = current_page == 1
        if is_1st_request:
            req_url = self.json_tree.properties.format_urls.manga.format(url_name=url_name, id=_id)
        else:
            req_url = self.json_tree.properties.format_urls.ajax.format(url_name=url_name, id=_id)
        if url_name is None:
            req_url = req_url.removesuffix("None" if not req_url.endswith("None/") else "None/")

        req_url = req_url.replace("{page}", str(current_page))
        text = await self._get_text(req_url, method="GET")  # noqa

        if not is_1st_request:
            text = json.loads(text)["list_chap"]
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)
        sel = "ul#nav_list_chapter_id_detail>li:last-child>a,ul#nav_list_chapter_id_detail>li:last-child.active>span"
        last_page_tag = soup.select_one(sel)

        chapters = self._extract_chapters_from_html(text)
        if is_1st_request:
            if not last_page_tag:
                return chapters
            else:
                max_page = int(last_page_tag.get_text(strip=True))
        if current_page < max_page:
            chapters[:0] = await self.get_all_chapters(raw_url, current_page + 1, max_page)
        for i, chap in enumerate(chapters):
            chap.index = i
        return chapters


class _Flamecomics(BasicScanlator):
    def _extract_chapters_from_html(self, text: str) -> list[Chapter]:
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


class CustomKeys:
    reaperscans: str = "reaperscans"
    flamecomics: str = "flamecomics"
    omegascans: str = "omegascans"
    novelmic: str = "novelmic"
    mangapark: str = "mangapark"
    bato: str = "bato"
    gourmet: str = "gourmet"


keys = CustomKeys()

scanlators[keys.reaperscans] = _ReaperScans(keys.reaperscans, **scanlators[keys.reaperscans])  # noqa: This is a dict
scanlators[keys.flamecomics] = _Flamecomics(keys.flamecomics, **scanlators[keys.flamecomics])  # noqa: This is a dict
scanlators[keys.omegascans] = _OmegaScans(keys.omegascans, **scanlators[keys.omegascans])  # noqa: This is a dict
scanlators[keys.novelmic] = _NovelMic(keys.novelmic, **scanlators[keys.novelmic])  # noqa: This is a dict
scanlators[keys.mangapark] = _Mangapark(keys.mangapark, **scanlators[keys.mangapark])  # noqa: This is a dict
scanlators[keys.bato] = _Bato(keys.bato, **scanlators[keys.bato])  # noqa: This is a dict
scanlators[keys.gourmet] = _GourmetScans(keys.gourmet, **scanlators[keys.gourmet])  # noqa: This is a dict
# scanlators[keys.zinmanga] = _Zinmanga(keys.zinmanga, **scanlators[keys.zinmanga])  # noqa: This is a dict
