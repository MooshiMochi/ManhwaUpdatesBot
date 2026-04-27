"""Tests for the owner-only dev prefix help output."""

from __future__ import annotations

import asyncio
from typing import Any

import discord

from manhwa_bot.cogs.dev import DevCog

from .test_bot_skeleton import _make_bot


class _Ctx:
    clean_prefix = "?"
    invoked_with = "dev"

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, content: str | None = None, **kwargs: Any) -> None:
        self.sent.append({"content": content, **kwargs})


def test_dev_help_command_lists_commands_with_descriptions() -> None:
    bot = _make_bot()
    cog = DevCog(bot)
    command = cog.developer.get_command("help")

    assert command is not None

    ctx = _Ctx()
    asyncio.run(command.callback(cog, ctx))  # type: ignore[misc]

    assert len(ctx.sent) == 1
    embed = ctx.sent[0]["embed"]
    assert isinstance(embed, discord.Embed)

    text = "\n".join(field.value for field in embed.fields)
    assert "`?dev restart`" in text
    assert "Restart the bot process" in text
    assert "`?dev crawler health`" in text
    assert "Show crawler schema health" in text
