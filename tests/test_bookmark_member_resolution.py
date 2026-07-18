"""Membership resolution in the bookmark browser must not trust the member cache.

With ``chunk_guilds_at_startup=False`` the member cache is empty for most
guilds, so ``guild.get_member()`` returning ``None`` does NOT mean the user is
absent — the view must fall back to ``guild.fetch_member()`` before declaring
"you aren't in a mutual server".
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord

from manhwa_bot.ui.components.bookmark import BookmarkBrowserView


def _bare_view(invoker_id: int = 123) -> BookmarkBrowserView:
    view = object.__new__(BookmarkBrowserView)
    view._invoker_id = invoker_id
    view._member_memo = {}
    return view


def _guild(guild_id: int = 555) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    return guild


def test_cache_hit_skips_fetch() -> None:
    async def _run() -> None:
        view = _bare_view()
        guild = _guild()
        member = MagicMock(spec=discord.Member)
        guild.get_member.return_value = member
        guild.fetch_member = AsyncMock()

        resolved = await view._resolve_invoker_member(guild)

        assert resolved is member
        guild.fetch_member.assert_not_awaited()

    asyncio.run(_run())


def test_cache_miss_falls_back_to_fetch() -> None:
    async def _run() -> None:
        view = _bare_view()
        guild = _guild()
        member = MagicMock(spec=discord.Member)
        guild.get_member.return_value = None
        guild.fetch_member = AsyncMock(return_value=member)

        resolved = await view._resolve_invoker_member(guild)

        assert resolved is member
        guild.fetch_member.assert_awaited_once_with(123)

    asyncio.run(_run())


def test_fetch_404_means_not_a_member() -> None:
    async def _run() -> None:
        view = _bare_view()
        guild = _guild()
        guild.get_member.return_value = None
        response = MagicMock(status=404, reason="Not Found")
        guild.fetch_member = AsyncMock(
            side_effect=discord.NotFound(response, {"message": "Unknown Member"})
        )

        resolved = await view._resolve_invoker_member(guild)

        assert resolved is None

    asyncio.run(_run())


def test_result_is_memoised_per_guild() -> None:
    async def _run() -> None:
        view = _bare_view()
        guild = _guild()
        guild.get_member.return_value = None
        guild.fetch_member = AsyncMock(return_value=MagicMock(spec=discord.Member))

        first = await view._resolve_invoker_member(guild)
        second = await view._resolve_invoker_member(guild)

        assert first is second
        guild.fetch_member.assert_awaited_once()

    asyncio.run(_run())


def test_missing_invoker_id_resolves_none_without_calls() -> None:
    async def _run() -> None:
        view = _bare_view(invoker_id=0)
        guild = _guild()
        guild.fetch_member = AsyncMock()

        resolved = await view._resolve_invoker_member(guild)

        assert resolved is None
        guild.get_member.assert_not_called()
        guild.fetch_member.assert_not_awaited()

    asyncio.run(_run())
