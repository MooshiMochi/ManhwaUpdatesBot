"""Dev cog — owner-only prefix-mention operations.

Mirrors v1's ``developer`` group (aliases ``d``, ``dev``). Invoked via
``@bot d <subcommand>`` so it works without the ``message_content`` intent
(Discord forwards full content when the bot is mentioned). DMs to the bot
also work (no mention needed).
"""

from __future__ import annotations

import inspect
import io
import json
import logging
import os
import shutil
import sys
import time
import traceback as tb
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import aiohttp
import discord
from discord.ext import commands

from ..crawler.errors import CrawlerError
from ..dev_helpers import duration_parser, eval_runner, shell_runner, sql_runner
from ..ui.paginator import Paginator

if TYPE_CHECKING:
    from ..bot import ManhwaBot

_log = logging.getLogger(__name__)

_DISCORD_LIMIT = 1900  # safe headroom under the 2000-char message limit
_TABLES_FOR_JSON_EXPORT = (
    "tracked_series",
    "tracked_in_guild",
    "subscriptions",
    "bookmarks",
    "guild_settings",
    "guild_scanlator_channels",
    "dm_settings",
    "consumer_state",
    "premium_grants",
    "patreon_links",
)


class _ConfirmView(discord.ui.View):
    """Simple Confirm/Cancel prompt locked to the invoking user."""

    def __init__(self, invoker_id: int, *, timeout: float = 30.0) -> None:
        super().__init__(timeout=timeout)
        self.invoker_id = invoker_id
        self.result: bool | None = None
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "Only the invoker can answer this prompt.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button[Any]) -> None:
        self.result = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button[Any]) -> None:
        self.result = False
        await interaction.response.defer()
        self.stop()


def _split_text(text: str, *, chunk: int = _DISCORD_LIMIT) -> list[str]:
    if not text:
        return ["(no output)"]
    out: list[str] = []
    for i in range(0, len(text), chunk):
        out.append(text[i : i + chunk])
    return out


