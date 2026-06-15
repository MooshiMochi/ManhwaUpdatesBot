"""`/track new` auto-creates a ping role when the server opted in."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from manhwa_bot.cogs.tracking import TrackingCog


def _make_cog() -> TrackingCog:
    # The cog only needs ``bot.db`` to build its stores, and the stores merely
    # hold the pool reference — a stub is enough to exercise the role helper.
    bot = SimpleNamespace(db=SimpleNamespace())
    return TrackingCog(bot)  # type: ignore[arg-type]


def _make_guild(*, manage_roles: bool) -> SimpleNamespace:
    me = SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=manage_roles))
    return SimpleNamespace(id=123, me=me, create_role=AsyncMock())


def test_auto_create_ping_role_creates_mentionable_role() -> None:
    cog = _make_cog()
    guild = _make_guild(manage_roles=True)
    sentinel = object()
    guild.create_role.return_value = sentinel

    async def _run() -> None:
        role = await cog._auto_create_ping_role(guild, "Solo Leveling")  # type: ignore[arg-type]
        assert role is sentinel
        guild.create_role.assert_awaited_once()
        kwargs = guild.create_role.await_args.kwargs
        assert kwargs["name"] == "Solo Leveling"
        assert kwargs["mentionable"] is True

    asyncio.run(_run())


def test_auto_create_ping_role_requires_manage_roles() -> None:
    cog = _make_cog()
    guild = _make_guild(manage_roles=False)

    async def _run() -> None:
        role = await cog._auto_create_ping_role(guild, "Solo Leveling")  # type: ignore[arg-type]
        assert role is None
        guild.create_role.assert_not_awaited()

    asyncio.run(_run())


def test_auto_create_ping_role_truncates_long_title() -> None:
    cog = _make_cog()
    guild = _make_guild(manage_roles=True)
    guild.create_role.return_value = object()

    async def _run() -> None:
        await cog._auto_create_ping_role(guild, "x" * 250)  # type: ignore[arg-type]
        kwargs = guild.create_role.await_args.kwargs
        assert len(kwargs["name"]) == 100

    asyncio.run(_run())


def test_auto_create_ping_role_handles_http_error() -> None:
    cog = _make_cog()
    guild = _make_guild(manage_roles=True)
    guild.create_role.side_effect = discord.HTTPException(
        SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions"
    )

    async def _run() -> None:
        role = await cog._auto_create_ping_role(guild, "Solo Leveling")  # type: ignore[arg-type]
        assert role is None

    asyncio.run(_run())
