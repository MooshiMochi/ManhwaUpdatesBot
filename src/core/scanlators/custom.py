import json
import re
from urllib.parse import quote_plus as url_encode

import discord
from bs4 import BeautifulSoup, Tag

from src.core.objects import Chapter, PartialManga
from .classes import BasicScanlator, DynamicURLScanlator, scanlators

__all__ = (
    "scanlators",
)

from ...static import Constants

from ...utils import raise_and_report_for_status


class _ReaperScans(BasicScanlator):
    def __init__(self, name, **kwargs):
        super().__init__(name, **kwargs)

    async def get_chapters_on_page(
            self, manga_url: str, *, page: int | None = None
    ) -> tuple[list[Chapter] | None, int]:
        """
        Returns a tuple of (list of chapters [descending order], max number of chapters there are)
        for the given manga page.

        Args:
            manga_url: str - the manga url
            page: int | None - the page number to get chapters from. If None, get all chapters

        Returns:
            tuple[list[Chapter] | None, int] - the list of chapters and max number of chapters there are
        """
        req_url = manga_url.removesuffix("/")[:max(manga_url.find("?"), len(manga_url))]
        if page is not None and page > 1:
            req_url += f"?page={page}"
        text = await self._get_text(req_url, "GET")
        soup = BeautifulSoup(text, "html.parser")
        self.remove_unwanted_tags(soup, self.json_tree.selectors.unwanted_tags)

        max_chapters = soup.select_one('dt.text-neutral-500:-soup-contains("Total Chapters") + dd').get_text(strip=True)
        max_chapters = int(max_chapters)
        chapter_selector = self.json_tree.selectors.chapters
        chapters: list[Tag] = soup.select(chapter_selector["container"])
        if not chapters:
            self.bot.logger.warning(f"Could not fetch the chapters on page {page} for {manga_url}")
            return None, max_chapters

        index_shift = 0
        nums = soup.select("div:first-child > ul[role=list] + div.px-4.py-4 p.text-sm.text-white > span.font-medium")
        if nums:
            nums = [int(num.get_text(strip=True)) for num in nums]
            index_shift = nums[2] - nums[0] - len(chapters) + 1

        found_chapters: list[Chapter] = []
        for i, chapter in enumerate(reversed(chapters)):
            if self.json_tree.selectors.front_page.chapters["url"] == "_container_":
                url = chapter.get("href")
            else:
                url = chapter.select_one(chapter_selector["url"]).get("href")
            if not url.startswith(self.json_tree.properties.base_url):
                url = self.json_tree.properties.base_url + url

            name = chapter.select_one(chapter_selector["name"]).get_text(strip=True)  # noqa: Invalid scope warning
            found_chapters.append(Chapter(url, name, i + index_shift))
        return found_chapters, max_chapters

    async def get_all_chapters(self, raw_url: str, page: int | None = None) -> list[Chapter] | None:
        if page is not None and page == 0:
            return (await self.get_chapters_on_page(raw_url, page=page))[0]

        max_chapters = float("inf")
        chapters: list[Chapter] = []
        while len(chapters) < max_chapters:
            next_page_chapters, max_chapters = await self.get_chapters_on_page(
                raw_url, page=page
            )
            if next_page_chapters is None:
                break
            chapters[:0] = next_page_chapters
            page = (page or 1) + 1
        if len(chapters) < max_chapters:
            # fill in the missing chapters
            chapters_to_fill = [
                Chapter(raw_url, f"Chapter {i + 1}", i)
                for i in range(max_chapters - len(chapters))
            ]
            chapters[:0] = chapters_to_fill  # inserts at the beginning
        return sorted(chapters, key=lambda x: x.index)

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        # ReaperScans does not have a search feature
        return []


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


class _Rizzcomic(DynamicURLScanlator):
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

    def extract_cover_link_from_tag(self, tag, base_url: str) -> str | None:
        for attr in ["data-src", "src", "href", "content", "data-lazy-src"]:
            result = tag.get(attr)
            if result is not None:
                if result.startswith("/"):  # partial URL, we just need to append base URL to it
                    return base_url + result
                elif not result.startswith("https://"):
                    continue
                return result

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
            request_kwargs = {
                "url": search_url + query, "method": self.json_tree.search.request_method
            }
        else:  # as param
            params = extra_params
            data = {self.json_tree.search.search_param_name: query}
            request_kwargs = {
                "url": search_url, "params": params, "method": self.json_tree.search.request_method, "data": data
            }

        if self.json_tree.request_method == "http":
            # noinspection PyProtectedMember
            resp = await self.bot.session._request(**request_kwargs)
            await raise_and_report_for_status(self.bot, resp)
            json_resp = await resp.text()
        else:  # req method is "curl"
            resp = await self.bot.curl_session.request(**request_kwargs)
            await raise_and_report_for_status(self.bot, resp)
            json_resp = resp.text
        json_resp = json.loads(json_resp)

        found_manga: list[PartialManga] = []

        for item_dict in json_resp:
            title = item_dict["title"]
            url_name = re.sub("[^a-zA-Z0-9-]+", "-", title).lower()
            url = self.json_tree.properties.format_urls.manga.format(url_name=url_name, id=self.manga_id)
            cover_filename = item_dict["image_url"]
            cover = f"https://realmscans.to/assets/images/{cover_filename}"
            _id = await self.get_id(url)

            p_manga = PartialManga(_id, title, url, self.name, cover_url=cover)
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


class _MangaparkAndBato(BasicScanlator):
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        chapters = await super().get_all_chapters(raw_url)
        # reverse the index
        for i, chap in enumerate(reversed(chapters)):
            chap.index = i
        return chapters[::-1]  # could sort based on index, but that will require more processing

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


class CustomKeys:
    reaperscans: str = "reaperscans"
    omegascans: str = "omegascans"
    rizzcomic: str = "rizzcomic"
    novelmic: str = "novelmic"
    mangapark: str = "mangapark"
    bato: str = "bato"


keys = CustomKeys()

scanlators[keys.reaperscans] = _ReaperScans(keys.reaperscans, **scanlators[keys.reaperscans])  # noqa: This is a dict
scanlators[keys.omegascans] = _OmegaScans(keys.omegascans, **scanlators[keys.omegascans])  # noqa: This is a dict
scanlators[keys.rizzcomic] = _Rizzcomic(keys.rizzcomic, **scanlators[keys.rizzcomic])  # noqa: This is a dict
scanlators[keys.novelmic] = _NovelMic(keys.novelmic, **scanlators[keys.novelmic])  # noqa: This is a dict
scanlators[keys.mangapark] = _MangaparkAndBato(keys.mangapark, **scanlators[keys.mangapark])  # noqa: This is a dict
scanlators[keys.bato] = _MangaparkAndBato(keys.bato, **scanlators[keys.bato])  # noqa: This is a dict
# scanlators[keys.zinmanga] = _Zinmanga(keys.zinmanga, **scanlators[keys.zinmanga])  # noqa: This is a dict
