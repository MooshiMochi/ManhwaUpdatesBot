import asyncio
import logging
from typing import Optional, Set, Dict, Any, Coroutine, Union

import aiohttp
from aiohttp import hdrs
# noinspection PyProtectedMember
from aiohttp.client import _RequestContextManager
from aiohttp.typedefs import StrOrURL

from src.static import EMPTY


class CachedClientSession(aiohttp.ClientSession):
    logger = logging.getLogger(__name__)
    _default_cache_time: int = 5

    def __init__(
            self,
            ignored_urls: Optional[Set[str]] = None,
            *args,
            name: str = None,
            proxy: str = None,
            **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        self._ignored_urls = set(ignored_urls) if ignored_urls else set()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._proxy = proxy
        self._name = name or __name__

        self.logger.name = self._name

        self.set_default_cache_time = lambda *_, **k: self.logger.error(
            "Error: The 'set_default_cache_time' method can only be called on the class, not an instance.\n"
            "Please use the 'set_instance_default_cache_time' method instead."
        )

        self.logger.info(
            f"CachedClientSession initialized with default cache time of {self._default_cache_time} seconds"
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

    async def _request(
            self, method: str, url: str, cache_time: Optional[int] = None, *args, **kwargs
    ) -> Union[Coroutine[Any, Any, aiohttp.ClientResponse], _RequestContextManager, Any]:

        if self._proxy and kwargs.get("proxy") is None:
            kwargs["proxy"] = self._proxy
            kwargs["verify_ssl"] = False

        if (used_proxy := kwargs.get("proxy")) is not None:
            if used_proxy is not EMPTY:
                self.logger.debug(f"Making request through proxy: {self._proxy}")
            else:
                kwargs.pop("proxy")
                kwargs.pop("verify_ssl", None)

        if url in self._ignored_urls or self._is_discord_api_url(url):
            # Don't cache ignored URLs
            self.logger.debug(f"Requesting {url} without caching")
            if kwargs.get("headers", None) is None:
                kwargs["headers"] = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                                  'Chrome/58.0.3029.110 Safari/537.3'
                }
            return await super()._request(method, url, **kwargs)

        if url in self._cache and self._cache[url]['expires'] > asyncio.get_event_loop().time():
            # Use cached response
            response = self._cache[url]['response']
            # response.cached = True
            self.logger.debug(f"Using cached response for {url}")
            return response

        # Cache miss, fetch and cache response
        response = await super()._request(method, url, **kwargs)  # await the new response object
        # response.cached = False
        self._cache[url] = {
            'response': response,
            'expires': asyncio.get_event_loop().time() + (
                cache_time if cache_time is not None else self._default_cache_time
            )
        }
        self.logger.debug(f"Cached response for {url}")
        return response

    def get(
            self, url: str, *, allow_redirects: bool = True, **kwargs: Any
    ) -> "_RequestContextManager":
        """Perform HTTP GET request."""
        return _RequestContextManager(self._request(hdrs.METH_GET, url, **kwargs))

    def options(
            self, url: StrOrURL, *, allow_redirects: bool = True, **kwargs: Any
    ) -> "_RequestContextManager":
        """Perform HTTP OPTIONS request."""
        return _RequestContextManager(
            self._request(
                hdrs.METH_OPTIONS, url, allow_redirects=allow_redirects, **kwargs
            )
        )

    def head(
            self, url: StrOrURL, *, allow_redirects: bool = False, **kwargs: Any
    ) -> "_RequestContextManager":
        """Perform HTTP HEAD request."""
        return _RequestContextManager(
            self._request(
                hdrs.METH_HEAD, url, allow_redirects=allow_redirects, **kwargs
            )
        )

    def post(
            self, url: StrOrURL, *, data: Any = None, **kwargs: Any
    ) -> "_RequestContextManager":
        """Perform HTTP POST request."""
        return _RequestContextManager(
            self._request(hdrs.METH_POST, url, data=data, **kwargs)
        )

    def put(
            self, url: StrOrURL, *, data: Any = None, **kwargs: Any
    ) -> "_RequestContextManager":
        """Perform HTTP PUT request."""
        return _RequestContextManager(
            self._request(hdrs.METH_PUT, url, data=data, **kwargs)
        )

    def patch(
            self, url: StrOrURL, *, data: Any = None, **kwargs: Any
    ) -> "_RequestContextManager":
        """Perform HTTP PATCH request."""
        return _RequestContextManager(
            self._request(hdrs.METH_PATCH, url, data=data, **kwargs)
        )

    def delete(self, url: StrOrURL, **kwargs: Any) -> "_RequestContextManager":
        """Perform HTTP DELETE request."""
        return _RequestContextManager(self._request(hdrs.METH_DELETE, url, **kwargs))

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
        cls.logger.info(f"Set default cache time to {cache_time}")

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
