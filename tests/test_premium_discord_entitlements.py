"""Tests for DiscordEntitlementsService cache + interaction-direct lookup."""

from __future__ import annotations

import asyncio
import itertools
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from manhwa_bot.config import DiscordPremiumConfig
from manhwa_bot.premium.discord_entitlements import DiscordEntitlementsService

_id_iter = itertools.count(1)


def _ent(
    *,
    sku_id: int,
    user_id: int | None = None,
    guild_id: int | None = None,
    ends_at: datetime | None = None,
    deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=next(_id_iter),
        sku_id=sku_id,
        user_id=user_id,
        guild_id=guild_id,
        ends_at=ends_at,
        deleted=deleted,
    )


def _config(
    *, user_skus: tuple[int, ...] = (), guild_skus: tuple[int, ...] = ()
) -> DiscordPremiumConfig:
    return DiscordPremiumConfig(
        enabled=True,
        user_sku_ids=user_skus,
        guild_sku_ids=guild_skus,
        upgrade_url="",
    )


def test_user_scope_cache_hit() -> None:
    async def _run() -> None:
        svc = DiscordEntitlementsService(_config(user_skus=(100,)))
        await svc.on_entitlement_create(_ent(sku_id=100, user_id=42))
        assert svc.is_user_premium(42) is True
        assert svc.is_user_premium(43) is False

    asyncio.run(_run())


def test_guild_scope_cache_hit() -> None:
    async def _run() -> None:
        svc = DiscordEntitlementsService(_config(guild_skus=(200,)))
        await svc.on_entitlement_create(_ent(sku_id=200, guild_id=999))
        assert svc.is_guild_premium(999) is True
        assert svc.is_guild_premium(998) is False

    asyncio.run(_run())


def test_expired_entitlement_filtered() -> None:
    async def _run() -> None:
        svc = DiscordEntitlementsService(_config(user_skus=(100,)))
        past = datetime.now(tz=UTC) - timedelta(hours=1)
        await svc.on_entitlement_create(_ent(sku_id=100, user_id=42, ends_at=past))
        assert svc.is_user_premium(42) is False

    asyncio.run(_run())


def test_unconfigured_sku_filtered() -> None:
    async def _run() -> None:
        svc = DiscordEntitlementsService(_config(user_skus=(100,)))
        await svc.on_entitlement_create(_ent(sku_id=999, user_id=42))
        assert svc.is_user_premium(42) is False

    asyncio.run(_run())


def test_listener_update_replaces_and_delete_removes() -> None:
    async def _run() -> None:
        svc = DiscordEntitlementsService(_config(user_skus=(100,)))
        ent = _ent(sku_id=100, user_id=42)
        await svc.on_entitlement_create(ent)
        assert svc.cache_size() == 1

        # Update with a future ends_at — should still be in cache.
        future = datetime.now(tz=UTC) + timedelta(days=30)
        ent.ends_at = future
        await svc.on_entitlement_update(ent)
        assert svc.is_user_premium(42) is True

        # Update with past ends_at — should be removed.
        ent.ends_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        await svc.on_entitlement_update(ent)
        assert svc.cache_size() == 0

        # Re-add then delete.
        ent.ends_at = None
        await svc.on_entitlement_create(ent)
        assert svc.cache_size() == 1
        await svc.on_entitlement_delete(ent)
        assert svc.cache_size() == 0

    asyncio.run(_run())


def test_from_interaction_user_scope() -> None:
    svc = DiscordEntitlementsService(_config(user_skus=(100,)))
    ent = _ent(sku_id=100, user_id=42)
    interaction = SimpleNamespace(
        entitlements=[ent],
        user=SimpleNamespace(id=42),
        guild=None,
    )
    ok, reason = svc.from_interaction(interaction, dm_only=True)
    assert ok is True
    assert reason == "discord_user"


def test_from_interaction_guild_scope_skipped_when_dm_only() -> None:
    svc = DiscordEntitlementsService(_config(guild_skus=(200,)))
    ent = _ent(sku_id=200, guild_id=999)
    interaction = SimpleNamespace(
        entitlements=[ent],
        user=SimpleNamespace(id=42),
        guild=SimpleNamespace(id=999),
    )
    ok_dm, _ = svc.from_interaction(interaction, dm_only=True)
    assert ok_dm is False
    ok_guild, reason = svc.from_interaction(interaction, dm_only=False)
    assert ok_guild is True
    assert reason == "discord_guild"


def test_from_interaction_returns_false_when_disabled() -> None:
    cfg = DiscordPremiumConfig(enabled=False, user_sku_ids=(100,), guild_sku_ids=(), upgrade_url="")
    svc = DiscordEntitlementsService(cfg)
    ent = _ent(sku_id=100, user_id=42)
    interaction = SimpleNamespace(
        entitlements=[ent],
        user=SimpleNamespace(id=42),
        guild=None,
    )
    ok, reason = svc.from_interaction(interaction, dm_only=False)
    assert ok is False
    assert reason is None
