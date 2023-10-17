from __future__ import annotations

import inspect
from functools import partial
from typing import Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core import MangaClient

import asyncio
import io
import os
import subprocess
import sys
import textwrap
import traceback as tb
from contextlib import redirect_stdout

import discord
from discord import app_commands
from discord.ext import commands

from src.core.objects import TextPageSource, GuildSettings
from src.ui.views import ConfirmView, PaginatorView
from src.core.scanlators import scanlators


class Restricted(commands.Cog):
    def __init__(self, client: MangaClient) -> None:
        self.client: MangaClient = client
        self.bot: MangaClient = self.client
        self._last_result = None

    @staticmethod
    def _url(_id, *, animated: bool = False):
        """Convert an emote ID to the image URL for that emote."""  # noqa
        return str(discord.PartialEmoji(animated=animated, name="", id=_id).url)

    async def cog_load(self):
        self.client.logger.info("Loaded Restricted Cog...")

    async def grab_emoji(self, url: str):
        async with self.client.session.get(url) as r:
            result = await r.read()
        return result

    async def run_process(self, command):
        try:
            process = await asyncio.create_subprocess_shell(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            result = await process.communicate()
        except NotImplementedError:
            process = subprocess.Popen(
                command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            result = await self.client.loop.run_in_executor(None, process.communicate)

        return [output.decode() for output in result]

    @staticmethod
    async def restart_bot(message_url: str = None):
        with open("logs/restart.txt", "w") as f:
            f.write(message_url)

        if os.name == "nt":
            python = sys.executable
            sys_args = sys.argv
            os.execl(python, python, *sys_args)
        else:
            os.system("pm2 restart manga-bot")

    @staticmethod
    def cleanup_code(content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith("```") and content.endswith("```"):
            return "\n".join(content.split("\n")[1:-1])

        # remove `foo`
        return content.strip("` \n")

    @commands.group(help="Developer tools.", brief="Dev tools.", aliases=["d", "dev"], case_insensitive=True)
    @commands.is_owner()
    async def developer(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Hmmm...",  # noqa
                description=f"You seem lost. Try to use / for more commands.",
                color=0xFF0000,
            )
            await ctx.send(embed=embed)

    @developer.command(
        name="restart",
        help="Restart the bot.",
        brief="Restart the bot.",
    )
    @commands.is_owner()
    async def developer_restart(self, ctx: commands.Context):
        msg = await ctx.send(
            embed=discord.Embed(
                description=f"⚠️ `Restarting the bot.`",
                color=discord.Color.dark_theme(),
            )
        )
        await self.restart_bot(msg.jump_url)

    @developer.command()
    @commands.guild_only()
    @commands.is_owner()
    async def sync(self, ctx: commands.Context, guilds: commands.Greedy[discord.Object],
                   spec: Optional[Literal["~", "*", "^", "^^"]] = None) -> None:
        """
        Summary:
            Syncs the tree to the current guild or all guilds.

        Args:
            ctx: commands.Context - The context of the command.
            guilds: commands.Greedy[discord.Object] - The guilds to sync to.
            spec: Optional[Literal["~", "*", "^"]] - The specification of the sync.
                "~" - Sync to the current guild.
                "*" - Copy the global tree to the current guild.
                "^" - Clear the commands in the current guild.
                "^^" - Clear the commands in all guilds.
                "None" - Sync to all guilds.

        Returns:
            None
        """
        if not guilds:
            if spec == "~":
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == "*":
                ctx.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == "^":
                ctx.bot.tree.clear_commands(guild=ctx.guild)
                await ctx.bot.tree.sync(guild=ctx.guild)
                synced = []
            elif spec == "^^":
                ctx.bot.tree.clear_commands(guild=None)
                await ctx.bot.tree.sync()
                synced = []
            else:
                synced = await ctx.bot.tree.sync()

            await ctx.send(
                f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}"
            )
            return

        ret = 0
        for guild in guilds:
            try:
                await ctx.bot.tree.sync(guild=guild)
            except discord.HTTPException:
                pass
            else:
                ret += 1

        await ctx.send(f"Synced the tree to {ret}/{len(guilds)}.")

    @developer.command(
        name="pull",
        help="Pull from GitHub and reload cogs.",
        brief="Pull from GitHub and reload cogs.",
    )
    @commands.is_owner()
    async def dev_pull(self, ctx: commands.Context):
        out = subprocess.check_output("git pull", shell=True)
        embed = discord.Embed(
            title="git pull",
            description=f"```py\n{out.decode('utf8')}\n```",
            color=0x00FF00,
        )
        await ctx.send(embed=embed)

        if out.decode("utf8").strip() == "Already up to date.":
            return

        for ext_name, ext in dict(self.client.extensions).copy().items():
            try:
                await self.client.reload_extension(ext_name)
            except (commands.ExtensionNotLoaded, commands.ExtensionAlreadyLoaded, commands.ExtensionNotFound):
                pass

        self.client.logger.info("Synced local code with GitHub repo.")

    @developer.command(
        name="loaded_cogs",
        help="List loaded cogs.",
        brief="List loaded cogs.",
        aliases=["lc"],
    )
    @commands.is_owner()
    async def developer_loaded_cogs(self, ctx):
        embed = discord.Embed(
            title="Loaded cogs",
            description="```diff\n- " + "\n- ".join(self.client.cogs) + "\n```",
            color=discord.Color.red(),
        )
        await ctx.send(embed=embed)

    @developer.command(
        name="shell",
        help="Run something in shell.",
        brief="Run something in shell.",
        aliases=["sh"],
    )
    @commands.is_owner()
    async def developer_shell(self, ctx, *, command):
        async with ctx.typing():
            stdout, stderr = await self.run_process(command)

        if stderr:
            await ctx.message.add_reaction("❌")
            text = f"stdout:\n{stdout}\nstderr:\n{stderr}"
        else:
            await ctx.message.add_reaction("✅")
            text = stdout

        pages = TextPageSource(text).getPages()
        view = PaginatorView(pages, ctx)
        view.message = await ctx.send(pages[0], view=view)

    @developer.command(
        name="get_emoji",
        help="Re-posses an emoji from a different server.",
        brief="Re-posses an emoji from a different server.",
        aliases=["gib", "get"],
    )
    @commands.is_owner()
    @commands.guild_only()
    async def gib(self, ctx, *emojis: discord.PartialEmoji):
        new_emojis = []
        for emoji in emojis:
            if not isinstance(emoji, discord.PartialEmoji):
                self.bot.logger.warning(f"Emoji {emoji} is not a partial emoji.")
                continue
            url = self._url(_id=emoji.id, animated=emoji.animated)
            result = await self.grab_emoji(url)
            try:
                new_emoji = await ctx.guild.create_custom_emoji(
                    name=f"{emoji.name}", image=bytes(result)
                )
            except Exception as e:
                await ctx.send("".join(tb.format_exception(type(e), e, e.__traceback__))[-2000:])
                continue
            new_emojis.append(new_emoji)
        if new_emojis:
            await ctx.send(
                f"{' | '.join([str(emoji) for emoji in new_emojis])}"
            )
        else:
            await ctx.send("No emojis were created.")

    @developer.command(
        name="source",
        help="Get the source code of a command.",
        brief="Get the source code of a command.",
    )
    @commands.is_owner()
    @commands.bot_has_permissions(embed_links=True)
    async def _bot_source(self, ctx: commands.Context, *, command: str):
        """Get the source code of a command."""
        obj = self.client.get_command(command.replace(".", " "))

        if obj is None:
            return await ctx.send("Could not find command.")

        src = obj.callback.__code__
        lines, firstlineno = inspect.getsourcelines(src)  # noqa
        if not lines:
            return await ctx.send("Could not find source.")

        source = "".join(lines)

        if len(source) > 2000:
            await ctx.send(
                file=discord.File(io.BytesIO(source.encode()), filename=f"{command}.py")
            )

        else:
            source = source.replace("```", "`\u200b`\u200b`")

            await ctx.send(f"```py\n{source}\n```")

    @developer.command(
        name="load",
        help="Load a cog.",
        brief="Load a cog.",
    )
    @commands.is_owner()
    async def dev_load_cog(self, ctx, *, cog_name: str) -> None:

        filename = cog_name.lower()
        if filename.endswith(".py"):
            filename = filename[:-3]

        # if f"cogs.{filename}" not in const.extensions:
        #     text = "\n- ".join(map(lambda x: x.replace("cogs.", ""), const.extensions))
        #     return await ctx.send(
        #         embed=discord.Embed(
        #             description=f"```diff\n- {text}\n```",
        #             color=0xFF0000,
        #             title="Available cogs",
        #         )
        #     )

        try:
            await self.client.load_extension(f"{filename}")
            return await ctx.send(f"```diff\n-<[ Extension {filename!r} loaded. ]>-```")
        except commands.errors.ExtensionNotFound:
            await ctx.send(f"```diff\n- Extension {filename!r} not found.```")
        except commands.errors.ExtensionAlreadyLoaded:
            await ctx.send(f"```diff\n- Extension {filename!r} already loaded.```")

    @developer.command(
        name="unload",
        help="Unload a cog.",
        brief="Unload a cog.",
    )
    @commands.is_owner()
    async def dev_unload_cog(self, ctx, *, cog_name: str) -> None:

        filename = cog_name.lower()
        if filename.endswith(".py"):
            filename = filename[:-3]

        all_loaded_cog_paths = [
            all_loaded_cogs.__module__ for all_loaded_cogs in self.client.cogs.values()
        ]

        if (
                f"{filename}" not in all_loaded_cog_paths
                and filename not in all_loaded_cog_paths
        ):
            text = "\n- ".join(all_loaded_cog_paths).replace("cogs.", "")
            return await ctx.send(
                embed=discord.Embed(
                    description=f"```diff\n- {text}\n```",
                    color=0xFF0000,
                    title="Available cogs",
                )
            )
        try:
            await self.client.unload_extension(f"{filename}")
            return await ctx.send(
                f"```diff\n-<[ Extension {filename!r} unloaded. ]>-```"
            )
        except commands.errors.ExtensionNotLoaded:
            await ctx.send(f"```diff\n- Extension {filename!r} is not loaded.\n```")

    @developer.command(
        name="reload",
        help="Reload a cog.",
        brief="Reload a cog.",
    )
    @commands.is_owner()
    async def dev_reload_cog(self, ctx, *, cog_name: str) -> None:

        filename = cog_name.lower()
        if filename.endswith(".py"):
            filename = filename[:-3]

        all_loaded_cog_paths = [
            all_loaded_cogs.__module__ for all_loaded_cogs in self.client.cogs.values()
        ]

        if filename.startswith("cogs."):
            filename = filename.replace("cogs.", "")

        if (
                f"{filename}" not in all_loaded_cog_paths
                and filename not in all_loaded_cog_paths
        ):
            text = "\n- ".join(
                map(lambda x: x.replace("cogs.", ""), all_loaded_cog_paths)
            )
            return await ctx.send(
                embed=discord.Embed(
                    description=f"```diff\n- {text}\n```",
                    color=0xFF0000,
                    title="Available cogs",
                )
            )
        try:
            await self.client.reload_extension(f"{filename}")
            return await ctx.send(
                f"```diff\n-<[ Extension {filename!r} reloaded. ]>-\n```"
            )
        except commands.errors.ExtensionNotLoaded:
            await ctx.send(f"```diff\n- Extension {filename!r} is not loaded.\n```")
        except commands.errors.ExtensionNotFound:
            await ctx.send(f"```diff\n- Extension {filename!r} not found.\n```")
        except commands.errors.ExtensionFailed as e:
            raise e

    @developer.command(
        name="eval",
        help="Run something in python shell.",
        brief="Run something in python shell.",
    )
    @commands.is_owner()
    async def dev_eval(self, ctx, *, code: str):
        env = {
            "discord": discord,
            "client": self.client,
            "bot": self.bot,
            "ctx": ctx,
            "channel": ctx.channel,
            "author": ctx.author,
            "guild": ctx.guild,
            "message": ctx.message,
            "self": self,
            "scanlators": scanlators,
            "_": self._last_result,
        }

        env.update(globals())

        code = self.cleanup_code(code)
        stdout = io.StringIO()

        to_compile = f'async def func():\n{textwrap.indent(code, "    ")}'

        try:
            exec(to_compile, env)
        except Exception as e:
            pages = TextPageSource(
                str(e.__class__.__name__) + ": " + str(e), code_block=True
            ).getPages()
            if len(pages) == 1:
                await ctx.send(pages[0][:-8].strip())
            else:
                view = PaginatorView(pages, ctx)
                view.message = await ctx.send(pages[0], view=view)
            return

        else:
            func = env["func"]

            try:
                with redirect_stdout(stdout):
                    ret = await func()
            except Exception as e:
                value = stdout.getvalue()
                pages = TextPageSource(
                    value
                    + str("".join(tb.format_exception(e, e, e.__traceback__))),  # type: ignore
                    code_block=True,
                ).getPages()
                if len(pages) == 1:
                    await ctx.send(pages[0][:-8].strip())
                else:
                    view = PaginatorView(pages, ctx)
                    view.message = await ctx.send(pages[0], view=view)
            else:
                value = stdout.getvalue()

                if ret is None and value != "":
                    pages = TextPageSource(value, code_block=True).getPages()
                    if len(pages) == 1:
                        await ctx.send(pages[0][:-8].strip())
                    else:
                        view = PaginatorView(pages, ctx)
                        view.message = await ctx.send(pages[0], view=view)
                    return
                else:
                    self._last_result = ret
                    if value != "" or ret != "":
                        pages = TextPageSource(
                            value + str(ret), code_block=True
                        ).getPages()
                        if len(pages) == 1:
                            await ctx.send(pages[0][:-8].strip())
                        else:
                            view = PaginatorView(pages, ctx)
                            view.message = await ctx.send(pages[0], view=view)

    @developer.command(
        name="logs",
        help="View/Clear the error.log file.",
        brief="View/Clear the error.log file.",
    )
    @commands.is_owner()
    async def logs_clear(
            self, ctx: commands.Context, *, action: Literal["clear", "view"] = "view"
    ) -> Optional[discord.Message]:
        action = action.lower()
        log_file = "logs/error.log"
        assert os.path.exists("logs"), "logs folder does not exist."
        assert os.path.exists(log_file), "error.log file does not exist."

        if action == "clear":
            with open(log_file, "w") as f:
                f.write("")
            return await ctx.send("```diff\n-<[ Logs cleared. ]>-```")

        with open(log_file, "r") as f:
            lines = f.readlines()

        if not lines:
            return await ctx.send("```diff\n-<[ No logs. ]>-```")

        pages = TextPageSource(
            "".join(lines).replace(self.client.config["token"], "[TOKEN]"),
            code_block=True,
        ).getPages()

        view = PaginatorView(pages, ctx)
        view.message = await ctx.send(view.iter_items[0], view=view)

    @developer.command(
        name="export_db",
        help="Export the database to an Excel file.",
        brief="Export the database to an Excel file.",
    )
    async def _export_db(self, ctx: commands.Context, raw: bool = False) -> None:
        await ctx.send("```diff\n-<[ Exporting database. ]>-```")
        export_func = partial(self.client.db.export, raw=raw)
        io_buffer: io.BytesIO = await self.client.loop.run_in_executor(None, export_func)
        filename = "manga_db_raw.db" if raw else "manga_db.xlsx"
        await ctx.send(
            file=discord.File(io_buffer, filename=filename)
        )

    @developer.command(
        name="import_db",
        help="Import the database from an Excel file.",
        brief="Import the database from an Excel file.",
    )
    async def _import_db(self, ctx: commands.Context) -> None:
        await ctx.send("```diff\n-<[ Importing database. ]>-```")
        file_content = await ctx.message.attachments[0].read()
        buffer_file = io.BytesIO(file_content)
        buffer_file.seek(0)
        await self.client.loop.run_in_executor(None, self.client.db.import_data, buffer_file)
        await ctx.send("```diff\n-<[ Database imported. ]>-```")

    @developer.command(
        name="sql",
        help="Execute SQL queries.",
        brief="Execute SQL queries.",
    )
    async def _sql(self, ctx: commands.Context, *, query_n_args: str) -> None:
        query_n_args = query_n_args.split(", ", 1)
        if len(query_n_args) > 1:
            query, args = query_n_args
        else:
            query = query_n_args[0]
            args = None
        if query.startswith("\"") and query.endswith("\""):
            query = query[1:-1]
        args = args.split(", ") if args else []
        try:
            result = await self.bot.db.execute(query, *args)
        except Exception as e:
            traceback = "".join(
                tb.format_exception(type(e), e, e.__traceback__)
            )
            await ctx.send(f"```diff\n-<[ {traceback} ]>-```".strip()[-2000:])
            return
        if result:
            msg = f"{result}"
            if len(msg) > 2000:
                pages = TextPageSource(msg, code_block=True).getPages()
                view = PaginatorView(pages, ctx)
                view.message = await ctx.send(pages[0], view=view)
            else:
                await ctx.send(f"```diff\n-<[ {result} ]>-```")
            return
        await ctx.send("```diff\n-<[ Query executed. ]>-```")

    @developer.command(
        name="toggle_scanlator",
        help="Enable or disable a scanlator class.",
        brief="Enable or disable a scanlator class.",
        aliases=["tscan"]
    )
    async def toggle_scanlator(self, ctx: commands.Context, *, scanlator: str):
        scanlator = scanlator.lower()
        if scanlator != "all":
            # noinspection PyProtectedMember
            if scanlator not in self.bot._all_scanners:
                em = discord.Embed(
                    title="Scanlator not found.",
                    description=f"Scanlator `{scanlator}` not found.",
                    color=discord.Color.red()
                )
                em.description += "\n\nAvailable scanlators:\n```diff\n"
                # noinspection PyProtectedMember
                em.description += "+ " + " +\n+ ".join(self.bot._all_scanners) + " +" + "\n```"
                await ctx.send(embed=em)
                return
        if scanlator == "all":
            # noinspection PyProtectedMember
            _looping_item = self.bot._all_scanners.keys()
        else:
            _looping_item = [scanlator]
        results = []
        for scanlator in _looping_item:
            new_status = await self.bot.db.toggle_scanlator(scanlator)
            if new_status:  # enabled
                # noinspection PyProtectedMember
                scanlators[scanlator] = self.bot._all_scanners[scanlator]
            else:
                scanlators.pop(scanlator, None)
            if new_status:
                scanlator_str = f"+<[ {scanlator:^15} ]>+\n"
            else:
                scanlator_str = f"-<[ {scanlator:^15} ]>-\n"
            results.append(scanlator_str)
        result_str = ''.join(results)
        await ctx.send(
            embed=discord.Embed(
                title=f"Toggled {len(results)} scanlators", description=f"```diff\n{result_str}```"
            )
        )
        # await ctx.send(
        #     f"```diff\n-<[ {scanlator} is now {'enabled' if new_status else 'disabled'} ]>-```")

    @developer.command(
        name="disabled_scanlators",
        help="List all disabled scanlators.",
        brief="List all disabled scanlators.",
        aliases=["dscan"]
    )
    async def disabled_scanlators(self, ctx: commands.Context):
        em = discord.Embed(
            title="Disabled scanlators.",
            description="List of all disabled scanlators.",
            color=discord.Color.red()
        )
        em.description += "\n\n```diff\n"
        disabled_scanlators = await self.bot.db.get_disabled_scanlators()
        if disabled_scanlators:
            em.description += "- " + " -\n- ".join(disabled_scanlators) + " -" + "\n```"
        else:
            em.description += "+ None +\n```"
        await ctx.send(embed=em)

    @developer.command(
        name="g_update",
        help="Send a global update.",
        brief="Send a global update.",
    )
    async def g_update(self, ctx: commands.Context, *, message: str):
        bottom_text = (
            "\n\n*If you have any questions, please join the [Support Server]("
            "https://discord.gg/TYkw8VBZkr) and ping `.mooshi`.*"
        )
        message += bottom_text
        em = discord.Embed(
            title="⚠️ Important Update ⚠️",
            description=message,
            color=discord.Color.red()
        )
        em.set_footer(text="This is a global update sent by Mooshi.")

        guild_configs = await self.bot.db.get_many_guild_config([x.id for x in self.bot.guilds])
        if not guild_configs:
            await ctx.send(embed=discord.Embed(
                title="⚠️ No guilds found!",
                description="No guilds have been found in the database.",
                color=discord.Color.red()
            ))
            return

        guild_configs_to_notify: list[GuildSettings] = []
        # ensure that the channel in each guild config exists
        for guild_config in guild_configs:
            if not guild_config.notifications_channel:
                continue
            bot_channel_perms = guild_config.notifications_channel.permissions_for(
                guild_config.notifications_channel.guild.me
            )
            if bot_channel_perms.send_messages and bot_channel_perms.embed_links:
                guild_configs_to_notify.append(guild_config)

        if not guild_configs_to_notify:
            await ctx.send(embed=discord.Embed(
                title="⚠️ Can't sent messages!",
                description="There are no guilds for which the bot has perms to send messages.",
                color=discord.Color.red()
            ))
            return

        view = ConfirmView(self.bot, ctx)
        view.message = await ctx.send(
            f"Are you sure you want to send this message to {len(guild_configs_to_notify)} guilds?", embed=em, view=view
        )
        await view.wait()
        if view.value is None:  # timed out
            return
        elif view.value is False:  # cancelled = False
            await view.message.edit(embed=discord.Embed(
                title="Cancelled!",
                description="The message has been cancelled.",
                color=discord.Color.red()
            ), view=None)
            return

        await view.message.edit(embed=discord.Embed(
            title="Sending...",
            description=f"Sending the message to {len(guild_configs_to_notify)} guilds...",
        ), view=None)

        successes = 0
        for guild_config in guild_configs_to_notify:
            if guild_config.default_ping_role and guild_config.dev_notifications_ping:
                role_mention = guild_config.default_ping_role.mention
                if guild_config.default_ping_role.id == guild_config.notifications_channel.guild.id:
                    role_mention = "@everyone"
            else:
                role_mention = None

            try:
                await guild_config.notifications_channel.send(
                    f"||{role_mention}||" if role_mention is not None else None,
                    embed=em,
                    allowed_mentions=discord.AllowedMentions(roles=True)
                )
                successes += 1
            except discord.HTTPException:
                pass

        await view.message.edit(embed=discord.Embed(
            title="Sent!",
            description=f"Sent the message to {successes} guilds.",
            color=discord.Color.green()
        ))

    @app_commands.command(name="add_website", description="[DEV] Add a website to the bot.")
    async def _add_website(self, interaction: discord.Interaction):
        return await interaction.response.send_message("This command is not yet supported!", ephemeral=True)  # noqa


async def setup(bot: MangaClient) -> None:
    await bot.add_cog(Restricted(bot))
