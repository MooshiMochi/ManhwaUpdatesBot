from __future__ import annotations

import asyncio
import datetime
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import APIManager

import random


class Proxy:
    def __init__(self,
                 id, username, password, proxy_address, port, valid,
                 country_code, city_name, created_at, **kwargs):
        self.id: str = id
        self.username: str = username
        self.password: str = password
        self.proxy_address: str = proxy_address
        self.port: int = port
        self.valid: bool = valid
        self.last_verification: datetime.datetime | None = kwargs.get("last_verification")
        self.country_code: str = country_code
        self.city_name: str = city_name
        self.created_at: datetime.datetime = created_at
        self.meta: dict = kwargs

    def to_url_dict(self) -> dict[str, str]:
        return {
            "http": f"http://{self.username}:{self.password}@{self.proxy_address}:{self.port}",  # noqa
            "https": f"http://{self.username}:{self.password}@{self.proxy_address}:{self.port}",  # noqa
        }

    def to_url(self, protocol: str = "http") -> str:
        return f"{protocol}://{self.username}:{self.password}@{self.proxy_address}:{self.port}"


class WebsShare:
    def __init__(self, manager: APIManager, api_key: str):
        self.manager: APIManager = manager
        self.key: str = api_key
        self.base_url: str = "https://proxy.webshare.io/api/v2"
        self.used_proxies: set[str] = set()  # format: ["proxy_address:port"]
        self.request_count = 0
        self.start_time = time.time()

        if not api_key:
            raise Exception("Webshare API key not found.")

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        await self._rate_limit()
        url = f"{self.base_url}/{endpoint}"
        headers = {"Authorization": f"Token {self.key}"}
        depth = kwargs.pop("depth", 0)
        if depth > 3:
            raise Exception("Max depth reached")
        async with self.manager.session.request(method, url, headers=headers, **kwargs) as resp:
            self.request_count += 1
            if resp.status == 429:
                # Rate limited. We are requied to wait 60 seconds before trying a new request.
                await asyncio.sleep(60)
                kwargs["depth"] = depth + 1
                return await self._request(method, endpoint, **kwargs)
            return await resp.json()

    async def get_proxy(self) -> Proxy:
        all_proxies = await self.get_proxy_list(per_page=50)
        random_proxy = [x for x in all_proxies if x.id not in self.used_proxies]
        self.used_proxies.add(random_proxy[0].id)
        return random.choice(random_proxy)

    async def get_proxy_list(self, per_page: int = 100, page: int = 1, get_all: bool = False) -> list[Proxy]:
        all_proxies: list[dict] = []
        data = await self._request(
            "GET", "proxy/list/",
            params={"per_page": per_page, "page": page, "mode": "direct"}
        )
        all_proxies.extend(data["results"])
        if get_all:
            while data["next"]:
                data = await self._request("GET", data["next"])
                all_proxies.extend(data["results"])
        all_proxies: list[Proxy] = [Proxy(**x) for x in all_proxies]
        return all_proxies

    async def _rate_limit(self):
        # 180 requests per minute means 1 request every 1/3 of a second
        if self.request_count >= 180:
            elapsed = time.time() - self.start_time
            if elapsed < 60:
                await asyncio.sleep(60 - elapsed)
            self.request_count = 0
            self.start_time = time.time()
