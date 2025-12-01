import asyncio
import json
import logging
import os
import urllib
from dataclasses import dataclass, field
from functools import partialmethod
from typing import Any, Dict, Optional, Set, Tuple
from urllib import parse

import certifi
import curl_cffi.requests
from aiohttp import ClientResponseError, RequestInfo
from bs4 import BeautifulSoup
from camoufox.async_api import AsyncCamoufox
from curl_cffi import CurlOpt
from curl_cffi.requests import Response
from playwright._impl._errors import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from playwright_captcha import CaptchaType, ClickSolver, FrameworkType
from playwright_captcha.utils.camoufox_add_init_script.add_init_script import get_addon_path

ADDON_PATH = get_addon_path()


# noinspection PyProtectedMember


class BaseCacheSessionMixin:
    logger: logging.Logger = None
    _default_cache_time: int = 3600  # 1 hour
    _ignored_urls: Set[str] = set()

    def __init__(
            self,
            ignored_urls: Optional[Set[str]] = None,
            *,
            name: str = None,
            proxy: str = None,
    ) -> None:
        if ignored_urls:
            BaseCacheSessionMixin._ignored_urls = BaseCacheSessionMixin._ignored_urls.union(set(ignored_urls))

        self._cache: Dict[str, Dict[str, Any]] = {}
        self._proxy = proxy
        self._name = name or (__name__ + "." + self.__class__.__name__)

        self.logger = logging.getLogger(self._name)
        self.logger.info(f"Initializing {self._name}...")

        self.set_default_cache_time = lambda *_, **k: self.logger.error(
            "Error: The 'set_default_cache_time' method can only be called on the class, not an instance.\n"
            "Please use the 'set_instance_default_cache_time' method instead."
        )

        self.logger.info(
            f"{self._name} initialized with default cache time of {self._default_cache_time} seconds"
        )

        if self._proxy:
            proxy_str = self._proxy
            if "@" in proxy_str:
                proxy_str = proxy_str.split("//")[0] + "//" + "[PROXY USER]:[PROXY PASSWORD]@" + proxy_str.split("@")[1]
            self.logger.info("Using proxy: " + proxy_str)

        # Start a background task to periodically clear the cache
        self._clear_cache_task = asyncio.create_task(self._clear_cache_periodically())

    @staticmethod
    def fmt_cached_url(url, **kwargs) -> str:
        cached_url = url.removesuffix("/")
        url_params = kwargs.get("params")
        if url_params:
            cached_url = cached_url + "?" + "&".join([f"{k}={v}" for k, v in url_params.items()])
        return cached_url

    async def get_from_cache(self, url: str, **kwargs) -> Tuple[str, Optional[Response]]:
        cached_url = self.fmt_cached_url(url, **kwargs)
        if cached_url in self._ignored_urls or self._is_discord_api_url(url):  # Don't cache URLs that should be ignored
            return cached_url, None
        if cached_url in self._cache and self._cache[cached_url]['expires'] > asyncio.get_event_loop().time():
            self.logger.debug(f"Cache hit for {cached_url}")
            resp = self._cache[cached_url]['response']
            if resp.status_code == 403:
                self.logger.warning(f"403 Forbidden response found in cache for {cached_url}. Removing to try again!")
                del self._cache[cached_url]
                resp = None
            return cached_url, resp
        return cached_url, None

    def save_to_cache(self, url: str, response: Response, cache_time: Optional[int] = None) -> None:
        cached_url = self.fmt_cached_url(url)
        cache_time = cache_time if cache_time is not None else self._default_cache_time
        self._cache[cached_url] = {
            'response': response,
            'expires': asyncio.get_event_loop().time() + cache_time
        }

    async def _clear_cache_periodically(self) -> None:
        while True:
            await asyncio.sleep(self._default_cache_time + 0.5)
            if self._cache:
                self.logger.debug("Clearing cache...")
                for url in self._cache.copy():
                    if self._cache[url]['expires'] < asyncio.get_event_loop().time():
                        del self._cache[url]
                self.logger.debug("Cache cleared")
            else:
                self.logger.debug("Cache is empty, not clearing")

    @staticmethod
    def _is_discord_api_url(url: str) -> bool:
        return url.startswith("https://discord.com/api")

    @classmethod
    def ignored_urls(cls) -> Set[str]:
        return BaseCacheSessionMixin._ignored_urls

    @classmethod
    def ignore_url(cls, value: str) -> None:
        if cls.logger is not None:
            cls.logger.info(f"Setting ignored URLs to {value}")
        cls._ignored_urls = BaseCacheSessionMixin._ignored_urls.union({value})

    def clear_cache(self) -> None:
        self._cache = {}
        self.logger.warning("Cleared cache")

    @classmethod
    def set_default_cache_time(cls, cache_time: int) -> None:
        """
        Set the default cache time for all instances of CachedCurlCffiSession

        NOTE: This method is a class method, so it can be called from the class itself, not an instance of the class

        Args:
            cache_time: The default cache time in seconds

        Returns:
            None
        """
        cls._default_cache_time = cache_time
        logging.getLogger(__name__).info(f"Set default cache time to {cache_time}")

    def set_instance_default_cache_time(self, cache_time: int) -> None:
        """
        Set the default cache time for this instance of CachedCurlCffiSession

        Args:
            cache_time: The default cache time in seconds

        Returns:
            None
        """
        self._default_cache_time = cache_time
        self.logger.info(f"Set instance default cache time to {cache_time}")


