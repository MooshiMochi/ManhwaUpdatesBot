from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

import aiofiles
from aiohttp import ClientResponseError

if TYPE_CHECKING:
    from src.core.bot import MangaClient

import traceback as tb
from datetime import timedelta

import discord
from discord import InteractionResponded, app_commands

from src.static import Emotes

from src.core.errors import *

IS_PATREON = True


class BotCommandTree(discord.app_commands.CommandTree):
    def __init__(self, client: MangaClient):
        self.bot: MangaClient = client
        super().__init__(client)

    @staticmethod
    async def _respond_with_check(
            interaction: discord.Interaction, embed: discord.Embed, ephemeral: bool = True, **kwargs
    ) -> None:
        try:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral, **kwargs)  # noqa
        except (InteractionResponded, discord.errors.HTTPException):
            await interaction.followup.send(embed=embed, **kwargs)

    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        """
        The global check for application commands.
        """
        commands_to_check = ["subscribe", "track"]
        # If it's DM channel and they're not patreon -> Can't use -> alert about patreon

        if not interaction.guild_id:
            if not IS_PATREON:
                em = discord.Embed(
                    title="Error",
                    description=(
                        "This command can only be used in a server.\n"
                        "You can unlock this feature by becoming a Patreon supporter.\nUser `/help` for patreon link."
                    ),
                    color=0xFF0000,
                )
                em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
                await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
                return False
            await self.bot.log_command_usage(interaction)
            return True

        if (not interaction.guild.me.guild_permissions.send_messages
                and not interaction.guild.me.guild_permissions.embed_links):
            self.bot.logger.error("I don't have permission to send messages or embed links.")
            return False

        if (str(interaction.command.qualified_name).split(" ")[0]
                not in commands_to_check):
            await self.bot.log_command_usage(interaction)
            return True

        if await self.bot.db.get_guild_config(interaction.guild_id) is None:
            if interaction.command.qualified_name == "subscribe list":
                try:
                    if interaction.namespace["global"]:
                        await self.bot.log_command_usage(interaction)
                        return True
                except KeyError:
                    pass
            raise GuildNotConfiguredError(interaction.guild_id)
        await self.bot.log_command_usage(interaction)
        return True

    async def on_error(
            self,
            interaction: discord.Interaction,
            error: discord.app_commands.AppCommandError,
            *args,
            **kwargs,
    ) -> None:

        ignore_args = (app_commands.CheckFailure, app_commands.CommandNotFound)
        send_kwargs = {}

        if isinstance(error, app_commands.errors.MissingRole):
            embed = discord.Embed(
                title=f"{Emotes.warning} Hey, you can't do that!",
                color=0xFF0000,
                description=f"Sorry, you need to have the role <@&{error.missing_role}> to execute that command.",
            )

        elif isinstance(error, PremiumFeatureOnly):
            embed = discord.Embed(
                title=f"{Emotes.warning} Premium feature!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, MangaNotFoundError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Manga not found!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, ClientResponseError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Error while contacting website!",
                color=0xFF0000,
                description=f"Received: `Status: {error.status} > Message: {error.message}`\n"
                            f"Visited URL: {error.request_info.url}\n\n**Please try again later!**",
            )

        elif isinstance(error, MangaNotTrackedError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Manga not tracked!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, MangaNotSubscribedError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Not subscribed!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, UnsupportedScanlatorURLFormatError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Incorrect URL format!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, GuildNotConfiguredError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Guild not configured!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, CustomError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Error!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, DatabaseError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Database error!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, MangaCompletedOrDropped):
            embed = discord.Embed(
                title=f"{Emotes.warning} Manga already completed or dropped!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, BookmarkNotFoundError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Bookmark not found!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, URLAccessFailed):
            embed = discord.Embed(
                title=f"{Emotes.warning} Failed to access URL!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, ChapterNotFoundError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Chapter not found!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, RateLimitExceeded):
            embed = discord.Embed(
                title=f"{Emotes.warning} Rate limit exceeded!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, MissingUserAgentError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Missing user agent!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, app_commands.errors.MissingAnyRole):
            embed = discord.Embed(
                title=f"{Emotes.warning} Hey, you can't do that!",
                color=0xFF0000,
                description="Sorry, you need to have one of the following roles: "
                            + f"<@&{'>, <@&'.join(error.missing_roles)}> to execute that command.",
            )

        elif isinstance(error, app_commands.errors.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)  # noqa
            if "send_messages" in perms:
                return
            embed = discord.Embed(
                title=f"{Emotes.warning} I can't do that.",
                color=0xFF0000,
                description=f"Sorry, I require the permission(s) `{perms}` to "
                            + "execute that command. Please contact a server "
                            + "administrator to fix this issue.",
            )

        elif isinstance(error, app_commands.errors.CommandOnCooldown):
            tdl_obj = timedelta(seconds=error.retry_after)
            time_as_string: str = (
                tdl_obj.strftime("`%M min and %S sec`")  # noqa
                if tdl_obj.seconds >= 60
                else f"`{tdl_obj.seconds} sec`"
            )
            text = f"**⏱️ | {interaction.author.name}**! Try again in {time_as_string}!"
            embed = discord.Embed(
                title="⏱️ Command on cooldown", color=0xFF0000, description=text
            )

        elif isinstance(error, app_commands.errors.MissingPermissions):
            if isinstance(error.missing_permissions, str):
                perms = error.missing_permissions.replace("_", " ").title()
            else:
                perms = ", ".join(
                    [
                        str(x).replace("_", " ").title()
                        for x in error.missing_permissions
                    ]
                )
            if len(error.missing_permissions) == 1:
                embed = discord.Embed(
                    title=f"{Emotes.warning} Hey, you can't do that!",
                    color=0xFF0000,
                    description=f"Sorry, you need the `{perms}` permission to execute this command.",
                )
            else:
                embed = discord.Embed(
                    title=f"{Emotes.warning} Hey, you can't do that!",
                    color=0xFF0000,
                    description=f"Sorry, you need the `{perms}` permissions to execute this command.",
                )


        elif isinstance(error, ignore_args):
            self.bot.logger.warning(f"Ignoring exception: {error}")
            return

        else:
            embed = discord.Embed(
                title=f"{Emotes.warning} An unknown error occurred!",
                color=0xFF0000,
                description=f"{error}",
            )
            traceback = "".join(
                tb.format_exception(type(error), error, error.__traceback__)
            )

            buffer = BytesIO(traceback.encode("utf-8"))
            file = discord.File(buffer, filename="error.py")
            send_kwargs["file"] = file

            self.bot.logger.error(
                f"{Emotes.warning} An unhandled error has occurred: {str(error)} - More details can be found in "
                f"logs/error.log"
            )
            async with aiofiles.open(
                    "logs/error.log", "a", encoding="utf-8"
            ) as logfile:
                await logfile.write(f"{tb.format_exc()}\n\n{error}")

        await self._respond_with_check(interaction, embed, **send_kwargs)
