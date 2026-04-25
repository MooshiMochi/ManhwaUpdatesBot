"""Tests for PremiumService decision order and dm_only semantics."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from manhwa_bot.config import DiscordPremiumConfig, PatreonPremiumConfig, PremiumConfig
from manhwa_bot.premium.service import PremiumService


class _FakeGrants:
    def __init__(self, user: bool = False, guild: bool = False) -> None:
        self.user = user
        self.guild = guild

    async def is_active(self, scope: str, _target_id: int) -> bool:
        return self.user if scope == "user" else self.guild


class _FakePatreon:
    def __init__(self, ok: bool = False) -> None:
        self._ok = ok

    async def is_premium(self, _user_id: int) -> bool:
        return self._ok


class _FakeDiscordEnts:
    def __init__(
        self,
        *,
        user: bool = False,
        guild: bool = False,
        interaction_user: bool = False,
        interaction_guild: bool = False,
    ) -> None:
        self.user = user
        self.guild = guild
        self.interaction_user = interaction_user
        self.interaction_guild = interaction_guild

    def is_user_premium(self, _user_id: int) -> bool:
        return self.user

    def is_guild_premium(self, _guild_id: int) -> bool:
        return self.guild

    def from_interaction(self, _interaction: Any, *, dm_only: bool) -> tuple[bool, str | None]:
        if self.interaction_user:
            return (True, "discord_user")
        if not dm_only and self.interaction_guild:
            return (True, "discord_guild")
        return (False, None)


def _config(
    *,
    enabled: bool = True,
    owner_bypass: bool = True,
    discord_enabled: bool = True,
    patreon_enabled: bool = True,
) -> PremiumConfig:
    return PremiumConfig(
        enabled=enabled,
        owner_bypass=owner_bypass,
        log_decisions=False,
        discord=DiscordPremiumConfig(
            enabled=discord_enabled,
            user_sku_ids=(100,),
            guild_sku_ids=(200,),
            upgrade_url="",
        ),
        patreon=PatreonPremiumConfig(
            enabled=patreon_enabled,
            campaign_id=1,
            poll_interval_seconds=600,
            freshness_seconds=1800,
            required_tier_ids=(),
            pledge_url="",
            access_token="x",
        ),
    )


def _make(
    *,
    config: PremiumConfig,
    grants: _FakeGrants | None = None,
    patreon: _FakePatreon | None = None,
    ents: _FakeDiscordEnts | None = None,
    owner_ids: set[int] | None = None,
) -> PremiumService:
    bot = SimpleNamespace(owner_ids=owner_ids if owner_ids is not None else set())
    return PremiumService(
        bot,
        config,
        grants or _FakeGrants(),  # type: ignore[arg-type]
        patreon or _FakePatreon(),  # type: ignore[arg-type]
        ents or _FakeDiscordEnts(),  # type: ignore[arg-type]
    )


def test_disabled_returns_true() -> None:
    async def _run() -> None:
        svc = _make(config=_config(enabled=False))
        ok, reason = await svc.is_premium(user_id=1, guild_id=2)
        assert ok is True
        assert reason == "disabled"

    asyncio.run(_run())


def test_owner_bypass_wins_over_no_grants() -> None:
    async def _run() -> None:
        svc = _make(config=_config(), owner_ids={42})
        ok, reason = await svc.is_premium(user_id=42, guild_id=None)
        assert ok is True
        assert reason == "owner"

    asyncio.run(_run())


def test_grant_user_priority() -> None:
    async def _run() -> None:
        # Both grant_user and grant_guild active — user wins (lower priority # = higher prio).
        svc = _make(
            config=_config(),
            grants=_FakeGrants(user=True, guild=True),
            patreon=_FakePatreon(ok=True),
            ents=_FakeDiscordEnts(user=True, guild=True),
        )
        ok, reason = await svc.is_premium(user_id=1, guild_id=2)
        assert ok is True
        assert reason == "grant_user"

    asyncio.run(_run())


def test_grant_guild_priority_over_patreon_and_discord() -> None:
    async def _run() -> None:
        svc = _make(
            config=_config(),
            grants=_FakeGrants(guild=True),
            patreon=_FakePatreon(ok=True),
            ents=_FakeDiscordEnts(user=True, guild=True),
        )
        ok, reason = await svc.is_premium(user_id=1, guild_id=2)
        assert ok is True
        assert reason == "grant_guild"

    asyncio.run(_run())


def test_patreon_priority_over_discord() -> None:
    async def _run() -> None:
        svc = _make(
            config=_config(),
            patreon=_FakePatreon(ok=True),
            ents=_FakeDiscordEnts(user=True, guild=True),
        )
        ok, reason = await svc.is_premium(user_id=1, guild_id=2)
        assert ok is True
        assert reason == "patreon"

    asyncio.run(_run())


def test_discord_user_priority_over_discord_guild() -> None:
    async def _run() -> None:
        svc = _make(
            config=_config(),
            ents=_FakeDiscordEnts(user=True, guild=True),
        )
        ok, reason = await svc.is_premium(user_id=1, guild_id=2)
        assert ok is True
        assert reason == "discord_user"

    asyncio.run(_run())


def test_discord_guild_only() -> None:
    async def _run() -> None:
        svc = _make(
            config=_config(),
            ents=_FakeDiscordEnts(guild=True),
        )
        ok, reason = await svc.is_premium(user_id=1, guild_id=2)
        assert ok is True
        assert reason == "discord_guild"

    asyncio.run(_run())


def test_no_source_returns_false() -> None:
    async def _run() -> None:
        svc = _make(config=_config())
        ok, reason = await svc.is_premium(user_id=1, guild_id=2)
        assert ok is False
        assert reason is None

    asyncio.run(_run())


def test_dm_only_skips_guild_grants_and_discord_guild() -> None:
    async def _run() -> None:
        svc = _make(
            config=_config(),
            grants=_FakeGrants(guild=True),
            ents=_FakeDiscordEnts(guild=True),
        )
        ok, reason = await svc.is_premium(user_id=1, guild_id=2, dm_only=True)
        assert ok is False
        assert reason is None

    asyncio.run(_run())


def test_interaction_short_circuits_to_discord_user() -> None:
    async def _run() -> None:
        svc = _make(config=_config(), ents=_FakeDiscordEnts(interaction_user=True))
        ok, reason = await svc.is_premium(
            user_id=1,
            guild_id=2,
            interaction=SimpleNamespace(),
        )
        assert ok is True
        assert reason == "discord_user"

    asyncio.run(_run())
