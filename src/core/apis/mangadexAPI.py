from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.apis import APIManager
import aiohttp

from src.core.cache import CachedClientSession


class MangaDexAPI:
    def __init__(
            self,
            api_manager: APIManager,
    ):
        self.api_url: str = "https://api.mangadex.org"
        self.manager: APIManager = api_manager
        self.headers = {
            "User-Agent": "github.com/MooshiMochi/ManhwaUpdatesBot",
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

    async def get_manga(self, manga_id: str) -> Dict[str, Any]:
        endpoint = f"manga/{manga_id}"
        return await self.__request("GET", endpoint)

    async def get_synopsis(self, manga_id: str) -> Optional[str]:
        manga = await self.get_manga(manga_id)
        if manga.get("data"):
            synopsis = manga['data']["attributes"]["description"].get("en")
            if not synopsis:
                # If the synopsis is not available in English, use the first available language.
                if len(manga['data']["attributes"]["description"].values()) > 0:
                    synopsis = next(iter(manga['data']["attributes"]["description"].values()))
            return synopsis
        return None

    async def get_chapters_list(
            self, manga_id: str, languages=None, offset: int = 0, limit: int = 100
    ) -> list[Dict[str, Any]]:
        """Return a list of chapters in ascending order"""
        if languages is None:
            languages = ["en"]
        endpoint = f"manga/{manga_id}/feed"
        params = {
            "translatedLanguage[]": languages, "order[chapter]": "asc", "offset": offset, "limit": limit
        }
        result = await self.__request(
            "GET", endpoint, params=params
        )
        chapters = result.get("data") or []

        total_displayed = result["total"]
        if total_displayed > limit + offset:
            chapters.extend(await self.get_chapters_list(manga_id, languages, offset + limit, limit))
        return list(chapters)

    async def search(
            self,
            title: Optional[str] = None,
            author: Optional[str] = None,
            artist: Optional[str] = None,
            year: Optional[str] = None,
            included_tags: Optional[List[str]] = None,
            excluded_tags: Optional[List[str]] = None,
            status: Optional[str] = None,
            order: Optional[str] = None,
            page: Optional[int] = None,
            limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        endpoint = "manga"
        params = {
            "title": title,
            "authors": author,
            "artists": artist,
            "year": year,
            "includedTags": included_tags,
            "excludedTags": excluded_tags,
            "status": status,
            "order": order,
            "offset": (page - 1) * limit if page and limit else None,
            "limit": limit,
        }
        params = {k: v for k, v in params.items() if v is not None}
        kwargs = {}
        if isinstance(self.manager.session, CachedClientSession):
            kwargs["cache_time"] = 0
        return await self.__request("GET", endpoint, params=params, **kwargs)

    async def get_cover(self, manga_id: str, cover_id: str) -> str:
        endpoint = f"cover/{cover_id}"
        result = await self.__request("GET", endpoint)
        fileName = result["data"]["attributes"]["fileName"]
        cover_url = f"https://uploads.mangadex.org/covers/{manga_id}/{fileName}"
        return cover_url
