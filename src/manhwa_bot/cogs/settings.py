"""Settings cog — /settings command with ephemeral SettingsView."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..db.guild_settings import GuildSettingsStore
from ..ui.settings_view import SettingsView, _build_settings_embed, _collect_warnings

_log = logging.getLogger(__name__)


class SettingsCog(commands.Cog, name="Settings"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._store = GuildSettingsStore(bot.db)  # type: ignore[attr-defined]

    @app_commands.command(
        name="settings",
        description="Configure bot settings for this server",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id
        guild = interaction.guild
        if guild_id is None or guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        gs = await self._store.get(guild_id)
        scanlator_overrides = await self._store.list_scanlator_channels(guild_id)

        warnings = _collect_warnings(gs, guild, guild.me)
        embed = _build_settings_embed(gs, scanlator_overrides, warnings)
        view = SettingsView(self.bot, guild_id, gs, scanlator_overrides)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
