from __future__ import annotations

from typing import TYPE_CHECKING

import pyppeteer.errors
from pyppeteer_stealth import stealth

if TYPE_CHECKING:
    from src.core import MangaClient
from io import BytesIO
import asyncio

from pyppeteer.launcher import Launcher
from pyppeteer.browser import Browser
from pyppeteer.network_manager import Request
import logging
from typing import Dict, Any, Optional, Set
from src.core.scanners import AsuraScans
import tempfile


class ProtectedRequest:
    _default_cache_time: int = 5
    logger = logging.getLogger(__name__)

    def __init__(self, bot: MangaClient, headless: bool = True, ignored_urls: Optional[Set[str]] = None) -> None:

        self.bot: MangaClient = bot
        self._user_data_dir: str = "browser_data"
        self._headless: bool = headless
        self._ignored_urls = set(ignored_urls) if ignored_urls else set()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.browser: Browser | None = None

        self.cookie_exempt_scanlators = [
            AsuraScans.name
        ]

        options = {
            "headless": self._headless,
            "args": [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--headless',
                '--disable-gpu',
                '--ignore-certificate-errors'
            ],
            "userDataDir": self._user_data_dir,
            # "ignoreHTTPSErrors": True,
        }

        if bot.config.get("proxy", {}).get("enabled", False):
            options["args"].append(f"--proxy-server={bot.proxy_addr.split('@')[-1].split('//')[-1]}")

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

    async def new_tab(self, size: tuple[int, int] = (1280, 800)) -> pyppeteer.browser.Page:

        if not self.browser:
            await self.async_init()

        page = await self.browser.newPage()

        # authenticate the proxy if enabled:
        if self.bot.config.get("proxy", {}).get("enabled", False):
            proxy_dict = self.bot.config.get("proxy", {})
            if proxy_dict.get("username") and proxy_dict.get("password"):
                await page.authenticate(
                    {'username': proxy_dict.get("username"), 'password': proxy_dict.get("password")}
                )

        # Set custom User-Agent string
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ' \
                     'Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.43'
        await page.setUserAgent(user_agent)

        # Set viewport size
        await page.setViewport({'width': size[0], 'height': size[1]})

        # Set additional headers
        headers = {
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
        await page.setExtraHTTPHeaders(headers)

        await stealth(page)

        return page  # return the page object
        # await page.goto(url, wait_until="domcontentloaded")
        # return page

    async def open_page(self, url: str, size: tuple[int, int] = (1280, 800)) -> pyppeteer.browser.Page:
        page = await self.new_tab(size)
        await page.goto(url, wait_until="domcontentloaded")
        return page

    @staticmethod
    async def screenshot_element(page: pyppeteer.browser.Page, selector: str) -> BytesIO:
        """Screenshots an element on the page, returns the element as a BytesIO object"""
        element = await page.querySelector(selector)
        if not element:
            raise ValueError(f"Element {selector} not found on page {page.url}")

        temp_file = tempfile.mktemp(suffix=".png")
        await element.screenshot({'path': temp_file}, type="png")
        with open(temp_file, "rb") as f:
            buffer = BytesIO(f.read())
        buffer.seek(0)
        await page.close()
        return buffer

    async def bypass_cloudflare(self, url, cache_time: Optional[int] = None) -> str:
        if not self.browser:
            await self.async_init()

        # page = await self.browser.newPage()

        if url in self._cache and self._cache[url]["expires"] > asyncio.get_event_loop().time():
            self.logger.debug(f"Using cached response for {url}")
            return self._cache[url]["content"]

        try:
            page = await self.new_tab()
        except ConnectionError:
            self.logger.error("ConnectionError when trying to create new page")
            self.logger.warning("Retrying in 10 seconds...")
            await self.browser.close()
            await asyncio.sleep(10)
            self.browser = None
            return await self.bypass_cloudflare(url, cache_time)

        # scanlator = get_manga_scanlator_class(SCANLATORS, url)
        # if scanlator and scanlator.name not in self.cookie_exempt_scanlators:
        #     cookie = await self.bot.db.get_cookie(scanlator.name)
        #     if cookie:
        #         await page.setCookie(*cookie)
        #
        # elif scanlator and scanlator.name in self.cookie_exempt_scanlators:
        #     await page.deleteCookie(*await page.cookies())

        def on_request(req: Request):
            asyncio.ensure_future(self.check_request(req))

        # Block requests to the radio api
        await page.setRequestInterception(True)
        page.on("request", on_request)

        try:
            await page.goto(url)  # , wait_until="domcontentloaded"
        except TimeoutError:
            self.logger.error(f"TimeoutError when trying to bypass cloudflare for {url}")
            await self.bot.log_to_discord(f"TimeoutError when trying to bypass cloudflare for {url}")
            await page.close()
            return "Ray ID: 504 Gateway Timeout"

        # await asyncio.sleep(5)  # wait 5 sec in hopes that cloudflare will be done.
        content = await page.content()
        if "Just a moment..." in content:
            self.logger.debug("Caught in cloudflare 'Just a moment...' challenge. Attempting to wait it out!")
            # wait 10 sec in hopes that cloudflare will be done.
            await page.waitFor(10000)
            content = await page.content()
            if "Verify you are human" in content:
                self.logger.debug("Caught in cloudflare 'Verify you are human' challenge. Attempting to bypass!")
                await self.click_cloudflare_checkbox(page)
        else:
            self.logger.debug("No cloudflare challenge detected.")

        # page_cookie = await page.cookies()
        # if page_cookie and scanlator and scanlator.name not in self.cookie_exempt_scanlators:
        #     await self.bot.db.set_cookie(scanlator.name, page_cookie)

        if url not in self._ignored_urls:
            self._cache[url] = {
                "content": content,
                "expires": asyncio.get_event_loop().time() + (
                    self._default_cache_time if cache_time is None else cache_time
                )
            }
        self.logger.debug(f"Cached response for {url}")
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
        cls.logger.info(f"Set default cache time to {cache_time}")

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
