from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp.helpers

from ...enums import Minutes

if TYPE_CHECKING:
    from .. import CachedClientSession
    from ..bot import MangaClient

from .comickAPI import ComickAppAPI
from .mangadexAPI import MangaDexAPI
from .omegascansAPI import OmegaScansAPI
from .zeroscansAPI import ZeroScansAPI
from .flaresolverr import FlareSolverrAPI
from .webshare import WebsShare


class APIManager:
    def __init__(self, bot: MangaClient, session: CachedClientSession):
        self.bot: MangaClient = bot
        self._session: CachedClientSession = session
        self.comick = ComickAppAPI(self)
        self.mangadex = MangaDexAPI(self)
        self.omegascans = OmegaScansAPI(self)
        self.zeroscans = ZeroScansAPI(self)
        self.webshare = WebsShare(self, bot.config.get("api-keys", {}).get("webshare"))
        self.flare = FlareSolverrAPI(
            self,
            bot.config.get("flaresolverr", {}).get("base_url"),
            bot.config.get("api-keys", {}).get("flaresolverr"),
            bot.config.get("flaresolverr", {}).get("enabled", False),
            {
                "http": self.bot.proxy_addr,
                "https": self.bot.proxy_addr
            } if self.bot.proxy_addr else None
        )

    @property
    def session(self) -> CachedClientSession:
        return self._session

    async def reset_session(self, curl:bool=False):
        await self._session.close() if self._session is not None else None
        timeout = aiohttp.ClientTimeout(total=Minutes.FIVE.value)  # 5 min
        self._session = CachedClientSession(
            timeout=timeout, proxy=self.session._proxy, name=self._session._name, trust_env=True  # noqa: protected mem
        )