def _code_block(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text}\n```"


def _flag(args: list[str], name: str) -> tuple[bool, list[str]]:
    """Return ``(present, remaining)`` after stripping a boolean ``--flag``."""
    present = False
    remaining: list[str] = []
    for a in args:
        if a == f"--{name}":
            present = True
        else:
            remaining.append(a)
    return present, remaining


def _named(args: list[str], name: str) -> tuple[str | None, list[str]]:
    """Return ``(value, remaining)`` after stripping ``--name=value``."""
    needle = f"--{name}="
    value: str | None = None
    remaining: list[str] = []
    for a in args:
        if a.startswith(needle):
            value = a[len(needle) :]
        else:
            remaining.append(a)
    return value, remaining


class DevCog(commands.Cog, name="Dev"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot: ManhwaBot = bot  # type: ignore[assignment]
        self._last_eval: Any = None

    async def cog_check(self, ctx: commands.Context) -> bool:  # type: ignore[override]
        return await self.bot.is_owner(ctx.author)

    # -- parent group ---------------------------------------------------

    @commands.group(
        name="developer",
        aliases=["d", "dev"],
        invoke_without_command=True,
        case_insensitive=True,
    )
    async def developer(self, ctx: commands.Context) -> None:
        await ctx.send("Use `@bot d <subcommand>`. See `@bot d loaded_cogs` or `@bot d help`.")

    # -- restart --------------------------------------------------------

    @developer.command(name="restart")
    async def restart(self, ctx: commands.Context) -> None:
        msg = await ctx.send(
            embed=discord.Embed(
                description="⚠️ `Restarting the bot.`",
                color=discord.Color.dark_theme(),
            )
        )
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "restart.txt").write_text(msg.jump_url, encoding="utf-8")

        if os.name == "nt":
            python = sys.executable
            os.execl(python, python, *sys.argv)
        else:
            try:
                await shell_runner.run(["pm2", "restart", "bot"], timeout=10.0)
            except Exception:
                _log.exception("pm2 restart failed; falling back to sys.exit")
                sys.exit(0)

    # -- sync -----------------------------------------------------------

    @developer.command(name="sync")
    @commands.guild_only()
    async def sync(
        self,
        ctx: commands.Context,
        guilds: commands.Greedy[discord.Object],
        spec: Literal["~", "*", "^", "^^"] | None = None,
    ) -> None:
        if not guilds:
            if spec == "~":
                synced = await self.bot.tree.sync(guild=ctx.guild)
            elif spec == "*":
                self.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await self.bot.tree.sync(guild=ctx.guild)
            elif spec == "^":
                self.bot.tree.clear_commands(guild=ctx.guild)
                await self.bot.tree.sync(guild=ctx.guild)
                synced = []
            elif spec == "^^":
                self.bot.tree.clear_commands(guild=None)
                await self.bot.tree.sync()
                synced = []
            else:
                synced = await self.bot.tree.sync()
            scope = "globally" if spec is None else "to the current guild."
            await ctx.send(f"Synced {len(synced)} commands {scope}")
            return

        ok = 0
        for guild in guilds:
            try:
                await self.bot.tree.sync(guild=guild)
            except discord.HTTPException:
                pass
            else:
                ok += 1
        await ctx.send(f"Synced the tree to {ok}/{len(guilds)}.")

    # -- pull -----------------------------------------------------------

    @developer.command(name="pull")
    async def pull(self, ctx: commands.Context) -> None:
        stdout, stderr, rc = await shell_runner.run(["git", "pull", "--ff-only"], timeout=60.0)
        out = (stdout or stderr).strip() or f"(rc={rc})"
        await ctx.send(
            embed=discord.Embed(
                title="git pull",
                description=_code_block(out, "py"),
                color=discord.Color.green() if rc == 0 else discord.Color.red(),
            )
        )
        if "Already up to date" in stdout:
            return
        for ext_name in list(self.bot.extensions.keys()):
            try:
                await self.bot.reload_extension(ext_name)
            except (
                commands.ExtensionNotLoaded,
                commands.ExtensionAlreadyLoaded,
                commands.ExtensionNotFound,
            ):
                pass

    # -- loaded_cogs ----------------------------------------------------

    @developer.command(name="loaded_cogs", aliases=["lc"])
    async def loaded_cogs(self, ctx: commands.Context) -> None:
        cogs = list(self.bot.cogs.keys())
        body = "\n- ".join(cogs) if cogs else "(none)"
        await ctx.send(
            embed=discord.Embed(
                title="Loaded cogs",
                description=_code_block(f"- {body}", "diff"),
                color=discord.Color.red(),
            )
        )

    # -- shell / sh -----------------------------------------------------

    @developer.command(name="shell", aliases=["sh"])
    async def shell(self, ctx: commands.Context, *, command: str) -> None:
        async with ctx.typing():
            try:
                stdout, stderr, rc = await shell_runner.run(command, timeout=120.0)
            except TimeoutError:
                await ctx.send("⏱️ shell command timed out")
                return
        if stderr:
            try:
                await ctx.message.add_reaction("❌")
            except discord.HTTPException:
                pass
            text = f"stdout:\n{stdout}\nstderr:\n{stderr}\n(rc={rc})"
        else:
            try:
                await ctx.message.add_reaction("✅")
            except discord.HTTPException:
                pass
            text = stdout or f"(rc={rc})"
        await self._send_long_text(ctx, text, lang="bash")

    # -- get_emoji ------------------------------------------------------

    @developer.command(name="get_emoji", aliases=["gib", "get"])
    @commands.guild_only()
    async def get_emoji(self, ctx: commands.Context, *emojis: discord.PartialEmoji) -> None:
        new_emojis: list[discord.Emoji] = []
        async with aiohttp.ClientSession() as session:
            for emoji in emojis:
                if not isinstance(emoji, discord.PartialEmoji) or emoji.id is None:
                    continue
                url = str(
                    discord.PartialEmoji(
                        name=emoji.name or "", animated=emoji.animated, id=emoji.id
                    ).url
                )
                async with session.get(url) as resp:
                    data = await resp.read()
                try:
                    new_emoji = await ctx.guild.create_custom_emoji(  # type: ignore[union-attr]
                        name=emoji.name or "emoji", image=data
                    )
                except discord.HTTPException as exc:
                    await ctx.send(f"failed to create `{emoji.name}`: {exc}")
                    continue
                new_emojis.append(new_emoji)
        if new_emojis:
            await ctx.send(" | ".join(str(e) for e in new_emojis))
        else:
            await ctx.send("No emojis were created.")

    # -- source ---------------------------------------------------------

    @developer.command(name="source")
    async def source(self, ctx: commands.Context, *, command: str) -> None:
        obj = self.bot.get_command(command.replace(".", " "))
        if obj is None:
            await ctx.send("Could not find command.")
            return
        try:
            src = inspect.getsource(obj.callback)
        except OSError, TypeError:
            await ctx.send("Could not load source.")
            return
        if len(src) > _DISCORD_LIMIT:
            await ctx.send(
                file=discord.File(io.BytesIO(src.encode("utf-8")), filename=f"{command}.py")
            )
        else:
            safe = src.replace("```", "`​`​`")
            await ctx.send(_code_block(safe, "py"))

    # -- load / unload / reload ----------------------------------------

    @developer.command(name="load")
    async def load(self, ctx: commands.Context, *, cog_name: str) -> None:
        try:
            await self.bot.load_extension(cog_name)
            await ctx.send(_code_block(f"-<[ Extension {cog_name!r} loaded. ]>-", "diff"))
        except commands.ExtensionNotFound:
            await ctx.send(_code_block(f"- Extension {cog_name!r} not found.", "diff"))
        except commands.ExtensionAlreadyLoaded:
            await ctx.send(_code_block(f"- Extension {cog_name!r} already loaded.", "diff"))
        except commands.ExtensionFailed:
            await ctx.send(_code_block(tb.format_exc()[-1900:], "py"))

    @developer.command(name="unload")
    async def unload(self, ctx: commands.Context, *, cog_name: str) -> None:
        try:
            await self.bot.unload_extension(cog_name)
            await ctx.send(_code_block(f"-<[ Extension {cog_name!r} unloaded. ]>-", "diff"))
        except commands.ExtensionNotLoaded:
            await ctx.send(_code_block(f"- Extension {cog_name!r} not loaded.", "diff"))

    @developer.command(name="reload")
    async def reload(self, ctx: commands.Context, *, cog_name: str) -> None:
        try:
            await self.bot.reload_extension(cog_name)
            await ctx.send(_code_block(f"-<[ Extension {cog_name!r} reloaded. ]>-", "diff"))
        except commands.ExtensionNotLoaded:
            await ctx.send(_code_block(f"- Extension {cog_name!r} not loaded.", "diff"))
        except commands.ExtensionNotFound:
            await ctx.send(_code_block(f"- Extension {cog_name!r} not found.", "diff"))
        except commands.ExtensionFailed:
            await ctx.send(_code_block(tb.format_exc()[-1900:], "py"))

    # -- eval -----------------------------------------------------------

    @developer.command(name="eval")
    async def eval_cmd(self, ctx: commands.Context, *, code: str) -> None:
        env: dict[str, Any] = {
            "discord": discord,
            "bot": self.bot,
            "ctx": ctx,
            "channel": ctx.channel,
            "author": ctx.author,
            "guild": ctx.guild,
            "message": ctx.message,
            "self": self,
            "db": self.bot.db,
            "crawler": self.bot.crawler,
            "premium": self.bot.premium,
            "_": self._last_eval,
        }
        env.update(globals())
        try:
            result, captured = await eval_runner.run(code, env)
        except Exception:
            await self._send_long_text(ctx, tb.format_exc(), lang="py")
            return
        self._last_eval = result
        text = captured
        if result is not None:
            text += repr(result)
        await self._send_long_text(ctx, text or "(no output)", lang="py")

    # -- logs -----------------------------------------------------------

    @developer.command(name="logs")
    async def logs(
        self, ctx: commands.Context, *, action: Literal["clear", "view"] = "view"
    ) -> None:
        log_path = Path("logs") / "error.log"
        if not log_path.exists():
            await ctx.send("No log file at `logs/error.log` (logs may go to stdout).")
            return
        if action == "clear":
            log_path.write_text("", encoding="utf-8")
            await ctx.send(_code_block("-<[ Logs cleared. ]>-", "diff"))
            return
        contents = log_path.read_text(encoding="utf-8", errors="replace")
        if not contents.strip():
            await ctx.send(_code_block("-<[ No logs. ]>-", "diff"))
            return
        await self._send_long_text(ctx, contents, lang="")

    # -- export_db / import_db -----------------------------------------

    @developer.command(name="export_db")
    async def export_db(self, ctx: commands.Context, raw: bool = False) -> None:
        await ctx.send(_code_block("-<[ Exporting database. ]>-", "diff"))
        if raw:
            db_path = Path(self.bot.config.db.path)
            if not db_path.exists():
                await ctx.send("Raw DB file does not exist on disk (in-memory?).")
                return
            await ctx.send(file=discord.File(str(db_path), filename=db_path.name))
            return
        dump: dict[str, list[dict[str, Any]]] = {}
        for table in _TABLES_FOR_JSON_EXPORT:
            try:
                rows = await self.bot.db.fetchall(f"SELECT * FROM {table}")
            except Exception:
                _log.exception("export_db: failed to read %s", table)
                continue
            dump[table] = [dict(r) for r in rows]
        buf = io.BytesIO(json.dumps(dump, indent=2, default=str).encode("utf-8"))
        await ctx.send(file=discord.File(buf, filename="manhwa_bot_db.json"))

    @developer.command(name="import_db")
    async def import_db(self, ctx: commands.Context) -> None:
        if not ctx.message.attachments:
            await ctx.send("Attach a `.sqlite`/`.db` or `.json` file.")
            return
        attachment = ctx.message.attachments[0]
        name = attachment.filename.lower()
        data = await attachment.read()
        if name.endswith((".sqlite", ".db")):
            db_path = Path(self.bot.config.db.path)
            backup = db_path.with_suffix(db_path.suffix + f".bak.{int(time.time())}")
            if db_path.exists():
                shutil.copy2(db_path, backup)
            await self.bot.db.close()
            db_path.write_bytes(data)
            await ctx.send(
                f"Wrote new DB to `{db_path}` (backup `{backup.name}`). "
                "Run `@bot d restart` to reopen the connection."
            )
            return
        if name.endswith(".json"):
            try:
                payload = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                await ctx.send(f"Invalid JSON: {exc}")
                return
            inserted = 0
            for table, rows in payload.items():
                if table not in _TABLES_FOR_JSON_EXPORT or not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict) or not row:
                        continue
                    cols = ",".join(row.keys())
                    placeholders = ",".join(["?"] * len(row))
                    try:
                        await self.bot.db.execute(
                            f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})",
                            tuple(row.values()),
                        )
                        inserted += 1
                    except Exception:
                        _log.exception("import_db: failed to insert into %s", table)
            await ctx.send(_code_block(f"-<[ Imported {inserted} rows. ]>-", "diff"))
            return
        await ctx.send("Unsupported attachment type. Use `.sqlite`/`.db` or `.json`.")

    # -- sql ------------------------------------------------------------

    @developer.command(name="sql")
    async def sql(self, ctx: commands.Context, *, query_n_args: str) -> None:
        query, args = sql_runner.parse(query_n_args)
        if not query:
            await ctx.send("empty query")
            return
        try:
            start = time.perf_counter()
            if query.strip().lower().startswith("select"):
                rows = await self.bot.db.fetchall(query, tuple(args))
                results: list[Any] = [dict(r) for r in rows]
            else:
                cursor = await self.bot.db.execute(query, tuple(args))
                results = [{"rowcount": cursor.rowcount, "lastrowid": cursor.lastrowid}]
            dt_ms = (time.perf_counter() - start) * 1000.0
        except Exception:
            await self._send_long_text(ctx, tb.format_exc(), lang="py")
            return
        if results:
            text = f"# Returned {len(results)} rows in {dt_ms:.2f}ms\n"
            text += json.dumps(results, indent=2, default=str)
            await self._send_long_text(ctx, text, lang="py")
            return
        await ctx.send(_code_block(f"-<[ {dt_ms:.2f}ms: no rows ]>-", "diff"))

    # -- disabled_scanlators -------------------------------------------

    @developer.command(name="disabled_scanlators", aliases=["dscan"])
    async def disabled_scanlators(self, ctx: commands.Context) -> None:
        try:
            data = await self.bot.crawler.request("schema_health_list")
        except CrawlerError as exc:
            await ctx.send(f"crawler error: `{exc.code}`: {exc.message}")
            return
        rows = data.get("websites") or data.get("results") or []
        disabled = [r for r in rows if isinstance(r, dict) and r.get("works") is False]
        embed = discord.Embed(
            title="Disabled scanlators",
            color=discord.Color.red(),
        )
        if not disabled:
            embed.description = _code_block("+ None +", "diff")
        else:
            keys = "\n- ".join(str(r.get("website_key", "?")) for r in disabled)
            embed.description = _code_block(f"- {keys}", "diff")
        await ctx.send(embed=embed)

    # -- g_update -------------------------------------------------------

    @developer.command(name="g_update")
    async def g_update(self, ctx: commands.Context, *, message: str) -> None:
        from ..db.guild_settings import GuildSettingsStore

        store = GuildSettingsStore(self.bot.db)
        targets = await store.list_with_system_alerts()
        viable: list[tuple[int, int]] = []
        for s in targets:
            channel_id = s.system_alerts_channel_id
            if channel_id is None:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if channel is None or not isinstance(channel, discord.abc.Messageable):
                continue
            guild = getattr(channel, "guild", None)
            me = guild.me if guild is not None else None
            perms = channel.permissions_for(me) if me is not None else None
            if perms is None or (perms.send_messages and perms.embed_links):
                viable.append((s.guild_id, int(channel_id)))

        if not viable:
            await ctx.send("No viable system-alerts channels found.")
            return

        body = (
            f"{message}\n\n*If you have any questions, please join the support server "
            "and ping the maintainers.*"
        )
        embed = discord.Embed(
            title="⚠️ Important Update ⚠️",
            description=body,
            color=discord.Color.red(),
        )
        embed.set_footer(text="Sent by the bot owner.")

        view = _ConfirmView(invoker_id=ctx.author.id)
        view.message = await ctx.send(f"Send to **{len(viable)}** guilds?", embed=embed, view=view)
        await view.wait()
        if not view.result:
            await view.message.edit(content="Cancelled.", embed=None, view=None)
            return
        await view.message.edit(content=f"Sending to {len(viable)}…", view=None)

        ok = 0
        for _guild_id, channel_id in viable:
            channel = self.bot.get_channel(channel_id)
            if not isinstance(channel, discord.abc.Messageable):
                continue
            try:
                await channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )
                ok += 1
            except discord.HTTPException:
                pass
        await view.message.edit(content=f"Sent to {ok}/{len(viable)}.")

    # -- test_update ----------------------------------------------------

    @developer.command(name="test_update")
    async def test_update(self, ctx: commands.Context) -> None:
        cog = self.bot.cogs.get("Updates")
        if cog is None:
            await ctx.send("UpdatesCog not loaded.")
            return
        record = {
            "id": 0,
            "payload": {
                "website_key": "test",
                "url_name": "fake-series",
                "series_title": "Fake Series",
                "series_url": "https://example.com/series/fake-series",
                "cover_url": None,
                "chapter": {
                    "name": "Chapter 1",
                    "index": 1,
                    "url": "https://example.com/series/fake-series/chapter/1",
                    "is_premium": False,
                },
            },
        }
        try:
            await cog.dispatch(record)  # type: ignore[attr-defined]
        except Exception:
            await self._send_long_text(ctx, tb.format_exc(), lang="py")
            return
        await ctx.message.add_reaction("✅")

    # -- crawler subgroup ----------------------------------------------

    @developer.group(name="crawler", invoke_without_command=True)
    async def crawler(self, ctx: commands.Context) -> None:
        await ctx.send("Use `crawler health|heal|test|websites`.")

    @crawler.command(name="health")
    async def crawler_health(self, ctx: commands.Context, website_key: str | None = None) -> None:
        try:
            data = await self.bot.crawler.request("schema_health_list")
        except CrawlerError as exc:
            await ctx.send(f"crawler error: `{exc.code}`: {exc.message}")
            return
        rows = data.get("websites") or data.get("results") or []
        if website_key:
            rows = [r for r in rows if str(r.get("website_key")) == website_key]
        if not rows:
            await ctx.send("(no rows)")
            return
        lines = [f"{'website':<24} {'works':<6} {'reason'}"]
        for r in rows:
            lines.append(
                f"{r.get('website_key', '?')!s:<24} "
                f"{r.get('works', '?')!s:<6} "
                f"{r.get('reason') or r.get('error') or ''!s}"
            )
        await self._send_long_text(ctx, "\n".join(lines), lang="")

    @crawler.command(name="heal")
    async def crawler_heal(
        self,
        ctx: commands.Context,
        website_key: str,
        series_url: str,
        *flags: str,
    ) -> None:
        dry_run, _ = _flag(list(flags), "dry-run")
        try:
            data = await self.bot.crawler.request(
                "schema_healing_run",
                website_key=website_key,
                series_url=series_url,
                dry_run=dry_run,
            )
        except CrawlerError as exc:
            await ctx.send(f"crawler error: `{exc.code}`: {exc.message}")
            return
        await self._send_long_text(ctx, json.dumps(data, indent=2, default=str), lang="json")

    @crawler.command(name="test")
    async def crawler_test(self, ctx: commands.Context, website_key: str, *flags: str) -> None:
        flag_list = list(flags)
        series_url, flag_list = _named(flag_list, "series")
        search_query, _ = _named(flag_list, "query")
        kwargs: dict[str, Any] = {"website_key": website_key}
        if series_url:
            kwargs["series_url"] = series_url
        if search_query:
            kwargs["search_query"] = search_query
        try:
            data = await self.bot.crawler.request("schema_health_test", **kwargs)
        except CrawlerError as exc:
            await ctx.send(f"crawler error: `{exc.code}`: {exc.message}")
            return
        await self._send_long_text(ctx, json.dumps(data, indent=2, default=str), lang="json")

    @crawler.command(name="websites")
    async def crawler_websites(self, ctx: commands.Context) -> None:
        self.bot.websites_cache.invalidate("websites")
        self.bot.websites_cache.invalidate("websites_full")
        try:
            data = await self.bot.crawler.request("supported_websites")
        except CrawlerError as exc:
            await ctx.send(f"crawler error: `{exc.code}`: {exc.message}")
            return
        sites = data.get("websites") or []
        keys = [str(w.get("key") or w.get("website_key") or w) for w in sites]
        await self._send_long_text(
            ctx,
            f"{len(keys)} supported websites:\n" + "\n".join(f"- {k}" for k in keys),
            lang="",
        )

    # -- premium subgroup ----------------------------------------------

    @developer.group(name="premium", invoke_without_command=True)
    async def premium(self, ctx: commands.Context) -> None:
        await ctx.send("Use `premium grant|revoke|list|check|patreon`.")

    @premium.command(name="grant")
    async def premium_grant(
        self,
        ctx: commands.Context,
        scope: Literal["user", "guild"],
        target_id: int,
        duration: str,
        *,
        reason: str | None = None,
    ) -> None:
        try:
            expires_at = duration_parser.parse_duration(duration)
        except ValueError as exc:
            await ctx.send(f"bad duration: {exc}")
            return
        grant_id = await self.bot.premium.grants.store.grant(
            scope=scope,
            target_id=target_id,
            granted_by=ctx.author.id,
            reason=reason,
            expires_at=expires_at,
        )
        expiry_msg = expires_at or "permanent"
        await ctx.send(
            f"✅ Granted premium (`{scope}` `{target_id}`) — id=`{grant_id}` "
            f"expires=`{expiry_msg}`."
        )

    @premium.command(name="revoke")
    async def premium_revoke(self, ctx: commands.Context, *args: str) -> None:
        if not args:
            await ctx.send(
                "Usage: `premium revoke <grant_id>` or `premium revoke <user|guild> <id>`"
            )
            return
        first = args[0].lower()
        if first in ("user", "guild"):
            if len(args) < 2:
                await ctx.send("missing target id")
                return
            try:
                target_id = int(args[1])
            except ValueError:
                await ctx.send("target id must be an integer")
                return
            view = _ConfirmView(invoker_id=ctx.author.id)
            view.message = await ctx.send(
                f"Revoke ALL active grants for `{first}` `{target_id}`?", view=view
            )
            await view.wait()
            if not view.result:
                await view.message.edit(content="Cancelled.", view=None)
                return
            await self.bot.premium.grants.store.revoke_for_target(first, target_id)
            await view.message.edit(content="✅ Revoked.", view=None)
            return
        try:
            grant_id = int(first)
        except ValueError:
            await ctx.send("expected `<grant_id>` or `<user|guild> <id>`")
            return
        await self.bot.premium.grants.store.revoke(grant_id)
        await ctx.send(f"✅ Revoked grant `{grant_id}`.")

    @premium.command(name="list")
    async def premium_list(
        self,
        ctx: commands.Context,
        scope: Literal["user", "guild", "all"] = "all",
        active: bool = True,
    ) -> None:
        scope_arg = None if scope == "all" else scope
        rows = await self.bot.premium.grants.store.list(
            scope=scope_arg, active_only=active, limit=200
        )
        if not rows:
            await ctx.send("(no grants)")
            return
        page_size = 10
        embeds: list[discord.Embed] = []
        for i in range(0, len(rows), page_size):
            chunk = rows[i : i + page_size]
            lines = []
            for g in chunk:
                expiry = g.expires_at or "permanent"
                revoked = f" revoked={g.revoked_at}" if g.revoked_at else ""
                lines.append(
                    f"`{g.id}` {g.scope}={g.target_id} expires={expiry}{revoked} "
                    f"reason={g.reason or '-'}"
                )
            embeds.append(
                discord.Embed(
                    title=f"Premium grants ({i + 1}-{i + len(chunk)} / {len(rows)})",
                    description="\n".join(lines),
                    color=discord.Color.gold(),
                )
            )
        view = Paginator(embeds, invoker_id=ctx.author.id)
        await ctx.send(embed=embeds[0], view=view)

    @premium.command(name="check")
    async def premium_check(self, ctx: commands.Context, user: discord.User) -> None:
        ok, reason = await self.bot.premium.is_premium(
            user_id=user.id, guild_id=None, interaction=None
        )
        sources: list[str] = []
        if await self.bot.premium.grants.is_active("user", user.id):
            sources.append("grant_user")
        if self.bot.premium.patreon.enabled and await self.bot.premium.patreon.is_premium(user.id):
            sources.append("patreon")
        if self.bot.premium.discord_ents.is_user_premium(user.id):
            sources.append("discord_user")
        embed = discord.Embed(
            title=f"Premium check — {user}",
            description=(
                f"**ok**: `{ok}`\n"
                f"**consolidated reason**: `{reason or '-'}`\n"
                f"**qualifying sources**: {', '.join(sources) if sources else '(none)'}"
            ),
            color=discord.Color.green() if ok else discord.Color.red(),
        )
        await ctx.send(embed=embed)

    @premium.group(name="patreon", invoke_without_command=True)
    async def premium_patreon(self, ctx: commands.Context) -> None:
        await ctx.send("Use `premium patreon refresh|link`.")

    @premium_patreon.command(name="refresh")
    async def premium_patreon_refresh(self, ctx: commands.Context) -> None:
        if not self.bot.premium.patreon.enabled:
            await ctx.send("Patreon source disabled in config.")
            return
        try:
            count = await self.bot.premium.patreon.refresh()
        except Exception:
            await self._send_long_text(ctx, tb.format_exc(), lang="py")
            return
        await ctx.send(f"✅ Patreon refresh wrote `{count}` active patrons.")

    @premium_patreon.command(name="link")
    async def premium_patreon_link(
        self,
        ctx: commands.Context,
        user: discord.User,
        patreon_user_id: str,
    ) -> None:
        now = datetime.now(tz=UTC)
        fmt = "%Y-%m-%d %H:%M:%S"
        await self.bot.premium.patreon._store.upsert(
            discord_user_id=user.id,
            patreon_user_id=patreon_user_id,
            tier_ids="[]",
            cents=0,
            refreshed_at=now.strftime(fmt),
            expires_at=(now + timedelta(days=1)).strftime(fmt),
        )
        await ctx.send(
            f"✅ Linked `{user}` → patreon `{patreon_user_id}` (expires in 24h; "
            "advanced on next poll)."
        )

    # -- helpers --------------------------------------------------------

    async def _send_long_text(self, ctx: commands.Context, text: str, *, lang: str = "") -> None:
        chunks = _split_text(text)
        if len(chunks) == 1:
            await ctx.send(_code_block(chunks[0], lang))
            return
        if sum(len(c) for c in chunks) > _DISCORD_LIMIT * 4:
            buf = io.BytesIO(text.encode("utf-8"))
            await ctx.send(file=discord.File(buf, filename="output.txt"))
            return
        embeds = [
            discord.Embed(
                description=_code_block(c, lang),
                color=discord.Color.dark_grey(),
            )
            for c in chunks
        ]
        view = Paginator(embeds, invoker_id=ctx.author.id)
        await ctx.send(embed=embeds[0], view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DevCog(bot))
