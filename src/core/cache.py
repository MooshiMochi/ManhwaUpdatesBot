import asyncio
import logging
from functools import partialmethod
from typing import Any, Coroutine, Dict, Optional, Set, Union

import aiohttp
import curl_cffi.requests
# noinspection PyProtectedMember
from aiohttp.client import _RequestContextManager

from src.core.objects import CachedResponse
from src.static import EMPTY


class BaseCacheSessionMixin:
    logger = None
    _default_cache_time: int = 5

    def __init__(
            self,
            ignored_urls: Optional[Set[str]] = None,
            *,
            name: str = None,
            proxy: str = None,
    ) -> None:
        self._ignored_urls = set(ignored_urls) if ignored_urls else set()
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
            self.logger.info("Using proxy: " + self._proxy)

        # Start a background task to periodically clear the cache
        self._clear_cache_task = asyncio.create_task(self._clear_cache_periodically())

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
    ) -> Union[Coroutine[Any, Any, aiohttp.ClientResponse], _RequestContextManager, Any]:

        if self._proxy and kwargs.get("proxy") is None:
            kwargs["proxy"] = self._proxy
            kwargs["verify_ssl"] = False

        if (used_proxy := kwargs.get("proxy")) is not None:
            if used_proxy is not EMPTY:
                # self.logger.debug(f"Making request through proxy: {self._proxy}")
                pass
            else:
                kwargs.pop("proxy")
                kwargs.pop("verify_ssl", None)

        # set default user agent if not set
        if kwargs.get("headers", None) is None:
            kwargs["headers"] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/114.0.0.0 Safari/537.36'
            }
        if url in self._ignored_urls or self._is_discord_api_url(url):
            # Don't cache ignored URLs
            return await super()._request(method, url, *args, **kwargs)

        if url in self._cache and self._cache[url]['expires'] > asyncio.get_event_loop().time():
            self.logger.debug(f"Cache hit for {url}")
            # Use cached response
            response = self._cache[url]['response']
            # response.cached = True
            return response

        # Cache miss, fetch and cache response
        self.logger.debug(f"Cache miss for {url}")
        response = await super()._request(method, url, *args, **kwargs)  # await the new response object
        response = await CachedResponse(response).apply_patch()

        cache_time = cache_time if cache_time is not None else self._default_cache_time
        # response.cached = False
        self._cache[url] = {
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
        BaseCacheSessionMixin.__init__(self, ignored_urls, name=name, proxy=proxy)
        super().__init__(*args, **kwargs)

    async def request(self, method, url, cache_time: Optional[int] = None, *args, **kwargs):
        self.logger.debug("Making request...")
        if url in self._ignored_urls or self._is_discord_api_url(url):
            # Don't cache ignored URLs
            return await super().request(method, url, *args, **kwargs)

        elif url in self._cache and self._cache[url]['expires'] > asyncio.get_event_loop().time():
            self.logger.debug(f"Cache hit for {url}")
            # Use cached response
            response = self._cache[url]['response']
            return response

        self.logger.debug(f"Cache miss for {url}")
        response = await super().request(method, url, *args, **kwargs)

        cache_time = cache_time if cache_time is not None else self._default_cache_time
        # response.cached = False
        self._cache[url] = {
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
