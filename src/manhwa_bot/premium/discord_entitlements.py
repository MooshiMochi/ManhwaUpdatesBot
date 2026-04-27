"""DiscordEntitlementsService — in-memory cache of Discord App Subscriptions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from ..config import DiscordPremiumConfig

_log = logging.getLogger(__name__)


class _EntitlementLike(Protocol):
    id: int
    sku_id: int
    user_id: int | None
    guild_id: int | None
    ends_at: datetime | None
    deleted: bool


def _is_active(ent: _EntitlementLike) -> bool:
    if getattr(ent, "deleted", False):
        return False
    ends_at = getattr(ent, "ends_at", None)
    if ends_at is None:
        return True
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=UTC)
    return ends_at > datetime.now(tz=UTC)


class DiscordEntitlementsService:
    """Caches active entitlements; updated by gateway events plus on-ready warm."""

    def __init__(self, config: DiscordPremiumConfig) -> None:
        self._config = config
        self._cache: dict[int, _EntitlementLike] = {}

    @property
    def enabled(self) -> bool:
        return bool(
            self._config.enabled
            and (self._config.user_sku_ids or self._config.guild_sku_ids)
        )

    def cache_size(self) -> int:
        return len(self._cache)

    async def warm(self, bot: Any) -> None:
        if not self._config.enabled:
            return

        try:
            skus = [s for s in await bot.fetch_skus()]
            known_ids = {sku.id for sku in skus}
            configured = set(self._config.user_sku_ids) | set(
                self._config.guild_sku_ids
            )
            unknown = configured - known_ids
            if unknown:
                _log.warning(
                    "Configured premium SKUs not present on the app: %s", unknown
                )
        except Exception:
            _log.exception("Failed to fetch SKUs from Discord")

        try:
            entitlements = [e async for e in bot.entitlements(exclude_ended=True)]
        except Exception:
            _log.exception("Failed to fetch entitlements from Discord")
            return

        self._cache = {ent.id: ent for ent in entitlements if _is_active(ent)}
        _log.info("Warmed Discord entitlement cache: %d active", len(self._cache))

    async def on_entitlement_create(self, entitlement: _EntitlementLike) -> None:
        self._cache[entitlement.id] = entitlement

    async def on_entitlement_update(self, entitlement: _EntitlementLike) -> None:
        if _is_active(entitlement):
            self._cache[entitlement.id] = entitlement
        else:
            self._cache.pop(entitlement.id, None)

    async def on_entitlement_delete(self, entitlement: _EntitlementLike) -> None:
        self._cache.pop(entitlement.id, None)

    def is_user_premium(self, user_id: int) -> bool:
        if not self._config.user_sku_ids:
            return False
        sku_set = set(self._config.user_sku_ids)
        for ent in self._cache.values():
            if not _is_active(ent):
                continue
            if ent.sku_id in sku_set and getattr(ent, "user_id", None) == user_id:
                return True
        return False

    def is_guild_premium(self, guild_id: int) -> bool:
        if not self._config.guild_sku_ids:
            return False
        sku_set = set(self._config.guild_sku_ids)
        for ent in self._cache.values():
            if not _is_active(ent):
                continue
            if ent.sku_id in sku_set and getattr(ent, "guild_id", None) == guild_id:
                return True
        return False

    def from_interaction(
        self,
        interaction: Any,
        *,
        dm_only: bool,
    ) -> tuple[bool, str | None]:
        if not self._config.enabled:
            return (False, None)
        ents = getattr(interaction, "entitlements", None) or []
        user_skus = set(self._config.user_sku_ids)
        guild_skus = set(self._config.guild_sku_ids)
        user_id = getattr(getattr(interaction, "user", None), "id", None)
        guild_id = getattr(getattr(interaction, "guild", None), "id", None)
        for ent in ents:
            if not _is_active(ent):
                continue
            if (
                user_skus
                and ent.sku_id in user_skus
                and getattr(ent, "user_id", None) == user_id
            ):
                return (True, "discord_user")
            if (
                not dm_only
                and guild_skus
                and ent.sku_id in guild_skus
                and getattr(ent, "guild_id", None) == guild_id
            ):
                return (True, "discord_guild")
        return (False, None)
