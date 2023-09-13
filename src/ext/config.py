from __future__ import annotations

from typing import TYPE_CHECKING

from src.ui.views import SettingsView

if TYPE_CHECKING:
    from src.core import MangaClient

import discord
from discord import app_commands
from discord.ext.commands import Cog

from src.core.objects import GuildSettings
from src.overwrites import Embed


class ConfigCog(Cog):
    def __init__(self, bot: MangaClient) -> None:
        self.bot = bot

    async def cog_load(self):
        self.bot.logger.info("Loaded Config Cog...")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            em = Embed(
                bot=self.bot,
                title="Error",
                description="This command can only be used in a server.",
                color=0xFF0000,
            )
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
            return False

        if (
                interaction.user.guild_permissions.manage_roles
                or interaction.user.id in self.bot.owner_ids
                or interaction.user.guild_permissions.administrator
                or interaction.user.guild_permissions.manage_channels
        ):
            return True

        em = Embed(
            bot=self.bot,
            title="Error",
            description="You don't have permission to do that.",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
        return False

    @app_commands.command(
        name="settings",
        description="View and Edit the server settings."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _settings(self, interaction: discord.Interaction):
        guild_config: GuildSettings = await self.bot.db.get_guild_config(interaction.guild_id)
        if not guild_config:
            guild_config = GuildSettings(self.bot, interaction.guild_id, None, None)  # noqa
        view = SettingsView(self.bot, interaction, guild_config)
        # noinspection PyProtectedMember
        embed = view._create_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)  # noqa


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_ids:
        await bot.add_cog(ConfigCog(bot), guilds=[discord.Object(id=x) for x in bot.test_guild_ids])
    else:
        await bot.add_cog(ConfigCog(bot))