class CachedCurlCffiSession(curl_cffi.requests.AsyncSession, BaseCacheSessionMixin):
    def __init__(
            self,
            ignored_urls: Optional[Set[str]] = None,
            *args,
            name: str = None,
            proxy: str = None,
            ca_bundle: Optional[str] = None,
            **kwargs
    ) -> None:
        #  The proxies are passed into the "proxies" parameter when this class is initialized
        BaseCacheSessionMixin.__init__(self, ignored_urls, name=name,
                                       proxy=proxy or kwargs.get("proxies", {}).get("http"))

        ca_path = ca_bundle or certifi.where()

        # Merge any user-provided curl options with our CA settings
        user_curl_opts = kwargs.pop("curl_options", None) or {}
        base_curl_opts = {CurlOpt.CAINFO: ca_path}

        # If caller passed proxies and HTTPS proxy is used, ensure proxy CA too
        proxies = kwargs.get("proxies") or {}
        https_proxy = proxies.get("https")
        if https_proxy:
            base_curl_opts[CurlOpt.PROXY_CAINFO] = ca_path

        merged_curl_opts = {**base_curl_opts, **user_curl_opts}
        kwargs["curl_options"] = merged_curl_opts

        # Keep verification ON unless caller explicitly set it
        kwargs.setdefault("verify", True)

        super().__init__(*args, **kwargs)

    async def request(self, method, url, cache_time: Optional[int] = None, *args, **kwargs) -> Response:
        self.logger.debug("Making request...")

        cached_url, response = await self.get_from_cache(url, **kwargs)
        if response is not None:
            return response

        # self.cookies.clear()  # clear all cookies

        self.logger.debug(f"Cache miss for {cached_url}")
        # await limiter.try_acquire(is_user_request=is_user_req)
        response = await super().request(method, url, *args, **kwargs)

        cache_time = cache_time if cache_time is not None else self._default_cache_time
        # response.cached = False
        self._cache[cached_url] = {
            'response': response,
            'expires': asyncio.get_event_loop().time() + cache_time
        }
        return response

    head = partialmethod(request, "HEAD")
    get = partialmethod(request, "GET")
    post = partialmethod(request, "POST")
    put = partialmethod(request, "PUT")
    patch = partialmethod(request, "PATCH")
    delete = partialmethod(request, "DELETE")


@dataclass
class CachedResponse:
    """
    A dataclass to hold response data, making it cacheable.
    This replaces the need to cache the live `aiohttp.ClientResponse`.
    """
    status: int
    text: str
    headers: Dict[str, str]
    url: str
    cached: bool = field(default=False, repr=False)
    request_info: RequestInfo = field(default=None, repr=False)

    def __post_init__(self):
        self.status_code = self.status

    def json(self, selector: str = None, **kwargs) -> Any:
        """Returns the response body as JSON."""
        if not selector:
            return json.loads(self.text, **kwargs)

        soup = BeautifulSoup(self.text, "html.parser")
        raw_json = soup.select_one(selector)
        if not raw_json:
            return None
        return json.loads(raw_json.text, **kwargs)

    def raise_for_status(self):
        """Raises an exception for 4xx/5xx responses."""
        if 400 <= self.status < 600:
            raise ClientResponseError(
                history=(),
                status=self.status,
                message=f"HTTP Status {self.status}",
                headers=self.headers,
                request_info=self.request_info,
            )

    @property
    def ok(self) -> bool:
        """Returns True if status code is less than 400."""
        return self.status < 400


