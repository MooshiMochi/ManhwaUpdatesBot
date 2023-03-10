import asyncio

from typing import Any, Dict, List, Optional
from src.core.cache import CachedClientSession


class MangaDexAPI:
    def __init__(
        self,
        session: Optional[CachedClientSession] = None,
    ):
        self.api_url: str = "https://api.mangadex.org"
        self.session = session or CachedClientSession()
        self.headers = {
            "User-Agent": "github.com/MooshiMochi/ManhwaUpdatesBot",
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
    ) -> Dict[str, Any]:
        url = f"{self.api_url}/{endpoint}"
        if not headers:
            headers = self.headers

        if self.rate_limit_remaining is not None and self.rate_limit_remaining == 0:
            await asyncio.sleep(self.rate_limit_reset)

        async with self.session.request(
            method, url, params=params, json=data, headers=headers
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
        endpoint = f"manga/{manga_id}"
        return await self.__request("GET", endpoint)

    async def get_chapters_list(
        self, manga_id: str, languages=None
    ) -> list[Dict[str, Any]]:
        """Return a list of chapters in ascending order"""
        if languages is None:
            languages = ["en"]
        endpoint = f"manga/{manga_id}/feed"
        result = await self.__request(
            "GET", endpoint, params={
                "translatedLanguage[]": languages, "order[chapter]": "desc", "order[volume]": "desc", "limit": 50
            }
        )
        for x in range(len(result.copy())):
            if result["data"][x]["attributes"]["volume"] is None:
                result["data"][x]["attributes"]["volume"] = 0
        result = sorted(result["data"], key=lambda _x: (
            float(_x['attributes']['volume'] or 0), float(_x['attributes']['chapter'])
        ))
        return list(result)

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
        return await self.__request("GET", endpoint, params=params)

    async def get_cover(self, manga_id: str, cover_id: str) -> str:
        endpoint = f"cover/{cover_id}"
        result = await self.__request("GET", endpoint)
        fileName = result["data"]["attributes"]["fileName"]
        return f"https://uploads.mangadex.org/covers/{manga_id}/{fileName}"
