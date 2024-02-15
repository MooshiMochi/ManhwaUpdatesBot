from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
from aiohttp import ClientConnectorError, ClientResponse, ContentTypeError

from src.core.objects import CachedResponse

if TYPE_CHECKING:
    from src.core.apis import APIManager


class FlareSolverrAPI:
    def __init__(self, api_manager: APIManager, base_url: str, api_key: str, proxy: dict[str, str]) -> None:
        """
        An API wrapper for the FlareSolverr proxy server.
        Note: It is recommended to run the health_check method after initializing the class to ensure the server is
        available.

        Args:
            api_manager: The API manager.
            base_url: The base url for the FlareSolverr server.
            api_key: The API key for the FlareSolverr server.
            proxy: The proxy to use for the FlareSolverr sessions.
        """
        self.manager: APIManager = api_manager
        self.base_url: str = base_url
        self.api_key: str = api_key
        self.proxy: dict[str, str] = proxy
        self.session_cache: set[str] = set()

        self.is_available: bool = self.base_url is not None

    async def async_init(self):
        self.manager.bot.logger.info("Testing FlareSolverr...")
        await self.health_check()
        if not self.is_available:
            self.manager.bot.logger.error("FlareSolverr check failed...")
            return
        await self.get_active_sessions()
        await self.destroy_all_sessions()
        await self.create_new_session()
        self.manager.bot.logger.info("FlareSolverr is working...")

    async def health_check(self) -> bool:
        """
        Check if the FlareSolverr server is available.

        Returns:
            bool: Whether the server is available.
        """
        try:
            async with self.manager.session.get(
                    f"{self.base_url}/health",  # noqa
                    headers={"Content-Type": "application/json", "Authorization": self.api_key},
                    json={"cmd": "health.check"},
                    cache_time=0
            ) as response:
                self.is_available = response.status == 200
                if not self.is_available:
                    self.manager.bot.logger.error(
                        f"[FlareSolverr] Health check: ({response.status} {response.reason}) "
                        f"{(await response.json()).get('message')}")
                return self.is_available
        except (ClientConnectorError, ContentTypeError):
            self.is_available = False
            self.manager.bot.logger.error("[FlareSolverr] Health check: Connection error. Double check the base_url "
                                          "and API Key in config.yml")
            return False

    async def get_active_sessions(self) -> list[str]:
        """
        Get a list of active sessions from the flaresolverr server.

        Returns:
            list[str]: A list of active session ids.
        """
        async with self.manager.session.post(
                f"{self.base_url}/v1",  # noqa
                headers={"Content-Type": "application/json", "Authorization": self.api_key},
                json={"cmd": "sessions.list"},
                cache_time=0
        ) as response:
            response.raise_for_status()
            active_sessions = await response.json()
            self.session_cache = self.session_cache.union(active_sessions.get("sessions"))  # update the session cache
            return active_sessions

    async def create_new_session(self, proxy: dict[str, str] | None = None) -> str:
        """
        Create a new session on the flaresolverr server.

        Args:
            proxy (str): The proxy to use for the session.

        Returns:
            str: The session id.
        """
        json_params = {"cmd": "sessions.create"}
        if proxy is not None or self.proxy is not None:
            json_params["proxy"] = proxy or self.proxy

        async with self.manager.session.post(
                f"{self.base_url}/v1",  # noqa
                headers={"Content-Type": "application/json", "Authorization": self.api_key},
                json=json_params,
                cache_time=0
        ) as response:
            response.raise_for_status()
            new_session = await response.json()
            session_id = new_session.get("session")
            self.session_cache.add(session_id)  # update the session cache
            self.manager.bot.logger.debug(f"[FlareSolverr] New session {session_id} created.")
            return session_id

    async def delete_session(self, session_id: str) -> None:
        """
        Delete a session on the flaresolverr server.

        Args:
            session_id (str): The session id to delete.
        """
        async with self.manager.session.post(
                f"{self.base_url}/v1",  # noqa
                headers={"Content-Type": "application/json", "Authorization": self.api_key},
                json={"cmd": "sessions.destroy", "session": session_id},
                cache_time=0
        ) as response:
            await response.json()
            self.session_cache = self.session_cache - {session_id}  # update the session cache
            self.manager.bot.logger.debug(f"[FlareSolverr] Session {session_id} deleted.")

    async def destroy_all_sessions(self) -> None:
        """
        Destroy all sessions on the flaresolverr server.
        """
        self.manager.bot.logger.debug("[FlareSolverr] Destroying all sessions.")
        for session_id in self.session_cache:
            await self.delete_session(session_id)

    async def get(
            self, url: str, session_id: str | None = None, headers: dict | None = None, *args, **kwargs
    ) -> ClientResponse | CachedResponse:
        """
        Get a response from the flaresolverr server.

        Args:
            headers: The headers to use for the request.
            url (str): The url to get a response from.
            session_id (str, optional): The session id to use. Defaults to None.

        Returns:
            str: The response from the server.
        """
        if not session_id:
            if not self.session_cache:
                session_id = await self.create_new_session()
            else:
                session_id = next(iter(self.session_cache))
        default_headers = {"Content-Type": "application/json", "Authorization": self.api_key}
        if headers:
            default_headers.update(headers)
        response = await self.manager.session.get_from_cache(url)
        if response:
            return response
        cache_time = kwargs.get("cache_time")
        async with self.manager.session.post(
                f"{self.base_url}/v1",  # noqa
                headers=default_headers,
                json={"cmd": "request.get", "url": url, "session": session_id},
                cache_time=0
        ) as response:
            response = await CachedResponse(response).apply_patch(preload_data=True)  # TODO: preload_data=False
            self.manager.session.save_to_cache(url, response, cache_time=cache_time)
            try:
                if 400 <= (status_code := (await response.json()).get("solution", {}).get("status", 200)) <= 499:
                    self.manager.bot.logger.error(f"[FlareSolverr] Error: {status_code}")
                    # swap out the proxy for a new one.
                    self.proxy = await self.manager.webshare.get_proxy().to_url_dict()
                else:
                    return response
            except aiohttp.ContentTypeError:
                # probably an internal proxy server error. We can destroy the session, and create a new one,
                # and raise error
                await self.delete_session(session_id)
                self.manager.bot.logger.error("[FlareSolverr] Internal server error.")
                await self.create_new_session()
            raise aiohttp.ClientResponseError(response.request_info, response.history) from response
