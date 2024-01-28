from __future__ import annotations

import traceback
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING

import aiofiles

from src.static import Emotes

if TYPE_CHECKING:
    from src.core import MangaClient

from src.core.errors import PremiumFeatureOnly
import discord
from discord.ext import commands


class TxtCommandErrorHandler(commands.Cog):
    def __init__(self, bot: MangaClient):
        self.bot: MangaClient = bot

    def cog_load(self) -> None:
        self.bot.logger.info("Loaded TxtCommandErrorHandler Cog...")

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error):
        # This prevents any commands with local handlers being handled here in on_command_error.
        if hasattr(ctx.command, 'on_error'):
            return

        # This prevents any cogs with an overwritten cog_command_error being handled here.
        # cog = ctx.cog
        # if cog:
        #     if cog._get_overridden_method(cog.cog_command_error) is not None:
        #         return

        error = getattr(error, "original", error)

        ignore_types: tuple = ()
        if (isinstance(error, (discord.NotFound, discord.errors.NotFound)) or
                isinstance(error, (discord.Forbidden, discord.errors.Forbidden))):
            # probably because a message got deleted, so we'll ignore it.
            return ctx.command.reset_cooldown(ctx)

        elif isinstance(error, PremiumFeatureOnly):
            embed = discord.Embed(
                title=f"{Emotes.warning} Premium feature!",
                color=0xFF0000,
                description=error.error_msg,
            )

        elif isinstance(error, commands.MaxConcurrencyReached):
            d = {
                commands.BucketType.default: "globally",
                commands.BucketType.user: "per user",
                commands.BucketType.guild: "per guild",
                commands.BucketType.channel: "per channel",
                commands.BucketType.member: "per member",
                commands.BucketType.category: "per category",
                commands.BucketType.role: "per role",
            }
            if error.number > 1:
                e = f"{error.number} times"
            else:
                e = f"{error.number} time"
            embed = discord.Embed(
                title="Woah, calm down.",
                description=f"This command can only be used {e} {d[error.per]}.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.MissingRole):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="Hey, you can't do that!",
                description=f"Sorry, you need to have the role <@&{error.missing_role}> "
                            + "to execute that command.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.BadLiteralArgument):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="Hey, you can't do that!",
                description=f"Sorry, argument `{error.param.name}` must be `{'` or `'.join(error.literals)}`",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.MissingAnyRole):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="Hey, you can't do that!",
                description="Sorry, you need to have one of the following roles: "
                            + f"<@&{'>, <@&'.join(error.missing_roles)}> to execute that command.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        # If the bot doesn't have enough permissions
        elif isinstance(error, commands.BotMissingPermissions):
            perms = (
                    "```diff\n- "
                    + "\n- ".join(error.missing_permissions).replace("_", " ").title()
                    + "\n```"
            )
            if "send_messages" in perms:
                return
            ctx.command.reset_cooldown(ctx)
            resp = f"**❗ {self.bot.user.name} lacks some permissions it needs!**"
            resp += perms
            embed = discord.Embed(
                title=f"{Emotes.warning} I can't do that.",
                color=0xFF0000,
                description=resp,
            )
            send_kwargs = {}

        elif isinstance(error, commands.TooManyArguments):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="That's not right.",
                description="That's a lot of arguments. Too many in fact.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        # If a user doesn't provide a required argument
        elif isinstance(error, commands.MissingRequiredArgument):
            param = str(error.param.name).replace("_", " ")
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="That's not right.",
                description=f"Please provide the `{param}` argument.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.BadUnionArgument):
            param = str(error.param.name).replace("_", " ")
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="That's not right.",
                description=f"Invalid `{param}` argument. Please try again.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.BadArgument):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="That's not right.",
                description=f"{error} Please try again.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        # If a user tries to run a restricted command
        elif isinstance(error, commands.NotOwner):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="Hey, you can't do that!",
                description="This command is restricted.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.MemberNotFound):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="That's not right.",
                description="Invalid member. Please try again.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.UserNotFound):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="That's not right.",
                description="Invalid user. Please try again.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.RoleNotFound):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="That's not right.",
                description="Invalid role. Please try again.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.ChannelNotFound):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="That's not right.",
                description="Invalid channel. Please try again.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.CheckFailure):
            ctx.command.reset_cooldown(ctx)
            return

        # If the command is disabled
        elif isinstance(error, commands.DisabledCommand):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="Hey, you can't do that!",
                description="This command is disabled.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        # If the command is on a cooldown
        elif isinstance(error, commands.CommandOnCooldown):
            embed = discord.Embed(
                description=(
                    f"**⏱️ | {ctx.author.name}**! "
                    f"Try again <t:{int(datetime.now().timestamp() + error.retry_after)}:R>!"
                ),
                color=discord.Colour.red(),
            )
            send_kwargs = {"delete_after": 10}

        # If the user provides an argument that has quotes and the bot gets doesn't understand
        elif (
                isinstance(error, commands.InvalidEndOfQuotedStringError)
                or isinstance(error, commands.ExpectedClosingQuoteError)
                or isinstance(error, commands.UnexpectedQuoteError)
        ):
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title="That's not right.",
                description="I don't like quotes, please omit any quotes in the command.",
                color=discord.Colour.red(),
            )
            send_kwargs = {}

        elif isinstance(error, commands.MissingPermissions):
            if isinstance(error.missing_permissions, str):
                perms = error.missing_permissions.replace("_", " ").title()
            else:
                perms = ", ".join(
                    [
                        str(x).replace("_", " ").title()
                        for x in error.missing_permissions
                    ]
                )
            ctx.command.reset_cooldown(ctx)
            if len(error.missing_permissions) == 1:
                embed = discord.Embed(
                    title="Hey, you can't do that!",
                    description=f"Sorry, you need the permission `{perms}` to execute this command.",
                    color=discord.Colour.red(),
                )
            else:
                embed = discord.Embed(
                    title="Hey, you can't do that!",
                    description=f"Sorry, you need the permissions `{perms}` to execute this command.",
                    color=discord.Colour.red(),
                )
            send_kwargs = {}

        elif isinstance(error, ignore_types):
            return

        # If the error is not recognized
        else:
            send_kwargs = {}
            error: Exception
            ctx.command.reset_cooldown(ctx)
            embed = discord.Embed(
                title=f"{Emotes.warning} An unknown error occurred!",
                color=0xFF0000,
                description=f"{error}",
            )
            tb = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
            buffer = BytesIO(tb.encode("utf-8"))
            file = discord.File(buffer, filename="error.py")
            send_kwargs["file"] = file

            self.bot.logger.error(
                f"{Emotes.warning} An unhandled error has occurred: {str(error)} - More details can be found in "
                f"logs/error.log"
            )
            async with aiofiles.open(
                    "logs/error.log", "a", encoding="utf-8"
            ) as logfile:
                await logfile.write(f"{tb}\n\n{error}")

        try:
            await ctx.send(embed=embed, **send_kwargs)
        except discord.HTTPException:
            pass


async def setup(bot: MangaClient):
    await bot.add_cog(TxtCommandErrorHandler(bot))
