"""Tests for the Manage Server permission gate (admin implies manage server)."""

from __future__ import annotations

import discord

from manhwa_bot.checks import can_manage_guild, resolve_member


class _FakePerms:
    def __init__(self, *, administrator: bool = False, manage_guild: bool = False) -> None:
        self.administrator = administrator
        self.manage_guild = manage_guild


class _FakeMember:
    def __init__(self, perms: _FakePerms) -> None:
        self.guild_permissions = perms


def test_can_manage_guild_accepts_manage_guild() -> None:
    assert can_manage_guild(_FakeMember(_FakePerms(manage_guild=True))) is True


def test_can_manage_guild_accepts_administrator_without_manage_guild() -> None:
    assert can_manage_guild(_FakeMember(_FakePerms(administrator=True))) is True


def test_can_manage_guild_rejects_regular_member() -> None:
    assert can_manage_guild(_FakeMember(_FakePerms())) is False


def test_can_manage_guild_rejects_none_member() -> None:
    assert can_manage_guild(None) is False


def test_resolve_member_prefers_interaction_payload_member() -> None:
    member = discord.Object(id=1)
    member.__class__ = type("_M", (discord.Object,), {})

    class _Interaction:
        user = None
        guild = None

    interaction = _Interaction()

    class _Guild:
        def get_member(self, _user_id: int) -> None:
            raise AssertionError("cache lookup should not run for payload members")

    real_member = discord.Member.__new__(discord.Member)
    interaction.user = real_member
    interaction.guild = _Guild()
    assert resolve_member(interaction) is real_member


def test_resolve_member_falls_back_to_guild_cache_for_user_payload() -> None:
    sentinel = object()

    class _User:
        id = 42

    class _Guild:
        def get_member(self, user_id: int):
            assert user_id == 42
            return sentinel

    class _Interaction:
        user = _User()
        guild = _Guild()

    assert resolve_member(_Interaction()) is sentinel
