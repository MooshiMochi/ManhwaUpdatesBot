from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from core.bot import MangaClient

import asyncio
import io
import os
import subprocess
import sys
import textwrap
import traceback
from contextlib import redirect_stdout

import discord
from discord import Object
from discord.ext import commands

from src.objects import PaginatorView, TextPageSource


class Restricted(commands.Cog):
    def __init__(self, client: MangaClient) -> None:
        self.client: MangaClient = client
        self._last_result = None

    @staticmethod
    def _url(_id, *, animated: bool = False):
        """Convert an emote ID to the image URL for that emote."""
        return str(discord.PartialEmoji(animated=animated, name="", id=_id).url)

    async def cog_load(self):
        self.client._logger.info("Loaded Restricted Cog...")

    async def grab_emoji(self, url: str):
        async with self.client._session.get(url) as r:
            empty_bytes = b""
            result = empty_bytes

            while True:
                chunk = await r.content.read(100)
                if chunk == empty_bytes:
                    break
                result += chunk
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

    async def restart_bot(self, message_url: str = None):
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

    @commands.group(help="Developer tools.", brief="Dev tools.", aliases=["d", "dev"])
    @commands.is_owner()
    async def developer(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Hmmm...",
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

    @developer.command(name="synctree", aliases=["sync_tree"])
    async def tree_sync(
        self,
        ctx: commands.Context,
        guilds: commands.Greedy[Object],
        spec: Optional[Literal["~"]] = None,
    ) -> None:
        """
        Usage:
        '!d sync' | Synchronizes all guilds
        '!d sync ~' | Synchronizes current guild
        '!d sync id_1 id_2' | Synchronizes specified guilds by id
        """
        if not guilds:
            if spec == "~":
                fmt = await ctx.bot.tree.sync(guild=ctx.guild)
            else:
                fmt = await ctx.bot.tree.sync()

            await ctx.send(
                f"Synced {len(fmt)} commands {'globally' if spec is None else 'to the current guild.'}"
            )
            return

        fmt = 0
        for guild in guilds:
            try:
                await ctx.bot.tree.sync(guild=guild)
            except discord.HTTPException:
                pass
            else:
                fmt += 1

        await ctx.send(f"Synced the tree to {fmt}/{len(guilds)} guilds.")

    @developer.command(
        name="sync",
        help="Sync with GitHub and reload cogs.",
        brief="Sync with GitHub and reload cogs.",
    )
    @commands.is_owner()
    async def developer_sync(self, ctx: commands.Context):
        out = subprocess.check_output("git pull", shell=True)
        embed = discord.Embed(
            title="git pull",
            description=f"```py\n{out.decode('utf8')}\n```",
            color=0x00FF00,
        )
        await ctx.send(embed=embed)

        if out.decode("utf8").strip() == "Already up to date.":
            return

        for ext_name, ext in self.client.extensions:
            try:
                await self.client.unload_extension(ext_name)
            except commands.ExtensionNotLoaded:
                pass

        # for dir_name in ["events"]:
        #     for file in os.listdir(dir_name):
        #         if file.endswith(".py"):
        #             await self.client.unload_extension(
        #                 f"{dir_name}.{file}".replace(".py", "")
        #             )
        #             await self.client.load_extension(
        #                 f"{dir_name}.{file}".replace(".py", "")
        #             )

        # skipped = 0
        # for dir_name in ["utils"]:
        #     for file in os.listdir(dir_name):
        #         if file.endswith(".py"):
        #             try:
        #                 await self.client.load_extension(
        #                     f"{dir_name}.{file}".replace(".py", "")
        #                 )
        #             except (
        #                 commands.NoEntryPointError,
        #                 commands.ExtensionAlreadyLoaded,
        #             ) as e:
        #                 self.client.logger.debug(
        #                     f"Extension {dir_name}.{file.replace('.py', '')} not loaded: {e}"
        #                 )
        #                 skipped += 1

        self.client._logger.info("Client reloaded.")

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
    async def gib(self, ctx, emoji: discord.PartialEmoji, emoji2=None):

        url = self._url(_id=emoji.id, animated=emoji.animated)
        result = await self.grab_emoji(url)

        new_emoji = await ctx.guild.create_custom_emoji(
            name=f"{emoji.name}", image=result
        )

        if emoji2:

            url2 = self._url(_id=emoji2.id, animated=emoji2.animated)
            result2 = await self.grab_emoji(url2)

            new_emoji2 = await ctx.guild.create_custom_emoji(
                name=f"{emoji2.name}", image=result2
            )

            return await ctx.send(content=f"{new_emoji} | {new_emoji2}")

        else:
            await ctx.send(new_emoji)
            return

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
        lines, firstlineno = inspect.getsourcelines(src)
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
            text = "\n- ".join(all_loaded_cog_paths.replace("cogs.", ""))
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
            "ctx": ctx,
            "channel": ctx.channel,
            "author": ctx.author,
            "guild": ctx.guild,
            "message": ctx.message,
            "self": self,
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
                    + str("".join(traceback.format_exception(e, e, e.__traceback__))),
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
    ) -> None:
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
            "\n".join(lines).replace(self.client._config["token"], "[TOKEN]"),
            code_block=True,
        ).getPages()

        view = PaginatorView(pages, ctx)
        view.message = await ctx.send(view._iterable[0], view=view)

    @developer.command(
        name="clear_commands",
        help="Clear all commands.",
        brief="Clear all commands.",
    )
    async def clear_commands(
        self,
        ctx: commands.Context,
        spec: Optional[Literal["~"]] = None,
    ) -> None:
        """
        Usage:
        '!d clear_commands' | Clears the commands from all guilds
        '!d clear_commands ~' | Clears the commands in the current guild
        """
        if spec == "~":
            self.client.tree.clear_commands(guild=ctx.guild)
            await ctx.invoke(
                self.client.get_command("developer synctree"), guilds=None, spec="~"
            )
        else:
            for guild in self.client.guilds:
                self.client.tree.clear_commands(guild=guild)
            await ctx.invoke(self.client.get_command("developer synctree"))

        await ctx.send(
            f"Cleared all commands {'globally' if spec is None else 'from the current guild.'}"
        )
        return


async def setup(bot: MangaClient) -> None:
    await bot.add_cog(Restricted(bot))
