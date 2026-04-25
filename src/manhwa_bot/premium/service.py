"""PremiumService — orchestrates DB grants, Patreon, and Discord entitlements."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..config import PremiumConfig
from .discord_entitlements import DiscordEntitlementsService
from .grants import GrantsService
from .patreon import PatreonClient

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PremiumDecision:
    ok: bool
    reason: str | None


class PremiumService:
    """Three-source premium gate with explicit decision order."""

    def __init__(
        self,
        bot: Any,
        config: PremiumConfig,
        grants: GrantsService,
        patreon: PatreonClient,
        discord_ents: DiscordEntitlementsService,
    ) -> None:
        self._bot = bot
        self._config = config
        self._grants = grants
        self._patreon = patreon
        self._discord_ents = discord_ents

    @property
    def grants(self) -> GrantsService:
        return self._grants

    @property
    def patreon(self) -> PatreonClient:
        return self._patreon

    @property
    def discord_ents(self) -> DiscordEntitlementsService:
        return self._discord_ents

    async def is_premium(
        self,
        *,
        user_id: int,
        guild_id: int | None,
        interaction: Any | None = None,
        dm_only: bool = False,
    ) -> tuple[bool, str | None]:
        decision = await self._evaluate(
            user_id=user_id, guild_id=guild_id, interaction=interaction, dm_only=dm_only
        )
        if self._config.log_decisions:
            _log.debug(
                "premium decision user=%s guild=%s dm_only=%s -> ok=%s reason=%s",
                user_id,
                guild_id,
                dm_only,
                decision[0],
                decision[1],
            )
        return decision

    async def _evaluate(
        self,
        *,
        user_id: int,
        guild_id: int | None,
        interaction: Any | None,
        dm_only: bool,
    ) -> tuple[bool, str | None]:
        if not self._config.enabled:
            return (True, "disabled")

        owner_ids = getattr(self._bot, "owner_ids", None) or set()
        if self._config.owner_bypass and user_id in owner_ids:
            return (True, "owner")

        if await self._grants.is_active("user", user_id):
            return (True, "grant_user")

        if not dm_only and guild_id is not None:
            if await self._grants.is_active("guild", guild_id):
                return (True, "grant_guild")

        if self._config.patreon.enabled and await self._patreon.is_premium(user_id):
            return (True, "patreon")

        if self._config.discord.enabled:
            if interaction is not None:
                ok, reason = self._discord_ents.from_interaction(interaction, dm_only=dm_only)
                if ok:
                    return (True, reason)
            if self._discord_ents.is_user_premium(user_id):
                return (True, "discord_user")
            if (
                not dm_only
                and guild_id is not None
                and self._discord_ents.is_guild_premium(guild_id)
            ):
                return (True, "discord_guild")

        return (False, None)
