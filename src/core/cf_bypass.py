from __future__ import annotations

from typing import TYPE_CHECKING

import pyppeteer.errors

if TYPE_CHECKING:
    from src.core import MangaClient

import asyncio
from pyppeteer.launcher import Launcher
from pyppeteer.browser import Browser
from pyppeteer.network_manager import Request
import logging
from typing import Dict, Any, Optional, Set
from src.utils import get_manga_scanlator_class
from src.core.scanners import SCANLATORS


class ProtectedRequest:
    _default_cache_time: int = 5
    logger = logging.getLogger(__name__)

    def __init__(self, bot: MangaClient, headless: bool = True, ignored_urls: Optional[Set[str]] = None, *args,
                 **kwargs) -> None:

        self.bot: MangaClient = bot
        self._user_data_dir: str = "browser_data"
        self._headless: bool = headless
        self._ignored_urls = set(ignored_urls) if ignored_urls else set()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.browser: Browser | None = None

        options = {
            "headless": self._headless,
            "args": [
                '--no-sandbox',

            ],
            "userDataDir": self._user_data_dir,
            # "ignoreHTTPSErrors": True,
        }
        self._launcher: Launcher | None = Launcher(**options)

        self._clear_cache_task = asyncio.create_task(self._clear_cache())

        self.logger.info(
            f"ProtectedRequest initialized with default cache time of {self._default_cache_time} seconds"
        )

    async def _clear_cache(self) -> None:
        while True:
            await asyncio.sleep(self._default_cache_time + 0.5)
            if self._cache:
                self.logger.debug("Clearing browser cache...")
                for url in self._cache.copy():
                    if self._cache[url]['expires'] < asyncio.get_event_loop().time():
                        del self._cache[url]
                self.logger.debug("Browser cache cleared")
            else:
                self.logger.debug("Browser cache is empty, not clearing")

    async def async_init(self):
        self.browser = await self._launcher.launch()

    async def __aenter__(self):
        await self.async_init()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        if self._launcher:
            try:
                await self._launcher.killChrome()
            except AttributeError:
                pass
            self._launcher.chromeClosed = True

    @staticmethod
    async def check_request(req: Request):
        blacklist = [
            "https://players.radioonlinehd.com/ads/aquamangaradio",
            "events.newsroom.bi",
            "radioonlinehd",
            "stream.zeno.fm",
            "hosted.muses.org",
            "disquscdn.com"
        ]
        if any(x in req.url for x in blacklist):
            await req.abort()
        else:
            await req.continue_()

    async def bypass_cloudflare(self, url, cache_time: Optional[int] = None) -> str:
        if not self.browser:
            await self.async_init()

        if url in self._cache and self._cache[url]["expires"] > asyncio.get_event_loop().time():
            self.logger.debug(f"Using cached response for {url}")
            return self._cache[url]["content"]

        page = await self.browser.newPage()

        scanlator = get_manga_scanlator_class(SCANLATORS, url)
        cookie = await self.bot.db.get_cookie(scanlator.name)
        if cookie:
            await page.setCookie(*cookie)

        # Set custom User-Agent string
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ' \
                     'Chrome/93.0.4577.63 Safari/537.36'
        await page.setUserAgent(user_agent)

        # Set viewport size
        await page.setViewport({'width': 1280, 'height': 800})

        # Set additional headers
        headers = {
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
        await page.setExtraHTTPHeaders(headers)

        def on_request(req: Request):
            asyncio.ensure_future(self.check_request(req))

        # Block requests to the radio api
        await page.setRequestInterception(True)
        page.on("request", on_request)

        for i in range(3):
            try:
                await page.goto(url, wait_until="domcontentloaded")
                break
            except pyppeteer.errors.PageError as e:
                if i == 2:
                    return f"Ray ID\n{str(e)}"

        # await asyncio.sleep(5)  # wait 5 sec in hopes that cloudflare will be done.
        content = await page.content()
        if "Just a moment..." in content:
            # wait 10 sec in hopes that cloudflare will be done.
            await page.waitFor(10000)
            content = await page.content()
            if "Verify you are human" in content:
                await self.click_cloudflare_checkbox(page)

        page_cookie = await page.cookies()
        if page_cookie:
            await self.bot.db.set_cookie(scanlator.name, page_cookie)

        if url not in self._ignored_urls:
            self._cache[url] = {
                "content": content,
                "expires": asyncio.get_event_loop().time() + (
                    self._default_cache_time if cache_time is None else cache_time
                )
            }
        self.logger.debug(f"Cached response for {url}")
        await asyncio.sleep(5)
        await page.close()
        return content

    async def click_cloudflare_checkbox(self, page):
        checkbox = await page.querySelector('input[type="checkbox"]')
        if checkbox:
            await checkbox.click()
            self.logger.debug("Clicked 'Verify you are human' checkbox.")
        else:
            self.logger.debug("Could not find 'Verify you are human' checkbox.")

    @property
    def ignored_urls(self) -> Set[str]:
        return self._ignored_urls

    @ignored_urls.setter
    def ignored_urls(self, value: Set[str]) -> None:
        self.logger.info(f"Setting ignored URLs to {value}")
        self._ignored_urls = set(value)

    def clear_cache(self) -> None:
        self._cache = {}
        self.logger.warning("Cleared cache")

    @classmethod
    def set_default_cache_time(cls, cache_time: int) -> None:
        """
        Set the default cache time for all instances of ProtectedRequest

        NOTE: This method is a class method, so it can be called from the class itself, not an instance of the class

        Args:
            cache_time: The default cache time in seconds

        Returns:
            None
        """
        cls._default_cache_time = cache_time
        cls.logger.warning(f"Set default cache time to {cache_time}")

    def set_instance_default_cache_time(self, cache_time: int) -> None:
        """
        Set the default cache time for this instance of ProtectedRequest

        Args:
            cache_time: The default cache time in seconds

        Returns:
            None
        """
        self._default_cache_time = cache_time
        self.logger.info(f"Set instance default cache time to {cache_time}")
