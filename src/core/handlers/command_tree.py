from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

import aiofiles

if TYPE_CHECKING:
    from src.core.bot import MangaClient

import traceback as tb
from datetime import timedelta

import discord
from discord import InteractionResponded, app_commands

from src.static import Emotes

from src.core.errors import *


class BotCommandTree(discord.app_commands.CommandTree):
    def __init__(self, client: MangaClient):
        self.client: MangaClient = client
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
        if not interaction.guild:
            return False
        elif (
                not interaction.guild.me.guild_permissions.send_messages
                and not interaction.guild.me.guild_permissions.embed_links
        ):
            self.client.logger.error("I don't have permission to send messages or embed links.")
            return False
        await self.client.log_command_usage(interaction)
        return True

    async def on_error(
            self,
            interaction: discord.Interaction,
            error: discord.app_commands.AppCommandError,
            *args,
            **kwargs,
    ) -> None:
        # self.client._logger.error(
        #     f"{tb.format_exc()}\n{interaction}\n{error}\n{args}\n{kwargs}",
        # )
        # self.client._logger.error(
        #     f"{tb.format_exc()}\n{error}",
        # )

        ignore_args = (app_commands.CheckFailure, app_commands.CommandNotFound)

        # self.client.logger.error(f"New error of type: {type(error)}")
        send_kwargs = {}

        if isinstance(error, app_commands.errors.MissingRole):
            embed = discord.Embed(
                title=f"{Emotes.warning} Hey, you can't do that!",
                color=0xFF0000,
                description=f"Sorry, you need to have the role <@&{error.missing_role}> to execute that command.",
            )

        elif isinstance(error, MangaNotFoundError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Manga not found!",
                color=0xFF0000,
                description=error.error_msg,
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

        elif isinstance(error, CustomError):
            embed = discord.Embed(
                title=f"{Emotes.warning} Error!",
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
            self.client.logger.warning(f"Ignoring exception: {error}")
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

            self.client.logger.error(
                f"{Emotes.warning} An unhandled error has occurred: {str(error)} - More details can be found in "
                f"logs/error.log"
            )
            async with aiofiles.open(
                    "logs/error.log", "a", encoding="utf-8"
            ) as logfile:
                await logfile.write(f"{tb.format_exc()}\n\n{error}")

        await self._respond_with_check(interaction, embed, **send_kwargs)
