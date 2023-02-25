from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.bot import MangaClient

import discord
from discord import app_commands
from discord.ext.commands import GroupCog

from src.objects import GuildSettings


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

        elif interaction.guild.me.guild_permissions.manage_webhooks is False:
            em = discord.Embed(
                title="Error",
                description="I don't have permission to manage webhooks.",
                color=0xFF0000,
            )
            em.description += (
                "\nThis is important so I can send updates to the channel you specify."
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
        await interaction.response.defer(ephemeral=True, thinking=True)

        existing_config: GuildSettings = await self.bot.db.get_guild_config(
            interaction.guild_id
        )
        if existing_config and existing_config.channel.id == channel.id:
            if existing_config.webhook:
                try:
                    await existing_config.webhook.delete(reason="Manga Bot - Setup")
                except discord.HTTPException:
                    pass

        webhook: discord.Webhook = await channel.create_webhook(
            name="Manga Bot",
            avatar=await self.bot.user.avatar.read(),
            reason="Manga Bot",
        )
        guild_config: GuildSettings = GuildSettings(
            self.bot, interaction.guild_id, channel.id, updates_role.id, webhook.url
        )
        await self.bot.db.upsert_config(guild_config)

        em = discord.Embed(
            title="Setup",
            description=(
                "Setup complete!\n\n"
                "> **Channel:** <#{}>\n"
                "> **Updates Role:** <@&{}>\n"
                "> **Webhook Details:**\n"
                "> \u200b \u200b- ID: {}"
            ).format(
                guild_config.channel.id,
                guild_config.role.id,
                guild_config.webhook.id,
            ),
        )

        em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)

        return await interaction.followup.send(embed=em, ephemeral=True)

    @app_commands.command(
        name="show", description="Shows the current config for this server."
    )
    async def show_config(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild_config: GuildSettings = await self.bot.db.get_guild_config(
            interaction.guild_id
        )
        if not guild_config:
            em = discord.Embed(
                title="Error",
                description="There is no config for this server.\n\nSetup the bot with `/config setup`.",
                color=0xFF0000,
            )
            em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        em = discord.Embed(
            title="Config",
            description=(
                "> **Channel:** <#{}>\n"
                "> **Updates Role:** <@&{}>\n"
                "> **Webhook Details:**\n"
                "> \u200b \u200b- ID: {}"
            ).format(
                guild_config.channel.id,
                guild_config.role.id,
                guild_config.webhook.id,
            ),
        )
        em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)

        return await interaction.followup.send(embed=em, ephemeral=True)

    @app_commands.command(
        name="clear", description="Clears the current config for this server."
    )
    async def clear_config(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild_config: GuildSettings = await self.bot.db.get_guild_config(
            interaction.guild_id
        )

        if not guild_config:
            em = discord.Embed(
                title="Error",
                description="There is no config for this server.\n\nSetup the bot with `/config setup`.",
                color=0xFF0000,
            )
            em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        if guild_config.channel:
            if guild_config.webhook:
                try:
                    await guild_config.webhook.delete(reason="Manga Bot - Clear Config")
                except (discord.Forbidden, discord.NotFound):
                    pass

        await self.bot.db.delete_config(interaction.guild_id)

        em = discord.Embed(
            title="Config",
            description=(
                "> **Channel:** None\n"
                "> **Updates Role:** None\n"
                "> **Webhook Details:**\n"
                "> \u200b \u200b- ID: Deleted"
            ),
        )
        em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)

        return await interaction.followup.send(embed=em, ephemeral=True)


async def setup(bot: MangaClient) -> None:
    if bot._debug_mode:
        await bot.add_cog(CommandsCog(bot), guild=discord.Object(id=bot.test_guild_id))
    else:
        await bot.add_cog(CommandsCog(bot))
