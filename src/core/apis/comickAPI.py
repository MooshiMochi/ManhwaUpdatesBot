from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.apis import APIManager
import aiohttp

from src.core.cache import CachedClientSession


class ComickAppAPI:
    def __init__(
            self,
            api_manager: APIManager
    ):
        self.api_url: str = "https://api.comick.fun"
        self.manager = api_manager
        self.headers = {
            # "User-Agent": "github.com/MooshiMochi/ManhwaUpdatesBot",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        self.rate_limit_remaining = None
        self.rate_limit_reset = None

    async def __request(
            self,
            method: str,
            endpoint: str,
            params: Optional[Dict[str, Any]] = None,
            data: Optional[Dict[str, Any]] = None,
            headers: Optional[Dict[str, Any]] = None,
            **kwargs
    ) -> Dict[str, Any] | List[Dict[str, Any]]:
        url = f"{self.api_url}/{endpoint}"
        if not headers:
            headers = self.headers

        if self.rate_limit_remaining is not None and self.rate_limit_remaining == 0:
            await asyncio.sleep(self.rate_limit_reset)
        try:
            response = await self.manager.bot.curl_session.request(method, url, params=params, json=data,
                                                                   headers=headers, **kwargs)
            if response.status_code != 200:
                raise Exception(
                    f"Request failed with status {response.status_code}\nURL: {response.url}"
                )
            json_data = response.json()
            self.rate_limit_remaining = int(
                response.headers.get("X-RateLimit-Remaining", "-1")
            )
            self.rate_limit_reset = int(response.headers.get("X-RateLimit-Reset", "-1"))
            return json_data

        except aiohttp.ServerDisconnectedError:
            if kwargs.get("call_depth", 0) > 3:
                raise Exception("Server disconnected too many times, aborting request")
            kwargs["call_depth"] = kwargs.get("call_depth", 0) + 1

            self.manager.session.logger.error("Server disconnected, retrying request...")
            return await self.__request(method, endpoint, params, data, headers, **kwargs)

    async def get_manga(self, url_name: str, used_prefixes: set[str] | None = None) -> Dict[str, Any]:
        if not used_prefixes:
            used_prefixes = set()
        possible_prefixes = {None, '00', '01', '02', '03', '04', '05'} - used_prefixes
        match = re.match(r"(\d{2})-", url_name)
        curr_prefix = match.group(1) if match else None

        if curr_prefix in possible_prefixes:
            possible_prefixes.remove(curr_prefix)

        used_prefixes.add(curr_prefix)
        endpoint = f"comic/{url_name}"
        try:
            result = await self.__request("GET", endpoint)
            if len(used_prefixes) > 1:
                self.manager.session.logger.debug(f"✅ Success!")
                result['new_prefix'] = curr_prefix
            else:
                result['new_prefix'] = None
            return result
        except Exception as e:
            if not possible_prefixes:
                raise Exception(f"❌ Exhausted all possbile prefixes for {url_name}\n{e.__traceback__}")

            new_prefix = possible_prefixes.pop()
            if new_prefix is None:
                new_url_name = url_name[3:] if match else url_name
            else:
                new_url_name = f"{new_prefix}-{url_name}" if not match else f"{new_prefix}{url_name[2:]}"
            self.manager.session.logger.debug(
                f"❌ Failed to get manga with url_name {url_name}\nTrying with {new_url_name}")
            return await self.get_manga(new_url_name, used_prefixes | {new_prefix})

    async def get_id(self, url_name: str) -> str:
        data = await self.get_manga(url_name)
        return data["comic"]["hid"]

    async def get_synopsis(self, url_name: str) -> Optional[str]:
        data = await self.get_manga(url_name)
        return data.get("comic", {}).get("desc", None)

    @staticmethod
    def _remove_duplicate_chapters(chapters):
        chapter_dict = {}
        for chapter in chapters:
            if chapter["chap"] is None:
                continue

            # apply type conversion
            if not isinstance(chapter["chap"], (int, float)):
                chapter["chap"] = float(chapter["chap"]) if "." in chapter["chap"] else int(chapter["chap"])
            if chapter["vol"] is not None and not isinstance(chapter["vol"], (int, float)):
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
        result = [value[0] for value in chapter_dict.values()]
        return result

    async def get_chapters_list(self, manga_id: str, language: str = None, page: int = 1) -> list[Dict[str, Any]]:
        """Return a list of chapters in ascending order"""
        if language is None:
            language = "en"
        endpoint = f"comic/{manga_id}/chapters?lang={language}&page={page}"
        # params = {"lang": language, "page": page}
        result = await self.__request("GET", endpoint)

        if result["chapters"]:
            result["chapters"].extend(await self.get_chapters_list(manga_id, language, page + 1))

        result["chapters"] = self._remove_duplicate_chapters(result["chapters"])
        result = sorted(result["chapters"], key=lambda _x: float(_x['chap']))
        return list(result)

    async def search(
            self,
            query: str = None,
            page: Optional[int] = None,
            limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        endpoint = "v1.0/search"
        params = {
            "q": query,
            "limit": limit,
            "page": 1 if page is None else page,
            "t": "true"
        }
        params = {k: v for k, v in params.items() if v is not None}
        kwargs = {}
        if isinstance(self.manager.session, CachedClientSession):
            kwargs["cache_time"] = 0
        return await self.__request("GET", endpoint, params=params, **kwargs)

    async def get_cover(self, manga_id: str) -> str | None:
        data = await self.get_manga(manga_id)
        covers = data["comic"]["md_covers"]
        if not covers:
            return None
        cover_filename = covers[0]["b2key"]
        return f"https://meo.comick.pictures/{cover_filename}"
