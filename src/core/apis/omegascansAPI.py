from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.apis import APIManager

import aiohttp
from bs4 import BeautifulSoup

from src.core.cache import CachedClientSession


class OmegaScansAPI:
    def __init__(
            self,
            api_manager: APIManager
    ):
        self.api_url: str = "https://api.omegascans.org"
        self.manager: APIManager = api_manager
        self.headers = {
            # "User-Agent": "github.com/MooshiMochi/ManhwaUpdatesBot",
        }
        self.rate_limit_remaining = 300
        self.rate_limit_reset = datetime.now().timestamp() + 60

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

        try:
            async with self.manager.session.request(
                    method, url, params=params, json=data, headers=headers, **kwargs
            ) as response:
                json_data = await response.json()
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

                if response.status != 200:
                    raise Exception(
                        f"Request failed with status {response.status}: {json_data}"
                    )
                return json_data
        except aiohttp.ServerDisconnectedError:
            if kwargs.get("call_depth", 0) > 3:
                raise Exception("Server disconnected too many times, aborting request")
            kwargs["call_depth"] = kwargs.get("call_depth", 0) + 1
            self.manager.session.logger.error("Server disconnected, retrying request...")
            return await self.__request(method, endpoint, params, data, headers, **kwargs)

    async def get_manga(self, url_name: str) -> Dict[str, Any]:
        endpoint = f"series/{url_name}"
        return await self.__request("GET", endpoint)

    async def get_synopsis(self, url_name: str) -> Optional[str]:
        manga = await self.get_manga(url_name)
        if (html_code := manga.get("description")) is not None:
            soup = BeautifulSoup(html_code, "html.parser")
            return soup.get_text(strip=True)
        return None

    async def get_chapters_list(
            self, manga_id: str, page: int = 1, limit: int = -1
    ) -> list[Dict[str, Any]]:
        """
        Summary:
            Return a list of chapters in ascending order

        Args:
            manga_id (str): The ID of the manga
            page: (int, optional): The page number to return. Defaults to 1.
            limit (int, optional): The number of chapters to return. Defaults to -1 (no limit).

        Returns:
            list[Dict[str, Any]]: A list of chapters in ascending order

        """
        if limit == 0:
            raise ValueError("limit must be greater than 0")

        endpoint = f"chapter/query?page={page}&perPage=30&series_id={manga_id}"
        result = await self.__request("GET", endpoint)
        metadata = result.get("meta", {})

        if not metadata.get("total", 0):  # No chapters available
            return []

        data = result.get("data", [])
        # Filter out any chapters that are for patreon only
        free_chapters = [x for x in data if x.get("price", 0) == 0]

        last_page = metadata.get("last_page", 1)
        current_page = metadata.get("current_page", 1)

        # Reverse the order of chapters to make it ascending
        free_chapters = free_chapters[::-1]

        # Check if there are more pages to fetch
        if current_page < last_page and (limit < 0 or len(free_chapters) < limit):
            next_limit = limit - len(free_chapters) if limit > 0 else -1
            next_page_chapters = await self.get_chapters_list(manga_id, page + 1, next_limit)
            # Since both lists are in ascending order, extend in reverse
            free_chapters = next_page_chapters + free_chapters

        if limit > 0:
            return free_chapters[:limit]

        return free_chapters

    async def search(self, title: str, limit: Optional[int] = None) -> list[Any]:
        endpoint = "query"
        params = {"adult": "true", "query_string": title}
        kwargs = {}
        if isinstance(self.manager.session, CachedClientSession):
            kwargs["cache_time"] = 0
        response = await self.__request("GET", endpoint, params=params, **kwargs)
        data = response.get("data", [])
        if limit is not None:
            data = list(data)[:limit]
        return data

    async def get_cover(self, url_name: str) -> Optional[str]:
        result = await self.get_manga(url_name)
        return result.get("thumbnail")

    async def get_title(self, url_name: str) -> Optional[str]:
        result = await self.get_manga(url_name)
        return result.get("title")

    async def get_status(self, url_name: str) -> Optional[str]:
        manga = await self.get_manga(url_name)
        return manga["status"]
