from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp.helpers

from ...enums import Minutes

if TYPE_CHECKING:
    from .. import CachedCurlCffiSession
    from ..bot import MangaClient

from .comickAPI import ComickAppAPI
from .mangadexAPI import MangaDexAPI
from .omegascansAPI import OmegaScansAPI
from .reaperAPI import ReaperScansAPI
from .zeroscansAPI import ZeroScansAPI
from .webshare import WebsShare


class APIManager:
    def __init__(self, bot: MangaClient, session: CachedCurlCffiSession):
        self.bot: MangaClient = bot
        self._session: CachedCurlCffiSession = session
        self.comick = ComickAppAPI(self)
        self.mangadex = MangaDexAPI(self)
        self.omegascans = OmegaScansAPI(self)
        self.zeroscans = ZeroScansAPI(self)
        self.reaperscans = ReaperScansAPI(self)
        # self.webshare = WebsShare(self, bot.config.get("api-keys", {}).get("webshare"))

    @property
    def session(self) -> CachedCurlCffiSession:
        return self._session

    async def reset_session(self):
        await self._session.close() if self._session is not None else None
        timeout = aiohttp.ClientTimeout(total=Minutes.FIVE.value)  # 5 min
        self._session = CachedCurlCffiSession(
            impersonate="random",
            name="cache.curl_cffi",
            proxies={"http": self.bot.proxy_addr, "https": self.bot.proxy_addr},
            timeout=timeout,
        )
