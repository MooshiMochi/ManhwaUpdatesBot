from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.apis import APIManager
    from src.static import R_METHOD_LITERAL

import aiohttp
from fuzzywuzzy import fuzz


def _levenshtein_distance(a: str, b: str) -> int:
    return fuzz.ratio(a, b)


class ZeroScansAPI:
    def __init__(
            self,
            api_manager: APIManager
    ):
        self.api_url: str = "https://zscans.com"
        self.manager = api_manager
        self.headers = {
            # "User-Agent": "github.com/MooshiMochi/ManhwaUpdatesBot",
        }
        self.rate_limit_remaining = 30
        self.rate_limit_reset = datetime.now().timestamp() + 60

    async def __request(
            self,
            method: R_METHOD_LITERAL,
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

        try:
            response = await self.manager.session.request(method, url, params=params, json=data, headers=headers,
                                                          **kwargs)
            json_data = response.json()
            if limit_remaining := response.headers.get("X-RateLimit-Remaining"):
                self.rate_limit_remaining = int(limit_remaining)
            else:
                self.rate_limit_remaining -= 1

            if limit_reset := response.headers.get("X-RateLimit-Reset"):
                self.rate_limit_reset = int(limit_reset)
            else:
                if datetime.now().timestamp() > self.rate_limit_reset:
                    self.rate_limit_reset = datetime.now().timestamp() + 60
                    self.rate_limit_remaining = 300

            if response.status_code != 200:
                raise Exception(
                    f"Request failed with status {response.status_code}: {json_data}"
                )
            return json_data
        except aiohttp.ServerDisconnectedError:
            if kwargs.get("call_depth", 0) > 3:
                raise Exception("Server disconnected too many times, aborting request")
            kwargs["call_depth"] = kwargs.get("call_depth", 0) + 1
            self.manager.session.logger.error("Server disconnected, retrying request...")
            return await self.__request(method, endpoint, params, data, headers, **kwargs)

    async def get_manga(self, url_name: str) -> Dict[str, Any]:
        endpoint = f"swordflake/comic/{url_name}"
        return await self.__request("GET", endpoint)

    async def get_manga_id(self, url_name: str) -> str:
        endpoint = f"swordflake/comic/{url_name}"
        return str((await self.__request("GET", endpoint))["data"]["id"])

    async def get_latest_chapters(self) -> list[dict]:
        endpoint = "swordflake/new-chapters"
        params = {"c[]": "7"}
        result = await self.__request("GET", endpoint, params=params)
        return result.get("all", [])

    async def get_synopsis(self, url_name: str) -> Optional[str]:
        manga = await self.get_manga(url_name)
        return manga.get("data", {}).get("summary")

    async def get_chapters_list(
            self, manga_id: str, page: int = 1
    ) -> list[Dict[str, Any]]:
        """Return a list of chapters in ascending order"""
        params = {"page": page}
        endpoint = f"swordflake/comic/{manga_id}/chapters"
        result = await self.__request(
            "GET", endpoint, params=params
        )
        data = result["data"]
        current_page = data["current_page"]
        last_page = data["last_page"]

        chapters = data["data"]
        if current_page < last_page:
            chapters.extend(await self.get_chapters_list(manga_id, page + 1))
        return list(chapters)

    async def search(
            self,
            title: str,
            limit: Optional[int] = None,
    ) -> list[dict]:
        endpoint = "swordflake/comics"
        kwargs = {}
        # because of the way they implemented the search feature, we can use cache for this endpoint
        # if isinstance(self.manager.session, CachedClientSession):
        #     kwargs["cache_time"] = 0
        results = await self.__request("GET", endpoint, **kwargs)
        results = results["data"].get("comics", [])
        results = sorted(results, key=lambda x: _levenshtein_distance(title, x["name"]), reverse=True)
        if limit is not None:
            return list(results)[:limit]
        return list(results)

    async def get_cover(self, url_name: str) -> str:
        manga = await self.get_manga(url_name)
        return (
                manga["data"]["cover"].get("full") or
                manga["data"]["cover"].get("vertical") or
                manga["data"]["cover"].get("horizontal")
        )
