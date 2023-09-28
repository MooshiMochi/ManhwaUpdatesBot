import re
from urllib.parse import quote_plus as url_encode

import discord
from bs4 import BeautifulSoup, Tag

from src.core.objects import Chapter, PartialManga
from .classes import BasicScanlator, NoStatusBasicScanlator, scanlators

__all__ = (
    "scanlators",
)


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


class _OmegaScans(NoStatusBasicScanlator):
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

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
            params = {self.json_tree.search.search_param_name: query} | extra_params
            request_kwargs = {
                "url": search_url, "params": params, "method": self.json_tree.search.request_method
            }

        if self.json_tree.request_method == "http":
            # noinspection PyProtectedMember
            resp = await self.bot.session._request(**request_kwargs)
            resp.raise_for_status()
            json_resp = await resp.json()
        else:  # req method is "curl"
            resp = await self.bot.curl_session.request(**request_kwargs)
            resp.raise_for_status()
            json_resp = resp.json()

        # here we have the resp object

        found_manga: list[PartialManga] = []

        for item_dict in json_resp:
            title = item_dict["title"]
            url = self.json_tree.properties.format_urls.manga.format(url_name=item_dict["series_slug"])
            cover = item_dict["thumbnail"]
            _id = await self.get_id(url)

            p_manga = PartialManga(_id, title, url, self.name, cover_url=cover)
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class CustomKeys:
    reaperscans: str = "reaperscans"
    omegascans: str = "omegascans"


keys = CustomKeys()

scanlators[keys.reaperscans] = _ReaperScans(keys.reaperscans, **scanlators[keys.reaperscans])  # noqa: This is a dict
scanlators[keys.omegascans] = _OmegaScans(keys.omegascans, **scanlators[keys.omegascans])  # noqa: This is a dict
