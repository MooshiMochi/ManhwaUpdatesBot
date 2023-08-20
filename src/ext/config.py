from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING

from src.ui.views import ConfirmView

if TYPE_CHECKING:
    from src.core import MangaClient

import discord
from discord import app_commands
from discord.ext.commands import GroupCog

from src.core.objects import GuildSettings
from src.static import Emotes


class ConfigCog(GroupCog, name="config", description="Config commands."):
    def __init__(self, bot):
        self.bot: MangaClient = bot

    async def cog_load(self):
        self.bot.logger.info("Loaded Config Cog...")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            em = discord.Embed(
                title="Error",
                description="This command can only be used in a server.",
                color=0xFF0000,
            )
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
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
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
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
        em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.avatar.url)
        await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
        return False

    @app_commands.command(name="setup", description="Setup the bot for this server.")
    @app_commands.describe(
        channel="The channel to send updates to.",
        auto_create_role="Whether to automatically create a role for new tracked series or use default role.",
        role="The default role to ping when a new update is released.",
        ping_for_dev_notifications="Whether to ping the default role when the developer sends a manual update."
    )
    async def _setup(
            self,
            interaction: discord.Interaction,
            channel: discord.TextChannel,
            auto_create_role: Optional[bool] = False,
            role: Optional[discord.Role] = None,
            ping_for_dev_notifications: Optional[bool] = True
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        manage_webhooks_perms = channel.permissions_for(interaction.guild.me).manage_webhooks
        send_messages_perms = channel.permissions_for(interaction.guild.me).send_messages
        attach_files_perms = channel.permissions_for(interaction.guild.me).attach_files
        send_links_perms = channel.permissions_for(interaction.guild.me).embed_links
        required_perms = [manage_webhooks_perms, send_messages_perms, attach_files_perms, send_links_perms]
        if not all(required_perms):
            raise app_commands.errors.BotMissingPermissions([
                "manage_webhooks", "send_messages", "attach_files", "embed_links"
            ])

        if role:
            if role.is_bot_managed():
                return await interaction.followup.send(
                    embed=(
                        discord.Embed(
                            title="Invalid Role",
                            description=(
                                "The role you provided is managed by a bot.\n"
                                "Please provide a role that is not managed by a bot."
                            ),
                            color=discord.Color.red())),
                )
            elif role >= interaction.guild.me.top_role:
                return await interaction.followup.send(
                    embed=(
                        discord.Embed(
                            title="Not Enough Permissions",
                            description=(
                                "The role you provided is higher than my top role.\n"
                                "Please move the role below my top role and try again."
                            ),
                            color=discord.Color.red())),
                )

        existing_config: GuildSettings = await self.bot.db.get_guild_config(
            interaction.guild_id
        )
        if existing_config and existing_config.notifications_channel.id == channel.id:
            if existing_config.notifications_webhook:
                try:
                    await existing_config.notifications_webhook.delete(reason="Manhwa Updates - Setup")
                except discord.HTTPException:
                    pass

        webhook: discord.Webhook = await channel.create_webhook(
            name="Manhwa Updates",
            avatar=await self.bot.user.avatar.read(),
            reason="Manhwa Updates",
        )
        default_role_id = role.id if role else None

        if existing_config:
            if default_role_id and default_role_id != existing_config.default_ping_role.id:
                if existing_config.default_ping_role:
                    await self.bot.db.update_guild_tracked_series_ping_role(
                        interaction.guild_id, existing_config.default_ping_role, default_role_id
                    )
                else:
                    await self.bot.db.update_guild_tracked_series_ping_role(
                        interaction.guild_id, None, default_role_id
                    )

        guild_config: GuildSettings = GuildSettings(
            self.bot, interaction.guild_id, channel.id, default_role_id, webhook.url, auto_create_role,
            ping_for_dev_notifications
        )
        await self.bot.db.upsert_config(guild_config)

        em = discord.Embed(
            title="Setup",
            description=(
                "Tracking setup complete!\n\n"
                "> **Notifications Channel:** <#{}>\n"
                "> **Updates Role:** {}\n"
                "> **Webhook Details:**\n"
                "> \u200b \u200b- ID: {}\n"
                "> **Auto Create Role:** {}\n"
                "> **Ping for Dev Notifications:** {}"
            ).format(
                guild_config.notifications_channel.id,
                f'<@&{guild_config.default_ping_role.id}>' if guild_config.default_ping_role else "`None set`",
                guild_config.notifications_webhook.id,
                auto_create_role,
                ping_for_dev_notifications,
            ),
            colour=discord.Colour.green()
        )

        em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.avatar.url)

        return await interaction.followup.send(embed=em, ephemeral=True)

    @app_commands.command(
        name="show", description="Shows the current config for this server."
    )
    async def _show(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        guild_config: GuildSettings = await self.bot.db.get_guild_config(
            interaction.guild_id
        )
        if not guild_config:
            em = discord.Embed(
                title="Error",
                color=0xFF0000,
                description="There is no config for this server.\nSetup the bot with `/config setup`."
            )
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        em = discord.Embed(
            title="Config",
            description=(
                "> **Notifications Channel:** <#{}>\n"
                "> **Updates Role:** {}\n"
                "> **Webhook Details:**\n"
                "> \u200b \u200b- ID: {}\n"
                "> **Auto Create Role:** {}\n"
                "> **Ping for Dev Notifications:** {}"
            ).format(
                guild_config.notifications_channel.id,
                f'<@&{guild_config.default_ping_role.id}>' if guild_config.default_ping_role else "`None set`",
                guild_config.notifications_webhook.id,
                bool(guild_config.auto_create_role),
                bool(guild_config.dev_notifications_ping),
            ),
            colour=discord.Colour.green()
        )
        em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.avatar.url)
        return await interaction.followup.send(embed=em, ephemeral=True)

    @app_commands.command(
        name="clear", description="Clears the current config for this server."
    )
    @app_commands.describe(
        full_clear="Whether to clear all data related to this server including roles and webhooks."
    )
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.guild_id)
    async def _clear_config(self, interaction: discord.Interaction, full_clear: Optional[bool] = False):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        guild_config: GuildSettings = await self.bot.db.get_guild_config(
            interaction.guild_id
        )

        if not guild_config:
            em = discord.Embed(
                title="Error",
                color=0xFF0000,
                description="There is no config for this server.\nSetup the bot with `/config setup`."
            )
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        deleted_tracked_manga = None
        deleted_roles = None

        if full_clear is True:
            confirm_view = ConfirmView(self.bot, interaction)
            await interaction.followup.send(
                embed=discord.Embed(
                    title=f"{Emotes.warning} Are you sure?",
                    description=(
                        "This will delete all data related to this server including tracked manhwa, roles and webhooks."
                        "\nThis means that the database for this server will be set as if the bot was never here.\n"
                        f"{Emotes.warning} **This action is irreversible.** {Emotes.warning}"
                    ),
                    color=discord.Color.red()
                ),
                view=confirm_view
            )

            await confirm_view.wait()

            if confirm_view.value is False or confirm_view.value is None:
                return await interaction.followup.send(
                    embed=discord.Embed(
                        title=f"{Emotes.success} Action cancelled.",
                        color=discord.Color.green()
                    ),
                    ephemeral=True
                )
            guild_role_ids = await self.bot.db.get_all_guild_bot_created_roles(interaction.guild_id)
            # guild_role_ids.append(guild_config.default_ping_role.id) if guild_config.default_ping_role else None
            # default ping role was not created by the bot, so we shouldn't delete it.
            guild_roles = [interaction.guild.get_role(x) for x in guild_role_ids]
            guild_roles = [x for x in guild_roles if x is not None]
            batch_size = 50
            batches = [guild_roles[i:i + batch_size] for i in range(0, len(guild_roles), batch_size)]
            for batch in batches:
                await asyncio.gather(*[x.delete(reason="Manhwa Updates - Clear Config") for x in batch])
                if len(batches) > 1:
                    await asyncio.sleep(60)  # wait for 1 minute if there is more than one batch

            deleted_roles = len(guild_roles)
            deleted_tracked_manga = await self.bot.db.delete_guild_tracked_series(interaction.guild_id)
            await self.bot.db.delete_all_guild_created_roles(interaction.guild_id)

        if guild_config.notifications_channel:
            if guild_config.notifications_webhook:
                try:
                    await guild_config.notifications_webhook.delete(reason="Manhwa Updates - Clear Config")
                except (discord.Forbidden, discord.NotFound):
                    pass

        await self.bot.db.delete_config(interaction.guild_id)  # deletes the whole config

        em = discord.Embed(
            title="Config deleted",
            description=(
                    "> **Notifications Channel:** None\n"
                    "> **Updates Role:** None\n"
                    "> **Webhook Details:**\n"
                    "> \u200b \u200b- ID: Deleted\n"
                    "> **Auto Create Role:** Deleted\n"
                    "> **Ping for Dev Notifications:** Deleted\n"
                    + (f"\n> **Deleted Tracked Series:** {deleted_tracked_manga}" if deleted_tracked_manga else '')
                    + (f"\n> **Deleted Roles:** {deleted_roles}" if deleted_roles else '')
            ),
            colour=discord.Colour.red()
        )

        em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.avatar.url)

        return await interaction.followup.send(embed=em, ephemeral=True)


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_ids:
        await bot.add_cog(ConfigCog(bot), guilds=[discord.Object(id=x) for x in bot.test_guild_ids])
    else:
        await bot.add_cog(ConfigCog(bot))
