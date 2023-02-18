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
        series: list[
            tuple[str, str, str, float, bool, str]
        ] = await self.bot.db.get_all_series()
        subscribed_series: dict[int, list[str]] = await self.bot.db.get_all_user_subs()

        subbed_series_ids = set(
            [
                series_id
                for user_subs in subscribed_series.values()
                for series_id in user_subs
            ]
        )
        untracked_series_ids = set([x[0] for x in series]) - subbed_series_ids

        if untracked_series_ids:
            await self.bot.db.bulk_delete_series(untracked_series_ids)

        series = [x for x in series if x[0] in subbed_series_ids]

        for (
            series_id,
            human_name,
            manga_url,
            last_chapter,
            completed,
            scanlator,
        ) in series:
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
                self.bot._logger.debug(f"No updates for {human_name} ({series_id})")
                continue

            url, new_chapter = update_check_result

            await self.bot.db.update_series(series_id, new_chapter)

            for channel_id, role_id in await self.bot.db.get_series_channels_and_roles(
                series_id
            ):
                channel = self.bot.get_channel(channel_id)
                if channel:
                    self.bot._logger.debug(
                        f"Sending update for {human_name}. Chapter {new_chapter}"
                    )
                    await channel.send(
                        f"<@&{role_id}> **{human_name}** chapter **{new_chapter}** has been released!\n{url}",
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )
                else:
                    self.bot._logger.warning(f"Cant find channel {channel_id}")

    @check_updates_task.before_loop
    async def before_check_updates_task(self):
        await self.bot.wait_until_ready()

    sub_group = app_commands.Group(
        name="subscribe", description="Subscribe to a manga series."
    )

    @sub_group.command(
        name="tritinia", description="Subscribe to a series on Tritinia Scans."
    )
    async def sub_tritinia(self, interaction: discord.Interaction, series_url: str):

        manga_url_name = RegExpressions.tritinia_url.search(series_url)
        if not manga_url_name:
            em = discord.Embed(title="Invalid URL", color=discord.Color.red())
            em.description = "The URL you provided must follow the format:\n```diff\n+ https://tritinia.org/manga/manga-title/```"
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        url_name = manga_url_name.group(3)
        completed = await TritiniaScans.is_series_completed(self.bot._session, url_name)

        if completed:
            em = discord.Embed(title="Series Completed", color=discord.Color.red())
            em.description = "This series has already been completed."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        scanlator = "tritinia"
        series_name = await TritiniaScans.get_human_name(self.bot._session, url_name)
        series_id = TritiniaScans.get_manga_id(TritiniaScans.base_url + url_name)
        latest_chapter = await TritiniaScans.get_curr_chapter_num(
            self.bot._session, url_name, None
        )
        await self.bot.db.add_series(
            series_id,
            series_name,
            TritiniaScans.base_url + url_name,
            latest_chapter or 1,
            False,
            scanlator,
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

    @sub_group.command(
        name="manganato", description="Subscribe to a series on Manganato."
    )
    @app_commands.describe(
        series_url="The URL of the series. E.g https://manganato.com/manga-abc123"
    )
    async def sub_manganato(self, interaction: discord.Interaction, series_url: str):

        manga_id = RegExpressions.manganato_url.search(series_url)

        if not manga_id:
            em = discord.Embed(title="Invalid URL", color=discord.Color.red())
            em.description = "The URL you provided must follow either format:\n```diff\n+ https://manganato.com/manga-abc123\n+ https://chapmanganato.com/manga-abc123```"
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        series_id = manga_id.group(4)
        completed = await Manganato.is_series_completed(self.bot._session, series_id)

        if completed:
            em = discord.Embed(title="Series Completed", color=discord.Color.red())
            em.description = "This series has already been completed."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        scanlator = "manganato"
        series_name = await Manganato.get_human_name(self.bot._session, series_id)
        latest_chapter = await Manganato.get_curr_chapter_num(
            self.bot._session, None, series_id
        )
        await self.bot.db.add_series(
            series_id,
            series_name,
            Manganato.fmt_url.format(manga_id=series_id),
            latest_chapter or 1,
            False,
            scanlator,
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

    @sub_group.command(name="toonily", description="Subscribe to a series on Toonily.")
    @app_commands.describe(
        series_url="The URL of the series. E.g https://toonily.com/webtoon/series-name/"
    )
    async def sub_toonily(self, interaction: discord.Interaction, series_url: str):

        manga_url_name = RegExpressions.toonily_url.search(series_url)
        if not manga_url_name:
            em = discord.Embed(title="Invalid URL", color=discord.Color.red())
            em.description = "The URL you provided must follow the format:\n```diff\n+ https://toonily.com/webtoon/manga-title/```"
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        url_name = manga_url_name.group(3)
        completed = await Toonily.is_series_completed(self.bot._session, url_name)

        if completed:
            em = discord.Embed(title="Series Completed", color=discord.Color.red())
            em.description = "This series has already been completed."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        scanlator = "toonily"
        series_name = await Toonily.get_human_name(self.bot._session, url_name)
        series_id = Toonily.get_manga_id(Toonily.base_url + url_name)
        latest_chapter = await Toonily.get_curr_chapter_num(
            self.bot._session, url_name, None
        )
        await self.bot.db.add_series(
            series_id,
            series_name,
            Toonily.base_url + url_name,
            latest_chapter or 1,
            False,
            scanlator,
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
