from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.core.cache import CachedCurlCffiSession

if TYPE_CHECKING:
    from src.core.apis import APIManager
    from src.static import R_METHOD_LITERAL

import aiohttp
from bs4 import BeautifulSoup


class ReaperScansAPI:
    def __init__(
            self,
            api_manager: APIManager
    ):
        self.api_url: str = "https://api.reaperscans.com"
        self.manager: APIManager = api_manager
        self.headers = {
            # "User-Agent": "github.com/MooshiMochi/ManhwaUpdatesBot",
        }
        self.rate_limit_remaining = 300
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
        call_depth = kwargs.pop("call_depth", 0)  # remove call_depth from kwargs before making request

        try:
            response = await self.manager.session.request(
                method, url, params=params, json=data, headers=headers, **kwargs
            )
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
            if call_depth > 3:
                raise Exception("Server disconnected too many times, aborting request")
            kwargs["call_depth"] = call_depth + 1
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
            Recursively fetches and returns chapters in ascending order.
            First, premium (paid) chapters are fetched (newest first, then reversed),
            enforcing the limit on the fly.
            If the limit is not reached, free chapters
            are fetched similarly.
            The final list is built page‐by‐page so that older
            chapters are prepended, and the overall order is ascending.

        Args:
            manga_id (str): The ID of the manga.
            page (int, optional): The starting page number for fetching.
            Defaults to 1.
            limit (int, optional): The maximum number of chapters to return.
                                   Defaults to -1 (i.e., no limit).

        Returns:
            list[Dict[str, Any]]: A list of chapters in ascending order.
        """
        if limit == 0:
            raise ValueError("limit must be greater than 0")

        def get_endpoint(is_paid: bool, _page: int) -> str:
            if is_paid:
                return f"api/chapters/paid?query=&page={_page}&perPage=30&series_id={manga_id}"
            else:
                return f"chapter/query?page={_page}&perPage=30&series_id={manga_id}"

        async def fetch_chapters(is_paid: bool, _page: int, remaining: int) -> list:
            """
            Recursively fetch chapters for either premium or free endpoints while enforcing the limit.

            Args:
                is_paid (bool): True for premium chapters; False for free.
                _page (int): The current page number.
                remaining (int): How many chapters are still needed. A negative value means no limit.

            Returns:
                list: The chapters from _page and older pages, in ascending order.
            """
            endpoint = get_endpoint(is_paid, _page)
            result = await self.__request("GET", endpoint)
            metadata = result.get("meta", {})
            data = result.get("data", [])

            # For free chapters, filter out non‑free ones.
            if not is_paid:
                data = [chapter for chapter in data if chapter.get("price", 0) == 0]

            # The API returns chapters in descending order.
            # Reverse the list to get ascending order for this page.
            page_chapters = data[::-1]

            # If a limit is enforced and this page has more chapters than needed,
            # take only the newest chapters from this page.
            if 0 < remaining <= len(page_chapters):
                # In the reversed list, the last items are the newest.
                # Return only those items, as we don't need to fetch older pages.
                return page_chapters[-remaining:]

            # Otherwise, we plan to use all chapters from this page.
            # Determine the new remaining count.
            used = len(page_chapters) if remaining < 0 else len(page_chapters)
            new_remaining = remaining if remaining < 0 else remaining - used

            # Check if there are older pages to fetch.
            if metadata.get("current_page", 1) < metadata.get("last_page", 1) and (remaining < 0 or new_remaining > 0):
                # Recursively fetch older chapters.
                older_chapters = await fetch_chapters(is_paid, _page + 1, new_remaining)
            else:
                older_chapters = []

            # Prepend older chapters to the current page's chapters to maintain ascending order.
            return older_chapters + page_chapters

        # --- Fetch premium chapters first ---
        premium_limit = limit if limit > 0 else -1
        premium_chapters = await fetch_chapters(is_paid=True, _page=page, remaining=premium_limit)

        # If a limit was set, and we have reached it using premium chapters, return immediately.
        if 0 < limit <= len(premium_chapters):
            return premium_chapters[-limit:]

        # Otherwise, determine how many chapters are still needed.
        remaining_for_free = -1 if limit < 0 else limit - len(premium_chapters)

        # --- Fetch free chapters for any remaining needed ---
        free_chapters = await fetch_chapters(is_paid=False, _page=page, remaining=remaining_for_free)

        # Combine premium chapters (which are newer and come later in ascending order)
        # with free chapters (which are older and should come at the start).
        # Since our recursive fetch prepends older pages, free_chapters is in ascending order.
        # Premium chapters were built similarly so that their final order is ascending.
        return free_chapters + premium_chapters

    async def search(self, title: str, limit: Optional[int] = None) -> list[Any]:
        endpoint = "query"
        params = {"adult": "true", "query_string": title}
        kwargs = {}
        if isinstance(self.manager.session, CachedCurlCffiSession):
            kwargs["cache_time"] = 0
        response = await self.__request("GET", endpoint, params=params, **kwargs)
        data = response.get("data", [])
        if limit is not None:
            data = list(data)[:limit]
        return data

    async def get_cover(self, url_name: str) -> Optional[str]:
        result = await self.get_manga(url_name)
        url = result.get("thumbnail").removeprefix("/")
        if not url.startswith("https://"):
            url = "https://media.reaperscans.com/file/4SRBHm/" + url
        return url

    async def get_title(self, url_name: str) -> Optional[str]:
        result = await self.get_manga(url_name)
        return result.get("title")

    async def get_status(self, url_name: str) -> Optional[str]:
        manga = await self.get_manga(url_name)
        return manga["status"]
