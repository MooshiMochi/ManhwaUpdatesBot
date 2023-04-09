import asyncio

from typing import Any, Dict, List, Optional
from src.core.cache import CachedClientSession


class ComickAppAPI:
    def __init__(
        self,
        session: Optional[CachedClientSession] = None,
    ):
        self.api_url: str = "https://api.comick.app"
        self.session = session or CachedClientSession()
        self.headers = {
            "User-Agent": "github.com/MooshiMochi/ManhwaUpdatesBot",
        }
        self.rate_limit_remaining = None
        self.rate_limit_reset = None

        # self.session.ignored_urls = self.session.ignored_urls.union({self.api_url + "/manga"})

    async def __request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        url = f"{self.api_url}/{endpoint}"
        if not headers:
            headers = self.headers

        if self.rate_limit_remaining is not None and self.rate_limit_remaining == 0:
            await asyncio.sleep(self.rate_limit_reset)

        async with self.session.request(
            method, url, params=params, json=data, headers=headers, **kwargs
        ) as response:
            json_data = await response.json()
            self.rate_limit_remaining = int(
                response.headers.get("X-RateLimit-Remaining", "-1")
            )
            self.rate_limit_reset = int(response.headers.get("X-RateLimit-Reset", "-1"))

            if response.status != 200:
                raise Exception(
                    f"Request failed with status {response.status}: {json_data}"
                )
            return json_data

    async def get_manga(self, manga_id: str) -> Dict[str, Any]:
        endpoint = f"comic/{manga_id}"
        return await self.__request("GET", endpoint)

    @staticmethod
    def _remove_duplicate_chapters(chapters):
        chapter_dict = {}
        for chapter in chapters:
            if chapter["chap"] is None:
                continue
            # elif chapter["chap"] is None:
            #     chapter["chap"] = "0." + chapter["vol"]

            chapter["chap"] = float(chapter["chap"]) if "." in chapter["chap"] else int(chapter["chap"])
            if chapter["vol"] is not None:
                chapter["vol"] = float(chapter["vol"]) if "." in chapter["vol"] else int(chapter["vol"])

            chap_number = chapter['chap']
            is_official = False
            for group in (chapter['group_name'] or []):
                if group == 'Official':
                    is_official = True
                    break
            if chap_number in chapter_dict:
                if is_official and not chapter_dict[chap_number][1]:
                    chapter_dict[chap_number] = (chapter, is_official)
                elif not chapter_dict[chap_number][1]:
                    chapter_dict[chap_number] = (chapter, is_official)
            else:
                chapter_dict[chap_number] = (chapter, is_official)

        return [value[0] for value in chapter_dict.values()]

    async def get_chapters_list(self, manga_id: str, language: str = None, page: int = 1) -> list[Dict[str, Any]]:
        """Return a list of chapters in ascending order"""
        if language is None:
            language = "en"
        endpoint = f"comic/{manga_id}/chapters?lang={language}&page={page}"
        # params = {"lang": language, "page": page}
        result = await self.__request("GET", endpoint)

        result["chapters"] = self._remove_duplicate_chapters(result["chapters"])

        if result["chapters"]:
            result["chapters"].extend(await self.get_chapters_list(manga_id, language, page + 1))

        result = sorted(result["chapters"], key=lambda _x: float(_x['chap']))
        return list(result)

    async def get_cover(self, manga_id: str) -> str | None:
        data = await self.get_manga(manga_id)
        covers = data["comic"]["md_covers"]
        if not covers:
            return None
        cover_filename = covers[0]["b2key"]
        return f"https://meo.comick.pictures/{cover_filename}"
