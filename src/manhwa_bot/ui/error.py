"""Shared error-embed helper used by cogs and the global app-command handler."""

from __future__ import annotations

import discord

# Standard sources, used as embed titles so the user can tell at a glance where
# the error originated.
SOURCE_BOT = "Bot Error"
SOURCE_CRAWLER = "Crawler Error"
SOURCE_PERMISSION = "Permission Error"
SOURCE_COOLDOWN = "Cooldown"
SOURCE_VALIDATION = "Invalid Input"


def error_embed(message: str, *, source: str = SOURCE_BOT) -> discord.Embed:
    return discord.Embed(
        title=source,
        description=message,
        colour=discord.Colour.red(),
    )
