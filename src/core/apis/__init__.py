from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .. import CachedClientSession
    from ..bot import MangaClient

from .comickAPI import ComickAppAPI
from .mangadexAPI import MangaDexAPI
from .omegascansAPI import OmegaScansAPI
from .zeroscansAPI import ZeroScansAPI


class APIManager:
    def __init__(self, bot: MangaClient, session: CachedClientSession):
        self.bot: MangaClient = bot
        self._session: CachedClientSession = session
        self.comick = ComickAppAPI(self)
        self.mangadex = MangaDexAPI(self)
        self.omegascans = OmegaScansAPI(self)
        self.zeroscans = ZeroScansAPI(self)

    @property
    def session(self) -> CachedClientSession:
        return self._session
