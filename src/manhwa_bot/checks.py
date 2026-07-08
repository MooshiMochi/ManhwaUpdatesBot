"""Permission/state checks for slash and prefix commands."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

PREMIUM_REQUIRED = "premium_required"


def resolve_member(interaction: discord.Interaction) -> discord.Member | None:
    """Resolve the invoking member without relying on the member cache.

    Guild interactions carry the member in the payload (``interaction.user``),
    which stays available even with guild chunking disabled; the cache lookup
    is only a fallback.
    """
    user = interaction.user
    if isinstance(user, discord.Member):
        return user
    if interaction.guild is not None:
        return interaction.guild.get_member(user.id)
    return None


def can_manage_guild(member: discord.Member | None) -> bool:
    """Manage Server gate — Administrator always implies Manage Server."""
    if member is None:
        return False
    perms = member.guild_permissions
    return bool(perms.administrator or perms.manage_guild)


def has_premium(*, dm_only: bool = False):
    """Slash-command check that gates on the bot's :class:`PremiumService`.

    When ``dm_only`` is set, the check is bypassed entirely inside guilds —
    only DM invocations require premium. On denial, raises
    ``app_commands.CheckFailure("premium_required")`` so the global tree error
    handler can render the upgrade embed.
    """

    async def predicate(interaction: discord.Interaction) -> bool:
        if dm_only and interaction.guild is not None:
            return True
        bot: Any = interaction.client
        ok, _ = await bot.premium.is_premium(
            user_id=interaction.user.id,
            guild_id=interaction.guild.id if interaction.guild else None,
            interaction=interaction,
            dm_only=dm_only,
        )
        if not ok:
            raise app_commands.CheckFailure(PREMIUM_REQUIRED)
        return True

    return app_commands.check(predicate)


def has_premium_prefix(*, dm_only: bool = False):
    """Prefix-command analogue of :func:`has_premium` for the dev cog."""

    async def predicate(ctx: commands.Context) -> bool:
        if dm_only and ctx.guild is not None:
            return True
        bot: Any = ctx.bot
        ok, _ = await bot.premium.is_premium(
            user_id=ctx.author.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            interaction=None,
            dm_only=dm_only,
        )
        if not ok:
            raise commands.CheckFailure(PREMIUM_REQUIRED)
        return True

    return commands.check(predicate)
