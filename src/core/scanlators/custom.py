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

            p_manga = PartialManga(_id, title, url, self.name, cover_url=cover)
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga

    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        url_name = await self._get_url_name(raw_url)
        chapters: list[dict] = await self.bot.apis.omegascans.get_chapters_list(url_name)
        found_chapters: list[Chapter] = []
        for i, chapter in enumerate(chapters):
            base_chapter_url = await self.format_manga_url(url_name=url_name)
            chapter_url = base_chapter_url.removesuffix("/") + "/" + chapter["chapter_slug"]
            chapter_name = chapter["chapter_name"]
            if chapter["chapter_title"] is not None:
                chapter_name += f" - {chapter['chapter_title']}"
            found_chapters.append(Chapter(chapter_url, chapter_name, i))
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


class _Mangapark(BasicScanlator):
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)
        self.apo_url = self.json_tree.properties.base_url + "/apo/"

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        data = {
            "query": """
                query get_content_browse_search($select: ComicSearchSelect) {
                    get_content_browse_search(
                        select: $select
                    ) {
                        reqPage reqSize reqSort reqWord
                        paging { total pages page size skip }
                        items {
                            id
                            data {
                                id
                                dbStatus
                                isNormal
                                isHidden
                                isDeleted
                                dateCreate datePublic dateModify
                                dateUpload dateUpdate
                                name
                                slug
                                altNames
                                authors
                                artists
                                genres
                                originalLanguage
                                originalStatus
                                originalInfo
                                originalPubFrom
                                originalPubTill
                                readDirection
                                summary {
                                    code
                                }
                                extraInfo {
                                    code
                                }
                                urlPath
                                urlCover600
                                urlCover300
                                urlCoverOri
                                disqusId
                            }
                            max_chapterNode {
                                id
                                data {
                                    id
                                    sourceId
                                    dbStatus
                                    isNormal
                                    isHidden
                                    isDeleted
                                    isFinal
                                    dateCreate
                                    datePublic
                                    dateModify
                                    lang
                                    volume
                                    serial
                                    dname
                                    title
                                    urlPath
                                    srcTitle srcColor
                                    count_images
                                }
                            }
                            sser_followed
                            sser_lastReadChap {
                                date
                                chapterNode {
                                    id
                                    data {
                                        id
                                        sourceId
                                        dbStatus
                                        isNormal
                                        isHidden
                                        isDeleted
                                        isFinal
                                        dateCreate
                                        datePublic
                                        dateModify
                                        lang
                                        volume
                                        serial
                                        dname
                                        title
                                        urlPath
                                        srcTitle srcColor
                                        count_images
                                    }
                                }
                            }
                        }
                    }
                }
            """,
            "variables": {
                "select": {
                    "word": "he'l",
                    "sort": None,
                    "page": 1,
                    "incGenres": [],
                    "excGenres": [],
                    "origLang": None,
                    "oficStatus": None,
                    "chapCount": None
                }
            },
            "operationName": "get_content_browse_search"
        }
        data["variables"]["select"]["word"] = query
        async with self.bot.session.post(self.apo_url, json=data) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if not data:
            return []

        found_manga: list[PartialManga] = []
        for result_dict in data["data"]["get_content_browse_search"]["items"]:
            title = result_dict["data"]["name"]
            url = self.json_tree.properties.base_url + result_dict["data"]["urlPath"]
            cover = result_dict["data"]["urlCoverOri"]
            _id = result_dict["data"]["id"]

            p_manga = PartialManga(_id, title, url, self.name, cover_url=cover)
            found_manga.append(p_manga)

        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        data = {
            "query": "query get_content_browse_latest($select: ComicLatestSelect) {\n  get_content_browse_latest("
                     "select: $select) {\n    reqLimit\n    reqStart\n    newStart\n    items {\n      comic {\n      "
                     "  id\n        data {\n          id\n          dbStatus\n          isNormal\n          "
                     "isHidden\n          isDeleted\n          dateCreate\n          datePublic\n          "
                     "dateModify\n          dateUpload\n          dateUpdate\n          name\n          slug\n        "
                     "  altNames\n          authors\n          artists\n          genres\n          "
                     "originalLanguage\n          originalStatus\n          originalInfo\n          originalPubFrom\n "
                     "         originalPubTill\n          readDirection\n          summary {\n            code\n      "
                     "    }\n          extraInfo {\n            code\n          }\n          urlPath\n          "
                     "urlCover600\n          urlCover300\n          urlCoverOri\n          disqusId\n          "
                     "stat_is_hot\n          stat_is_new\n          stat_count_follow\n          stat_count_review\n  "
                     "        stat_count_post_child\n          stat_count_post_reply\n          stat_count_mylists\n  "
                     "        stat_count_vote\n          stat_count_note\n          stat_count_emotions {\n           "
                     " field\n            count\n          }\n          stat_count_statuss {\n            field\n     "
                     "       count\n          }\n          stat_count_scores {\n            field\n            "
                     "count\n          }\n          stat_count_views {\n            field\n            count\n        "
                     "  }\n          stat_score_avg\n          stat_score_bay\n          stat_score_val\n          "
                     "chart_count_chapters_all\n          chart_count_chapters_bot\n          "
                     "chart_count_chapters_usr\n          chart_count_serials_all\n          "
                     "chart_count_serials_bot\n          chart_count_serials_usr\n          chart_count_langs_all\n   "
                     "       chart_count_langs_bot\n          chart_count_langs_usr\n          chart_max_chapterId\n  "
                     "        chart_max_serial_val\n          chart_count_sources_all\n          "
                     "chart_count_sources_bot\n          chart_count_sources_usr\n          "
                     "chart_count_lang_to_chapters {\n            field\n            count\n          }\n          "
                     "chart_count_lang_to_serials {\n            field\n            count\n          }\n          "
                     "userId\n          userNode {\n            id\n            data {\n              id\n            "
                     "  name\n              uniq\n              avatarUrl\n              urlPath\n              "
                     "verified\n              deleted\n              banned\n              dateCreate\n              "
                     "dateOnline\n              stat_count_chapters_normal\n              "
                     "stat_count_chapters_others\n              is_adm\n              is_mod\n              is_vip\n  "
                     "            is_upr\n            }\n          }\n        }\n        sser_followed\n        "
                     "sser_lastReadChap {\n          date\n          chapterNode {\n            id\n            data "
                     "{\n              id\n              sourceId\n              dbStatus\n              isNormal\n   "
                     "           isHidden\n              isDeleted\n              isFinal\n              dateCreate\n "
                     "             datePublic\n              dateModify\n              lang\n              volume\n   "
                     "           serial\n              dname\n              title\n              urlPath\n            "
                     "  srcTitle\n              srcColor\n              count_images\n              "
                     "stat_count_post_child\n              stat_count_post_reply\n              "
                     "stat_count_views_login\n              stat_count_views_guest\n              userId\n            "
                     "  userNode {\n                id\n                data {\n                  id\n                "
                     "  name\n                  uniq\n                  avatarUrl\n                  urlPath\n        "
                     "          verified\n                  deleted\n                  banned\n                  "
                     "dateCreate\n                  dateOnline\n                  stat_count_chapters_normal\n        "
                     "          stat_count_chapters_others\n                  is_adm\n                  is_mod\n      "
                     "            is_vip\n                  is_upr\n                }\n              }\n              "
                     "disqusId\n            }\n          }\n        }\n      }\n      chapters {\n        id\n        "
                     "data {\n          id\n          sourceId\n          dbStatus\n          isNormal\n          "
                     "isHidden\n          isDeleted\n          isFinal\n          dateCreate\n          datePublic\n  "
                     "        dateModify\n          lang\n          volume\n          serial\n          dname\n       "
                     "   title\n          urlPath\n          srcTitle\n          srcColor\n          count_images\n   "
                     "       stat_count_post_child\n          stat_count_post_reply\n          "
                     "stat_count_views_login\n          stat_count_views_guest\n          userId\n          userNode "
                     "{\n            id\n            data {\n              id\n              name\n              "
                     "uniq\n              avatarUrl\n              urlPath\n              verified\n              "
                     "deleted\n              banned\n              dateCreate\n              dateOnline\n             "
                     " stat_count_chapters_normal\n              stat_count_chapters_others\n              is_adm\n   "
                     "           is_mod\n              is_vip\n              is_upr\n            }\n          }\n     "
                     "     disqusId\n        }\n      }\n    }\n  }\n}",
            "variables": {
                "select": {
                    "incGenres": [],
                    "excGenres": [],
                    "incTLangs": [],
                    "where": "latest",
                    "limit": 80,
                }
            },
            "operationName": "get_content_browse_latest"
        }

        async with self.bot.session.post(self.apo_url, json=data) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if not data:
            return []
        found_manga: list[PartialManga] = []
        for result_dict in data["data"]["get_content_browse_latest"]["items"]:
            title = result_dict["comic"]["data"]["name"]
            url = self.json_tree.properties.base_url + result_dict["comic"]["data"]["urlPath"]
            cover = result_dict["comic"]["data"]["urlCoverOri"]
            _id = result_dict["comic"]["data"]["id"]
            chapters: list[Chapter] = []
            for chapter in reversed(result_dict["chapters"]):
                chapter_url = self.json_tree.properties.base_url + chapter["data"]["urlPath"]
                chapter_name = chapter["data"]["dname"]
                chapters.append(Chapter(chapter_url, chapter_name, chapter["data"]["serial"] - 1))
            p_manga = PartialManga(_id, title, url, self.name, cover_url=cover, latest_chapters=chapters)
            found_manga.append(p_manga)

        return found_manga

    async def get_all_chapters(self, raw_url: str) -> list[Chapter]:
        data = {
            "query": """query get_content_comicChapterRangeList($select: Content_ComicChapterRangeList_Select) {
                            get_content_comicChapterRangeList(select: $select) {
                                reqRange{x y}
                                missing
                                pager {x y}
                                items{
                                    serial
                                    chapterNodes {
                                        id
                                        data {
                                            isNormal
                                            isHidden
                                            lang
                                            volume
                                            serial
                                            dname
                                            urlPath
                                                }
                                            }
                                        }
                                    }
                                }""",
            "variables": {
                "select": {
                    "comicId": 378353,
                    "range": None,
                    "isAsc": False
                }
            },
            "operationName": "get_content_comicChapterRangeList"
        }
        _id = await self.get_id(raw_url)
        data["variables"]["select"]["comicId"] = int(_id)

        async with self.bot.session.post(self.apo_url, json=data) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if not data:
            return []
        chapter_nodes = data["data"]["get_content_comicChapterRangeList"]["items"]
        found_chapters: list[Chapter] = []
        for nodes in reversed(chapter_nodes):
            node = nodes["chapterNodes"][0]
            chapter = node["data"]
            chapter_url = self.json_tree.properties.base_url + chapter["urlPath"]
            chapter_name = chapter["dname"]
            found_chapters.append(Chapter(chapter_url, chapter_name, chapter["serial"] - 1))
        return found_chapters


class CustomKeys:
    reaperscans: str = "reaperscans"
    omegascans: str = "omegascans"
    rizzcomic: str = "rizzcomic"
    novelmic: str = "novelmic"
    mangapark: str = "mangapark"


keys = CustomKeys()

scanlators[keys.reaperscans] = _ReaperScans(keys.reaperscans, **scanlators[keys.reaperscans])  # noqa: This is a dict
scanlators[keys.omegascans] = _OmegaScans(keys.omegascans, **scanlators[keys.omegascans])  # noqa: This is a dict
scanlators[keys.rizzcomic] = _Rizzcomic(keys.rizzcomic, **scanlators[keys.rizzcomic])  # noqa: This is a dict
scanlators[keys.novelmic] = _NovelMic(keys.novelmic, **scanlators[keys.novelmic])  # noqa: This is a dict
scanlators[keys.mangapark] = _Mangapark(keys.mangapark, **scanlators[keys.mangapark])  # noqa: This is a dict
