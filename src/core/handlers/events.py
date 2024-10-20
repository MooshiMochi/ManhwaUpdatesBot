from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core import GuildSettings, MangaClient

import discord
from discord.ext import commands


class EventListenerCog(commands.Cog):
    def __init__(self, bot: MangaClient):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.logger.info("Loaded Event Listener Cog...")

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        author = entry.user_id
        if author == self.bot.user.id:
            return

        if entry.action == discord.AuditLogAction.role_delete:
            guild_config = await self.bot.db.get_guild_config(entry.guild.id)
            if guild_config is not None and guild_config.default_ping_role_id == entry.target.id:
                guild_config.default_ping_role = None
                await self.bot.db.upsert_config(guild_config)
                noti_channel = guild_config.system_channel
                if (
                        noti_channel is not None and noti_channel.permissions_for(entry.guild.me).send_messages and
                        noti_channel.permissions_for(entry.guild.me).embed_links and
                        noti_channel.permissions_for(entry.guild.me).attach_files
                ):
                    await noti_channel.send(
                        embed=discord.Embed(title="Warning",
                                            description="The default ping role was deleted.\nPlease use "
                                                        "`/settings` to set a new default ping role.",
                                            color=discord.Colour.red()).set_footer(
                            text=self.bot.user.display_name, icon_url=self.bot.user.avatar.url
                        )
                    )
            await self.bot.db.delete_role_from_db(role_id=entry.target.id)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        logs_channel: discord.TextChannel = self.bot.get_channel(self.bot.log_channel_id)
        if logs_channel is not None:
            await logs_channel.send(
                embed=discord.Embed(
                    title="Joined Guild",
                    description=f"Joined guild {guild.name} ({guild.id})\nWe're at {len(self.bot.guilds)} guilds now!",
                    color=discord.Colour.green()
                ).set_footer(
                    text=self.bot.user.display_name, icon_url=self.bot.user.avatar.url
                )
            )

        guild_config: GuildSettings = await self.bot.db.get_guild_config(guild.id)
        if not guild_config:
            return

        if guild_config.notifications_channel is None:
            await self.bot.db.delete_config(guild.id)
            return


async def setup(bot: MangaClient) -> None:
    await bot.add_cog(EventListenerCog(bot))
