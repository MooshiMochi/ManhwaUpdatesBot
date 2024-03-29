import asyncio
import logging
from functools import partialmethod
from typing import Any, Dict, Optional, Set, Union

import aiohttp
import curl_cffi.requests
from curl_cffi.requests import Response

from src.core.objects import CachedResponse
from src.static import EMPTY


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

    async def get_from_cache(self, url: str) -> Optional[CachedResponse]:
        cached_url = self.fmt_cached_url(url)
        if cached_url in self._cache and self._cache[cached_url]['expires'] > asyncio.get_event_loop().time():
            self.logger.debug(f"Cache hit for {cached_url}")
            return self._cache[cached_url]['response']
        return None

    def save_to_cache(self, url: str, response: CachedResponse, cache_time: Optional[int] = None) -> None:
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
        Set the default cache time for all instances of CachedClientSession

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
        Set the default cache time for this instance of CachedClientSession

        Args:
            cache_time: The default cache time in seconds

        Returns:
            None
        """
        self._default_cache_time = cache_time
        self.logger.info(f"Set instance default cache time to {cache_time}")


class CachedClientSession(aiohttp.ClientSession, BaseCacheSessionMixin):
    def __init__(
            self,
            ignored_urls: Optional[Set[str]] = None,
            *args,
            name: str = None,
            proxy: str = None,
            **kwargs
    ) -> None:
        BaseCacheSessionMixin.__init__(self, ignored_urls, name=name, proxy=proxy)
        super().__init__(*args, **kwargs)

    async def _request(
            self, method: str, url: str, cache_time: Optional[int] = None, *args, **kwargs
    ) -> Union[CachedResponse, Any]:
        self.logger.debug("Making request...")

        if self._proxy and kwargs.get("proxy") is None:
            kwargs["proxy"] = self._proxy
            kwargs["verify_ssl"] = False

        if (used_proxy := kwargs.get("proxy")) is not None:
            if used_proxy is EMPTY:
                kwargs.pop("proxy")
                kwargs.pop("verify_ssl", None)

        default_header_opts = {'Accept-Encoding': 'gzip, deflate', 'Accept': '*/*', 'Connection': 'keep-alive'}

        if kwargs.get("headers", None) is None:
            kwargs["headers"] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/114.0.0.0 Safari/537.36'
                # "User-Agent": "python-requests/2.31.0"
            }
            kwargs["headers"] |= default_header_opts

        else:
            for hdr in default_header_opts:
                if hdr not in kwargs["headers"]:
                    kwargs["headers"][hdr] = default_header_opts[hdr]
        cached_url = self.fmt_cached_url(url, **kwargs)

        if cached_url in self._ignored_urls or self._is_discord_api_url(url):
            # await limiter.try_acquire(is_user_request=is_user_req)
            return await super()._request(method, url, *args, **kwargs)

        elif cached_url in self._cache and self._cache[cached_url]['expires'] > asyncio.get_event_loop().time():
            self.logger.debug(f"Cache hit for {cached_url}")
            # Use cached response
            response = self._cache[cached_url]['response']
            # response.cached = True
            return response

        self.cookie_jar.clear()  # clear all cookies before making request
        # Cache miss, fetch and cache response
        self.logger.debug(f"Cache miss for {cached_url}")
        # await limiter.try_acquire(is_user_request=is_user_req)
        response = await super()._request(method, url, *args, **kwargs)
        response = await CachedResponse(response).apply_patch(preload_data=True)  # TODO: preload_data=False

        cache_time = cache_time if cache_time is not None else self._default_cache_time
        # response.cached = False
        self._cache[cached_url] = {
            'response': response,
            'expires': asyncio.get_event_loop().time() + cache_time
        }
        return response


class CachedCurlCffiSession(curl_cffi.requests.AsyncSession, BaseCacheSessionMixin):
    def __init__(
            self,
            ignored_urls: Optional[Set[str]] = None,
            *args,
            name: str = None,
            proxy: str = None,
            **kwargs
    ) -> None:
        #  The proxies are passed into the "proxies" parameter when this class is initialized
        BaseCacheSessionMixin.__init__(self, ignored_urls, name=name, proxy=proxy)
        super().__init__(*args, **kwargs)

    async def request(self, method, url, cache_time: Optional[int] = None, *args, **kwargs) -> Response:
        self.logger.debug("Making request...")

        cached_url = self.fmt_cached_url(url, **kwargs)

        if cached_url in self._ignored_urls or self._is_discord_api_url(url):
            # Don't cache ignored URLs
            # await limiter.try_acquire(is_user_request=is_user_req)  # TODO: Re-enable rate limiter
            return await super().request(method, url, *args, **kwargs)

        elif cached_url in self._cache and self._cache[cached_url]['expires'] > asyncio.get_event_loop().time():
            self.logger.debug(f"Cache hit for {cached_url}")
            # Use cached response
            response = self._cache[cached_url]['response']
            return response

        self.cookies.clear()  # clear all cookies

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
