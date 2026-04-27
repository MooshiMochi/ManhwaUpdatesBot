"""Settings cog — /settings command with ephemeral SettingsView."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from ..db.guild_settings import GuildSettingsStore
from ..ui.settings_view import (
    DmSettingsView,
    SettingsView,
    _build_settings_embed,
    _collect_warnings,
)

_log = logging.getLogger(__name__)


class SettingsCog(commands.Cog, name="Settings"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._store = GuildSettingsStore(bot.db)  # type: ignore[attr-defined]

    @app_commands.command(
        name="settings",
        description="Configure bot settings for this server (or your DM preferences).",
    )
    async def settings(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await self._handle_dm(interaction)
            return
        await self._handle_guild(interaction)

    async def _handle_guild(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id
        guild = interaction.guild
        if guild_id is None or guild is None:
            await interaction.response.send_message(
                "This command needs a server context.", ephemeral=True
            )
            return

        member = guild.get_member(interaction.user.id)
        if member is None or not member.guild_permissions.manage_guild:
            existing = await self._store.get(guild_id)
            allowed = (
                existing is not None
                and existing.bot_manager_role_id is not None
                and member is not None
                and any(r.id == existing.bot_manager_role_id for r in member.roles)
            )
            if not allowed:
                await interaction.response.send_message(
                    "You need the **Manage Server** permission (or the configured bot "
                    "manager role) to edit server settings.",
                    ephemeral=True,
                )
                return

        gs = await self._store.get(guild_id)
        scanlator_overrides = await self._store.list_scanlator_channels(guild_id)

        warnings = _collect_warnings(gs, guild, guild.me)
        embed = _build_settings_embed(gs, scanlator_overrides, warnings)
        view = SettingsView(self.bot, guild_id, gs, scanlator_overrides)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _handle_dm(self, interaction: discord.Interaction) -> None:
        bot: Any = self.bot
        ok, reason = await bot.premium.is_premium(
            user_id=interaction.user.id,
            guild_id=None,
            interaction=interaction,
            dm_only=True,
        )
        if not ok:
            await interaction.response.send_message(
                "DM settings require premium. Use `/patreon` for details."
                if reason is None
                else f"DM settings require premium ({reason}). Use `/patreon` for details.",
                ephemeral=True,
            )
            return

        view = DmSettingsView(bot, interaction.user.id)
        await view.initialize()
        await interaction.response.send_message(
            embed=view.build_embed(), view=view, ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
