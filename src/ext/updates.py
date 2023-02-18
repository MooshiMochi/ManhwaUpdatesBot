from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from core.bot import MangaClient

from discord import app_commands
from discord.ext import commands, tasks

from src.core.scanlationClasses import *
from src.objects import PaginatorView


class MangaUpdates(commands.Cog):
    def __init__(self, bot: MangaClient):
        self.bot: MangaClient = bot
        self.SCANLATORS: dict[str, ABCScan] = {
            "tritinia": TritiniaScans,
            "manganato": Manganato,
            "toonily": Toonily,
        }
        # self.register_command_checks()

    async def cog_load(self):
        self.bot._logger.info("Loaded Manga Updates Cog...")
        self.check_updates_task.start()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        ignore_checks = ["list", "unsubscribe"]
        if interaction.command.qualified_name in ignore_checks:
            return True

        if interaction.guild_id is None:
            em = discord.Embed(
                title="Error",
                description="This command can only be used in a server.",
                color=0xFF0000,
            )
            em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)
            return False

        elif await self.bot.db.get_guild_config(interaction.guild_id) is None:
            em = discord.Embed(
                title="Error",
                description="This server has not been setup yet.",
                color=0xFF0000,
            )
            em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)
            return False

        return True

    @tasks.loop(hours=1.0)
    async def check_updates_task(self):
        subscribed_series: list[
            tuple[str, str, str, float, bool, str]
        ] = await self.bot.db.get_all_subscribed_series()

        if not subscribed_series:
            return

        all_series: list[
            tuple[str, str, str, float, bool, str]
        ] = await self.bot.db.get_all_series()

        series_ids_to_discard = set([x[0] for x in all_series]) - set(
            [x[0] for x in subscribed_series]
        )

        if series_ids_to_discard:
            await self.bot.db.bulk_delete_series(series_ids_to_discard)

        series_webhook_roles: list[
            tuple[str, str, str]
        ] = await self.bot.db.get_series_webhook_role_pairs()

        series_webhooks_roles: dict[str, dict[str, list[tuple[str, str]]]] = {}
        for series_id, webhook_url, role_id in series_webhook_roles:
            if series_id not in series_webhooks_roles:
                series_webhooks_roles[series_id] = {
                    "webhook_role_pairs": [(webhook_url, role_id)]
                }
            else:
                series_webhooks_roles[series_id]["webhook_role_pairs"].append(
                    (webhook_url, role_id)
                )

        for (
            series_id,
            human_name,
            manga_url,
            last_chapter,
            completed,
            scanlator,
        ) in subscribed_series:
            if completed:
                self.bot._logger.warning(f"Deleting completed series {human_name}")
                await self.bot.db.delete_series(series_id)

            scanner = self.SCANLATORS.get(scanlator, None)
            if scanner is None:
                self.bot._logger.warning(
                    f"Unknown scanlator {scanlator} for {human_name}. ID--{series_id}"
                )
                log_em = discord.Embed(
                    title="Unknown Scanlator",
                    description=f"```diff\n- Scanlator: {scanlator}\n- Name: {human_name}\n- ID: {series_id}```",
                )
                log_em.set_footer(
                    text="Manga Updates Logs", icon_url=self.bot.user.avatar_url
                )
                await self.bot.log_to_discord(embed=log_em)
                continue

            update_check_result = await scanner.check_updates(
                self.bot._session, human_name, manga_url, series_id, last_chapter
            )

            if update_check_result is None:
                self.bot._logger.info(f"No updates for {human_name} ({series_id})")
                continue

            url, new_chapter = update_check_result

            await self.bot.db.update_series(series_id, new_chapter)

            wh_n_role = series_webhooks_roles.get(series_id, None)
            if wh_n_role is None:
                self.bot._logger.warning(
                    f"No webhook/role pairs for {human_name} ({series_id})"
                )
                continue
            for webhook_url, role_id in wh_n_role["webhook_role_pairs"]:
                webhook = discord.Webhook.from_url(
                    webhook_url, session=self.bot._session
                )

                if webhook:
                    self.bot._logger.info(
                        f"Sending update for {human_name}. Chapter {new_chapter}"
                    )
                    await webhook.send(
                        f"<@&{role_id}> **{human_name}** chapter **{new_chapter}** has been released!\n{url}",
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )
                else:
                    self.bot._logger.warning(f"Cant connect to webhook {webhook_url}")

    @check_updates_task.before_loop
    async def before_check_updates_task(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="subscribe", description="Subscribe to a manga series.")
    async def subscribe(self, interaction: discord.Interaction, manga_url: str) -> None:
        if RegExpressions.manganato_url.match(manga_url):
            scanlator = Manganato

            series_id = RegExpressions.manganato_url.search(manga_url).group(4)
            url_name = None  # we don't care for it in manganato
            series_url: str = Manganato.fmt_url.format(manga_id=series_id)

        elif RegExpressions.tritinia_url.match(manga_url):
            scanlator = TritiniaScans

            url_name = RegExpressions.tritinia_url.search(manga_url).group(3)
            series_url: str = TritiniaScans.base_url + url_name
            series_id = TritiniaScans.get_manga_id(series_url)

        elif RegExpressions.toonily_url.match(manga_url):
            scanlator = Toonily

            url_name = RegExpressions.toonily_url.search(manga_url).group(3)
            series_url: str = Toonily.base_url + url_name
            series_id = Toonily.get_manga_id(series_url)

        else:
            em = discord.Embed(title="Invalid URL", color=discord.Color.red())
            em.description = (
                "The URL you provided must follow either format:\n```diff"
                "\n+ Manganato -> https://manganato.com/manga-m123456"
                "\n+ Tritinia  -> https://tritinia.org/manga/manga-title/"
                "\n+ Toonily   -> https://toonily.net/manga/manga-title/"
                "```"
            )
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        completed = await scanlator.is_series_completed(
            self.bot._session, series_id, url_name
        )

        if completed:
            em = discord.Embed(title="Series Completed", color=discord.Color.red())
            em.description = "This series has already been completed."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        latest_chapter = await scanlator.get_curr_chapter_num(
            self.bot._session, series_id, url_name
        )
        series_name = await scanlator.get_human_name(
            self.bot._session, series_id, url_name
        )

        await self.bot.db.add_series(
            series_id,
            series_name,
            series_url,
            latest_chapter or 1,
            False,
            scanlator.name,
        )

        await self.bot.db.subscribe_user(
            interaction.user.id, interaction.guild_id, series_id
        )

        embed = discord.Embed(
            title="Subscribed to Series",
            color=discord.Color.green(),
            description=f"Successfully subscribed to {series_name}!",
        )
        embed.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def manga_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete for the playlist command."""
        subs: list[str, str] = await self.bot.db.get_user_subs(
            interaction.user.id, current
        )

        return [discord.app_commands.Choice(name=x[1], value=x[0]) for x in subs][:25]

    @app_commands.command(
        name="unsubscribe", description="Unsubscribe from a series on Manganato."
    )
    @app_commands.describe(manga_name="The name of the series.")
    @app_commands.autocomplete(manga_name=manga_autocomplete)
    async def unsubscribe(self, interaction: discord.Interaction, manga_name: str):
        await self.bot.db.unsub_user(interaction.user.id, manga_name)

        manga_name = await self.bot.db.get_series_name(manga_name)

        em = discord.Embed(title="Unsubscribed", color=discord.Color.green())
        em.description = f"Successfully unsubscribed from `{manga_name}`."
        em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.response.send_message(embed=em, ephemeral=True)
        return

    @app_commands.command(name="list", description="List all your subscribed series.")
    async def list_subs(self, interaction: discord.Interaction):

        subs = await self.bot.db.get_user_subs(interaction.user.id)

        if not subs:
            em = discord.Embed(title="No Subscriptions", color=discord.Color.red())
            em.description = "You have no subscriptions."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        if len(subs) <= 25:
            em = discord.Embed(title="Your Subscriptions", color=discord.Color.green())
            em.description = (
                "```diff\n"
                + "- "
                + "\n- ".join([f"{x[1]} - {x[2]}" for x in subs])
                + "```"
            )
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        pages = []
        for i in range(0, len(subs), 25):
            em = discord.Embed(title="Your Subscriptions", color=discord.Color.green())
            em.description = (
                "```diff\n"
                + "- "
                + "\n- ".join([f"{x[1]} - {x[2]}" for x in subs[i : i + 25]])
                + "```"
            )
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            pages.append(em)

        view = PaginatorView(pages, interaction, 60)
        await interaction.response.send_message(embed=pages[0], view=view)


async def setup(bot: MangaClient) -> None:
    if bot._debug_mode:
        await bot.add_cog(MangaUpdates(bot), guild=discord.Object(id=bot.test_guild_id))
    else:
        await bot.add_cog(MangaUpdates(bot))
