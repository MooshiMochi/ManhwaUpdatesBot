import asyncio
import aiohttp
from typing import Optional, Set, Dict, Any, Coroutine, Union
import logging
# noinspection PyProtectedMember
from aiohttp.client import _RequestContextManager
from aiohttp import hdrs
from aiohttp.typedefs import StrOrURL


class CachedClientSession(aiohttp.ClientSession):
    logger = logging.getLogger(__name__)
    _default_cache_time: int = 5

    def __init__(self, ignored_urls: Optional[Set[str]] = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._ignored_urls = set(ignored_urls) if ignored_urls else set()
        self._cache: Dict[str, Dict[str, Any]] = {}

        self.set_default_cache_time = lambda *_, **k: self.logger.error(
            "Error: The 'set_default_cache_time' method can only be called on the class, not an instance.\n"
            "Please use the 'set_instance_default_cache_time' method instead."
        )

        self.logger.info(
            f"CachedClientSession initialized with default cache time of {self._default_cache_time} seconds"
        )

        # Start a background task to periodically clear the cache
        self._clear_cache_task = asyncio.create_task(self._clear_cache_periodically())

    async def _clear_cache_periodically(self) -> None:
        while True:
            await asyncio.sleep(self._default_cache_time + 0.5)
            if self._cache:
                self.logger.info("Clearing cache...")
                for url in self._cache.copy():
                    if self._cache[url]['expires'] < asyncio.get_event_loop().time():
                        del self._cache[url]
                self.logger.info("Cache cleared")
            else:
                self.logger.info("Cache is empty, not clearing")

    @staticmethod
    def _is_discord_api_url(url: str) -> bool:
        return url.startswith("https://discord.com/api")

    # async def request(self, method, url, *, cache_time: Optional[int] = None, **kwargs):
    #     return await self._request(method, url, cache_time, **kwargs)

    async def _request(
            self, method: str, url: str, cache_time: Optional[int] = None, *args, **kwargs
    ) -> Union[Coroutine[Any, Any, aiohttp.ClientResponse], _RequestContextManager, Any]:

        if url in self._ignored_urls or self._is_discord_api_url(url):
            # Don't cache ignored URLs
            self.logger.info(f"Requesting {url} without caching")
            return await super()._request(method, url, **kwargs)

        if url in self._cache and self._cache[url]['expires'] > asyncio.get_event_loop().time():
            # Use cached response
            response = self._cache[url]['response']
            # response.cached = True
            self.logger.info(f"Using cached response for {url}")
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
        self.logger.info(f"Cached response for {url}")
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
        cls.logger.warning(f"Set default cache time to {cache_time}")

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
