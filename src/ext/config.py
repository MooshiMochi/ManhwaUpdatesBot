from __future__ import annotations

from typing import TYPE_CHECKING

from src.static import Emotes
from src.ui.views import SettingsView
from src.utils import check_missing_perms

if TYPE_CHECKING:
    from src.core import MangaClient

import discord
from discord import app_commands
from discord.ext.commands import Cog
from src.core import checks

from src.core.objects import DMSettings, GuildSettings


class ConfigCog(Cog):
    def __init__(self, bot: MangaClient) -> None:
        self.bot = bot

    async def cog_load(self):
        self.bot.logger.info("Loaded Config Cog...")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # if interaction.guild_id is None:
        #     em = discord.Embed(
        #         title="Error",
        #         description="This command can only be used in a server.",
        #         color=0xFF0000,
        #     )
        #     em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
        #     await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
        #     return False
        return True

    async def check_for_issues(self, interaction: discord.Interaction):
        """Checks for various system issues and outputs an embed with warnings if any.

        Args:
            interaction: The `discord.Interaction` object triggering the command.

        Returns:
            A `discord.Embed` object with warnings if found, or None if no issues are detected.
        """

        required_guild_perms = discord.Permissions(
            manage_roles=True, send_messages=True, embed_links=True, attach_files=True, use_external_emojis=True
        )
        required_channel_perms = discord.Permissions(
            send_messages=True, embed_links=True, attach_files=True, use_external_emojis=True
        )

        guild_settings = await self.bot.db.get_guild_config(interaction.guild_id)
        warnings_map: dict = {
            "notifications_channel": {
                "missing": {
                    "warning": f"{Emotes.error} Notifications Channel not set.",
                    "fix": "Set a valid Notifications Channel in `/settings` to be able to receive manhwa updates."
                },
                "permissions": {
                    "warning": f"{Emotes.error} Bot missing required permissions for the Notifications Channel.",
                    "fix": "Give me the {missing_perms} permissions for the {channel_mention} to be able to receive "
                           "manhwa updates."
                }
            },
            "system_channel": {
                "missing": {
                    "warning": f"{Emotes.warning} System Alerts Channel not set.",
                    "fix": "Set a valid System Alerts Channel in `/settings` to receive important system alerts."
                },
                "permissions": {
                    "warning": f"{Emotes.error} Bot missing required permissions for the System Alerts Channel",
                    "fix": "Give me the {missing_perms} for the {channel_mention} to receive important system alerts."
                }
            },
            "guild": {
                "permissions": {
                    "warning": f"{Emotes.error} Bot missing critical permissions in this server",
                    "fix": "Give me the {missing_perms} permissions for the server for the bot to work correctly!"
                }
            },
            "default_ping_role": {
                "notFound": {
                    "warning": f"{Emotes.warning} Unable to find the Default Ping Role.",
                    "fixIfIDNotNone": (
                            "Set a valid Default Ping Role in `/settings` to be able to use ping features or\n" +
                            "change the permissions for the <@&{ping_role_id}> role."),
                    "fixIfIDNone": "Set a valid Default Ping Role in `/settings` to be able to use ping features."
                }
            }
        }
        warnings: list[tuple[str, str]] = []

        def format_perms(perms_list: list[str]) -> str:
            _split = [x.replace("_", " ") for x in perms_list]
            titled = [x.title() for x in _split]
            formatted = "`" + ", ".join(titled) + "`"
            return formatted

        # Check notification channel and permissions
        notifications_channel = getattr(guild_settings, "notifications_channel", None)
        if not notifications_channel:
            warnings.append((warnings_map["notifications_channel"]["missing"]["warning"],
                             warnings_map["notifications_channel"]["missing"]["fix"]))
        elif not isinstance(notifications_channel, discord.TextChannel):
            warnings.append((warnings_map["notifications_channel"]["missing"]["warning"],
                             warnings_map["notifications_channel"]["missing"]["fix"]))
        else:
            missing_perms = check_missing_perms(notifications_channel.permissions_for(interaction.guild.me),
                                                required_channel_perms)
            if missing_perms:
                formatted_perms = format_perms(missing_perms)
                warnings.append((
                    warnings_map["notifications_channel"]["permissions"]["warning"],
                    warnings_map["notifications_channel"]["permissions"]["fix"].format(
                        channel_mention=notifications_channel.mention, missing_perms=formatted_perms)
                ))

        # Check system channel and permissions
        system_channel = getattr(guild_settings, "system_channel", None)
        if not system_channel:
            warnings.append((warnings_map["system_channel"]["missing"]["warning"],
                             warnings_map["system_channel"]["missing"]["fix"]))
        else:
            missing_perms = check_missing_perms(system_channel.permissions_for(interaction.guild.me),
                                                required_channel_perms)
            if missing_perms:
                formatted_perms = format_perms(missing_perms)
                warnings.append((
                    warnings_map["system_channel"]["permissions"]["warning"],
                    warnings_map["system_channel"]["permissions"]["fix"].format(
                        channel_mention=system_channel.mention, missing_perms=formatted_perms)
                ))

        # Check for missing guild permissions
        missing_perms = check_missing_perms(interaction.guild.me.guild_permissions, required_guild_perms)
        if missing_perms:
            formatted_perms = format_perms(missing_perms)
            warnings.append((
                warnings_map["guild"]["permissions"]["warning"],
                warnings_map["guild"]["permissions"]["fix"].format(missing_perms=formatted_perms)
            ))

        # Check for default ping role
        default_ping_role = getattr(guild_settings, "default_ping_role", None)
        default_ping_role_id = getattr(guild_settings, "default_ping_role_id", None)
        if not default_ping_role and not default_ping_role_id:
            if not default_ping_role_id:
                warnings.append((
                    warnings_map["default_ping_role"]["notFound"]["warning"],
                    warnings_map["default_ping_role"]["notFound"]["fixIfIDNone"]
                ))
        elif not default_ping_role and default_ping_role_id:
            warnings.append((
                warnings_map["default_ping_role"]["notFound"]["warning"],
                warnings_map["default_ping_role"]["notFound"]["fixIfIDNotNone"].format(
                    ping_role_id=default_ping_role_id
                )
            ))

        # Build embed and return
        if warnings:
            embed = discord.Embed(title="System Check",
                                  description=f"{Emotes.warning} {len(warnings)} warning"
                                              f"{'s' if len(warnings) > 1 else ''} found.",
                                  color=0xFF5555)
            for warning, solution in warnings:
                embed.add_field(name=warning, value=solution, inline=False)
            return embed

        return None

    @app_commands.command(
        name="settings",
        description="View and Edit the server/DM settings."
    )
    @checks.has_permissions(manage_guild=True, is_bot_manager=True)
    async def _settings(self, interaction: discord.Interaction):
        if interaction.guild_id:
            _id = interaction.guild_id
            config = await self.bot.db.get_guild_config(_id)
            if not config:
                config = GuildSettings(self.bot, _id, None, None)  # noqa
        else:
            _id = interaction.user.id
            config = await self.bot.db.get_guild_config(_id, user=True)
            if not config:
                config = DMSettings(self.bot, _id)

        view = SettingsView(self.bot, interaction, config)
        # noinspection PyProtectedMember
        embed = view.create_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)  # noqa

        if interaction.guild_id:  # Warnings should only be displayed for guilds, not DMs
            issues_embed: discord.Embed = await self.check_for_issues(interaction)
            if issues_embed:
                await interaction.followup.send(ephemeral=True, embed=issues_embed)


async def setup(bot: MangaClient) -> None:
    await bot.add_cog(ConfigCog(bot))
