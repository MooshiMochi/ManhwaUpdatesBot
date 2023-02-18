from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.bot import MangaClient

import discord
from discord import app_commands
from discord.ext.commands import GroupCog


class CommandsCog(GroupCog, name="config", description="Config commands."):
    def __init__(self, bot):
        self.bot: MangaClient = bot

    async def cog_load(self):
        self.bot._logger.info("Loaded Commands Cog...")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            em = discord.Embed(
                title="Error",
                description="This command can only be used in a server.",
                color=0xFF0000,
            )
            em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)
            return False

        if (
            interaction.user.guild_permissions.manage_roles
            or interaction.user.id in self.bot.owner_ids
            or interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.manage_channels
        ):
            return True

        em = discord.Embed(
            title="Error",
            description="You don't have permission to do that.",
            color=0xFF0000,
        )
        em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)
        await interaction.response.send_message(embed=em, ephemeral=True)
        return False

    @app_commands.command(name="setup", description="Setup the bot for this server.")
    @app_commands.describe(
        channel="The channel to send updates to.",
        updates_role="The role to ping for updates.",
    )
    async def setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        updates_role: discord.Role,
    ):
        webhook: discord.Webhook = await channel.create_webhook(
            name="Manga Bot",
            avatar=await self.bot.user.avatar.read(),
            reason="Manga Bot",
        )
        await self.bot.db.upsert_config(
            interaction.guild_id, channel.id, updates_role.id, webhook.url
        )

        em = discord.Embed(
            title="Setup",
            description="Setup complete!\n\n> **Channel:** {}\n> **Updates Role:** {}".format(
                channel.mention, updates_role.mention
            ),
        )
        em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)

        return await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(
        name="show", description="Shows the current config for this server."
    )
    async def show_config(self, interaction: discord.Interaction):
        guild_config = await self.bot.db.get_guild_config(interaction.guild_id)

        em = discord.Embed(
            title="Config",
            description="> **Channel:** <#{}>\n> **Updates Role:** <@&{}>".format(
                guild_config[0], guild_config[1]
            ),
        )
        em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)

        return await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(
        name="clear", description="Clears the current config for this server."
    )
    async def clear_config(self, interaction: discord.Interaction):
        await self.bot.db.delete_config(interaction.guild_id)

        em = discord.Embed(
            title="Config",
            description="> **Channel:** None\n> **Updates Role:** None",
        )
        em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)

        return await interaction.response.send_message(embed=em, ephemeral=True)


async def setup(bot: MangaClient) -> None:
    if bot._debug_mode:
        await bot.add_cog(CommandsCog(bot), guild=discord.Object(id=bot.test_guild_id))
    else:
        await bot.add_cog(CommandsCog(bot))