class CachedCamoufoxSession(BaseCacheSessionMixin):
    def __init__(self, ignored_urls: Optional[Set[str]] = None, *, name: str = None, proxy: str = None, **kwargs):
        BaseCacheSessionMixin.__init__(self, ignored_urls, name=name or "camoufox",
                                       proxy=proxy or kwargs.get("proxies", {}).get("http"))

        if self._proxy:
            proxy_dict = {
                "server": "http://" + self._proxy.split("@")[1],
                "username": self._proxy.split("@")[0].split(":")[1].split("//")[1],
                "password": self._proxy.split("@")[0].split(":")[2]
            }
        else:
            proxy_dict = None

        self.camoufox = AsyncCamoufox(
            geoip=True,
            humanize=True,

            # Camoufox workaround for captcha solver from playwright
            i_know_what_im_doing=True,
            config={'forceScopeAccess': True},
            disable_coop=True,
            main_world_eval=True,
            addons=[os.path.abspath(ADDON_PATH)],

            enable_cache=True,
            proxy=proxy_dict,
            headless="virtual" if os.name == "posix" else False,
            window=(1280, 720)
        )

    async def start(self):
        """
        Starts the underlying Camoufox browser session.
        Must be called before making any requests.
        """
        self.logger.info("Starting camoufox...")
        if not self.camoufox.browser:
            await self.camoufox.__aenter__()  # This creates self.camoufox.browser/context
            self.logger.info("Camoufox started.")
            await self.camoufox.browser.new_page()
            self.logger.info("New camoufox page for keepalive created.")
        else:
            self.logger.debug("Camoufox already started.")

    async def close(self):
        """Shuts down the Camoufox browser session."""
        self.logger.debug("Closing camoufox...")
        if self.camoufox.browser is not None:
            await self.camoufox.__aexit__(None, None, None)
            self.logger.debug("Camoufox closed.")
        else:
            self.logger.debug("Camoufox already closed or was never started.")

    async def request(self, method: str, url: str,
                      cache_time: Optional[int] = None,
                      *args, **kwargs) -> Response | CachedResponse:
        """
        Performs an asynchronous HTTP request with caching
        by creating a new Playwright page for each request.
        """
        self.logger.debug(f"Requesting (Method: {method}, URL: {url})")

        # 1. Check cache
        # Note: We don't pass *args, **kwargs to get_from_cache anymore
        # as the cache key is just the URL.
        cached_url, response = await self.get_from_cache(url, **kwargs)
        if response is not None:
            response.cached = True  # Mark as cached
            return response

        self.logger.debug(f"Cache miss for {cached_url}")

        # 2. Perform the request using a new browser page
        page = None
        try:
            page = await self.camoufox.browser.new_page()

            # Extract kwargs compatible with Playwright's request methods
            headers: Dict[str, str] | None = kwargs.get("headers")
            params: Dict[str, str] | None = kwargs.get("params")
            data = kwargs.get("data")
            json_data = kwargs.get("json")

            # Playwright's 'data' kwarg handles dicts as json
            if json_data is not None:
                data = json_data

            # Set extra headers if provided
            if headers:
                await page.set_extra_http_headers(headers)

            # --- Handle different methods ---
            if method.upper() == "GET":
                # page.goto is the "browser" way, renders JS
                # We must manually add params to the URL
                if params:
                    url_parts = list(urllib.parse.urlparse(url))
                    query = dict(urllib.parse.parse_qsl(url_parts[4]))
                    query.update(params)
                    url_parts[4] = urllib.parse.urlencode(query)
                    url = urllib.parse.urlunparse(url_parts)

                framework = FrameworkType.CAMOUFOX

                async with ClickSolver(framework, page) as solver:
                    attempt_count = 0
                    while True:
                        if attempt_count == 3:
                            self.logger.error("Failed to bypass captcha 3 times. Cancelling...")
                            break
                        attempt_count += 1

                        try:

                            pw_response = await page.goto(str(url), wait_until="domcontentloaded", timeout=30000)
                            # try:
                            #     await page.locator(".ray-id").wait_for(timeout=5000)  # wait for page to fully load
                            #     self.logger.debug("Loaded cloudflare turnstile")
                            #     break
                            # except PlaywrightTimeoutError:
                            #     self.logger.debug("No cloudflare turnstile loaded. ")
                            #     pass

                            try:
                                # check if we are requesting with bad IP
                                unable_to_access = page.locator(
                                    'div.cf-alert + div span[data-translate="unable_to_access"]')
                                await unable_to_access.wait_for(timeout=5000)
                                if await unable_to_access.count() > 0:
                                    self.logger.warning("Requested with bad IP. Retrying...")
                                    continue
                            except PlaywrightTimeoutError:
                                pass
                            break
                        except PlaywrightError as e:  # due to slow internet, the webpage may not have fully loaded yet
                            continue

                    try:
                        expected_content_selector = "html > body:not(:has(.ray-id))"
                        if kwargs.get("success_selector") is not None:
                            expected_content_selector = kwargs["success_selector"]
                        await solver.solve_captcha(
                            captcha_container=page,
                            captcha_type=CaptchaType.CLOUDFLARE_TURNSTILE,
                            expected_content_selector=expected_content_selector
                        )
                        status_code = 200
                    except Exception as e:
                        status_code = 403
                        self.logger.error(f"Failed to bypass captcha: {e}")

                    try:
                        is_loaded_locator = page.locator('html:first-child > body:not(:has(.ray-id))')
                        await is_loaded_locator.wait_for(timeout=10000)

                        if await is_loaded_locator.count() > 0:
                            status_code = 200
                        else:
                            status_code = 403
                    except PlaywrightTimeoutError:
                        status_code = 403

                # await asyncio.sleep(5)
                try:
                    await page.wait_for_load_state(timeout=10000)
                except PlaywrightTimeoutError:
                    self.logger.debug("Page did not load in time. This is ok because the goal was to add a delay.")

            elif method.upper() == "POST":
                # page.request.post does NOT render JS, but uses browser context
                pw_response = await page.request.post(url, params=params, data=data)

            elif method.upper() == "PUT":
                pw_response = await page.request.put(url, params=params, data=data)

            elif method.upper() == "DELETE":
                pw_response = await page.request.delete(url, params=params)

            else:
                # Fallback for HEAD, OPTIONS, PATCH etc.
                pw_response = await page.request.fetch(url, method=method, params=params, data=data)

            if pw_response is None:
                raise ValueError(f"HTTP method {method} not implemented or failed.")

            # 3. Read response data to make it cacheable
            text = await page.content()
            status = status_code
            headers_raw = {"content-type": "text/html; charset=utf-8"}
            final_url = page.url

            self.logger.debug(f"Request successful (Status: {status}, URL: {final_url})")

            # 4. Create our cacheable response object
            response_to_cache = CachedResponse(
                status=status,
                text=text,
                headers=headers_raw,
                url=final_url,
                cached=False,
                request_info=RequestInfo(final_url, method, headers_raw, url)
            )

            # 5. Save to cache
            if status < 400:  # Only cache successful responses
                current_cache_time = cache_time if cache_time is not None else self._default_cache_time

                if current_cache_time > 0:
                    # Use cached_url as the key
                    self._cache[cached_url] = {
                        'response': response_to_cache,
                        'expires': asyncio.get_event_loop().time() + current_cache_time
                    }
                    self.logger.debug(f"Cached response for {cached_url} for {current_cache_time}s")

            return response_to_cache

        except Exception as e:
            self.logger.error(f"Playwright request failed for {url}: {e}")
            # Depending on policy, you might want to cache errors.
            # For simplicity, we just re-raise here.
            raise
        finally:
            if page:
                await page.close()  # CRITICAL: close the page to avoid memory leaks

    # --- Helper Methods ---

    async def get(self, url: str, cache_time: Optional[int] = None, **kwargs) -> Response | CachedResponse:
        """Performs a GET request."""
        return await self.request("GET", url, cache_time, **kwargs)

    async def post(self, url: str, cache_time: Optional[int] = None, **kwargs) -> Response | CachedResponse:
        """Performs a POST request."""
        # POST requests are typically not cached, but we allow it
        if cache_time is None:
            cache_time = 0  # Default to no cache for POST
        return await self.request("POST", url, cache_time, **kwargs)

    async def put(self, url: str, cache_time: Optional[int] = None, **kwargs) -> Response | CachedResponse:
        """Performs a PUT request."""
        if cache_time is None:
            cache_time = 0
        return await self.request("PUT", url, cache_time, **kwargs)

    async def delete(self, url: str, cache_time: Optional[int] = None, **kwargs) -> Response | CachedResponse:
        """Performs a DELETE request."""
        if cache_time is None:
            cache_time = 0
        return await self.request("DELETE", url, cache_time, **kwargs)
