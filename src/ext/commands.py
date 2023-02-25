from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

if TYPE_CHECKING:
    from core.bot import MangaClient

from discord import app_commands
from discord.ext import commands, tasks

from src.core.scanlationClasses import *
from src.objects import Manga, PaginatorView, RateLimiter
from src.views import SubscribeView


class MangaUpdates(commands.Cog):
    def __init__(self, bot: MangaClient):
        self.bot: MangaClient = bot
        self.SCANLATORS: dict[str, ABCScan] = SCANLATORS
        self.rate_limiter: RateLimiter = RateLimiter()

    async def cog_load(self):
        self.bot._logger.info("Loaded Manga Updates Cog...")
        self.bot.add_view(SubscribeView(self.bot))
        self.check_updates_task.start()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        commands_to_check = [
            "subscribe",
        ]
        if interaction.command.qualified_name not in commands_to_check:
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
        subscribed_series: list[Manga] = await self.bot.db.get_all_subscribed_series()
        if not subscribed_series:
            return

        all_series: list[Manga] = await self.bot.db.get_all_series()

        series_to_delete_ids = [
            m.id for m in all_series if m.id not in [m2.id for m2 in subscribed_series]
        ]

        if series_to_delete_ids:
            print(f"All series: ({len(all_series)}) ->> {all_series}")
            print(
                f"Subscribed series: ({len(subscribed_series)}) ->> {subscribed_series}"
            )
            self.bot._logger.warn(
                f"Series to delete: ({len(series_to_delete_ids)}) ->> {series_to_delete_ids}"
            )
            await self.bot.db.bulk_delete_series(series_to_delete_ids)

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

        for manga in subscribed_series:
            if manga.completed:
                self.bot._logger.warning(
                    f"Deleting completed series {manga.human_name}"
                )
                await self.bot.db.delete_series(manga.series_id)

            scanner = self.SCANLATORS.get(manga.scanlator, None)
            if scanner is None:
                self.bot._logger.warning(
                    f"Unknown scanlator {manga.scanlator} for {manga.human_name}. ID--{manga.id}"
                )
                log_em = discord.Embed(
                    title="Unknown Scanlator",
                    description=f"```diff\n- Scanlator: {manga.scanlator}\n- Name: {manga.human_name}\n- ID: {manga.id}```",
                )
                log_em.set_footer(
                    text="Manga Updates Logs", icon_url=self.bot.user.avatar_url
                )
                await self.bot.log_to_discord(embed=log_em)
                continue

            await self.rate_limiter.delay_if_necessary(manga)

            update_check_result = await scanner.check_updates(
                self.bot,
                manga.human_name,
                manga.manga_url,
                manga.id,
                manga.last_chapter,
            )

            if update_check_result is None:
                # self.bot._logger.info(f"No updates for {manga.human_name} ({manga.id})")
                continue

            url, new_chapter, completed = update_check_result
            manga.update(new_chapter, completed)
            await self.bot.db.update_series(manga)

            wh_n_role = series_webhooks_roles.get(manga.id, None)
            if wh_n_role is None:
                self.bot._logger.warning(
                    f"No webhook/role pairs for {manga.human_name} ({manga.id})"
                )
                continue
            for webhook_url, role_id in wh_n_role["webhook_role_pairs"]:
                webhook = discord.Webhook.from_url(
                    webhook_url, session=self.bot._session
                )

                if webhook:
                    self.bot._logger.info(
                        f"Sending update for {manga.human_name}. Chapter {new_chapter}"
                    )
                    if int(new_chapter) == new_chapter:
                        new_chapter = int(new_chapter)
                    await webhook.send(
                        f"<@&{role_id}> **{manga.human_name}** chapter **{new_chapter}** has been released!\n{url}",
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )
                else:
                    self.bot._logger.warning(f"Cant connect to webhook {webhook_url}")

    @check_updates_task.before_loop
    async def before_check_updates_task(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="subscribe", description="Subscribe to a manga series.")
    async def subscribe(self, interaction: discord.Interaction, manga_url: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

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

        elif RegExpressions.mangadex_url.match(manga_url):
            scanlator = MangaDex

            url_name = RegExpressions.mangadex_url.search(manga_url).group(
                3
            )  # this is the manga id, but who cares
            series_url: str = MangaDex.fmt_url.format(manga_id=url_name)
            series_id = MangaDex.get_manga_id(series_url)

        else:
            em = discord.Embed(title="Invalid URL", color=discord.Color.red())
            em.description = (
                "The URL you provided must follow either format:\n```diff"
                "\n+ Manganato -> https://manganato.com/manga-m123456"
                "\n+ Tritinia  -> https://tritinia.org/manga/manga-title/"
                "\n+ Toonily   -> https://toonily.net/manga/manga-title/"
                "\n+ Mangadex  -> https://mangadex.org/title/1b2c3d/``"
                "```"
            )
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        completed = await scanlator.is_series_completed(self.bot, series_id, url_name)

        if completed:
            em = discord.Embed(title="Series Completed", color=discord.Color.red())
            em.description = "This series has already been completed."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        latest_chapter = await scanlator.get_curr_chapter_num(
            self.bot, series_id, url_name
        )
        series_name = await scanlator.get_human_name(self.bot, series_id, url_name)

        manga: Manga = Manga(
            series_id, series_name, series_url, latest_chapter, False, scanlator.name
        )

        await self.bot.db.add_series(manga)

        await self.bot.db.subscribe_user(
            interaction.user.id, interaction.guild_id, manga.id
        )

        embed = discord.Embed(
            title="Subscribed to Series",
            color=discord.Color.green(),
            description=f"Successfully subscribed to **{series_name}!**",
        )
        embed.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def manga_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete for the /unsubscribe command."""
        subs: list[Manga] = await self.bot.db.get_user_subs(
            interaction.user.id, current
        )

        return [
            discord.app_commands.Choice(
                name=(
                    x.human_name[:97] + "..."
                    if len(x.human_name) > 100
                    else x.human_name
                ),
                value=x.id,
            )
            for x in subs
        ][:25]

    async def latest_chapters_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete for the /latest command"""
        subs: list[Manga] = await self.bot.db._get_all_series_autocomplete(current)
        return [
            discord.app_commands.Choice(
                name=(
                    x.human_name[:97] + "..."
                    if len(x.human_name) > 100
                    else x.human_name
                ),
                value=x.id,
            )
            for x in subs
        ][:25]

    @app_commands.command(
        name="unsubscribe", description="Unsubscribe from a series on Manganato."
    )
    @app_commands.describe(manga_id="The name of the series.")
    @app_commands.autocomplete(manga_id=manga_autocomplete)
    @app_commands.rename(manga_id="manga")
    async def unsubscribe(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        manga: Manga = await self.bot.db.get_series(manga_id)

        await self.bot.db.unsub_user(interaction.user.id, manga_id)

        em = discord.Embed(title="Unsubscribed", color=discord.Color.green())
        em.description = f"Successfully unsubscribed from `{manga.human_name}`."
        em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.followup.send(embed=em, ephemeral=True)
        return

    @app_commands.command(name="list", description="List all your subscribed series.")
    async def list_subs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        subs: list[Manga] = await self.bot.db.get_user_subs(interaction.user.id)

        if not subs:
            em = discord.Embed(title="No Subscriptions", color=discord.Color.red())
            em.description = "You have no subscriptions."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        if len(subs) <= 25:
            em = discord.Embed(title="Your Subscriptions", color=discord.Color.green())
            em.description = (
                "```diff\n"
                + "- "
                + "\n- ".join([f"{x.human_name} - {x.last_chapter}" for x in subs])
                + "```"
            )
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        pages = []
        for i in range(0, len(subs), 25):
            em = discord.Embed(title="Your Subscriptions", color=discord.Color.green())
            em.description = (
                "```diff\n"
                + "- "
                + "\n- ".join(
                    [f"{x.human_name} - {x.last_chapter}" for x in subs[i : i + 25]]
                )
                + "```"
            )
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            pages.append(em)

        view = PaginatorView(pages, interaction, 60)
        await interaction.followup.send(embed=pages[0], view=view)

    @app_commands.command(
        name="latest", description="Get the latest chapter of a series."
    )
    @app_commands.describe(manga_id="The name of the series.")
    @app_commands.autocomplete(manga_id=latest_chapters_autocomplete)
    @app_commands.rename(manga_id="manga")
    async def latest_chapter(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        manga: Manga = await self.bot.db.get_series(manga_id)

        em = discord.Embed(title="Latest Chapter", color=discord.Color.green())
        em.description = (
            f"The latest chapter of `{manga.human_name}` is `{manga.last_chapter}`."
        )
        em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.followup.send(embed=em, ephemeral=True)
        return

    @app_commands.command(
        name="help", description="Get started with Manga Updates Bot."
    )
    async def help(self, interaction: discord.Interaction) -> None:
        em = discord.Embed(title="Manga Updates Bot", color=discord.Color.green())
        em.description = (
            "Manga Updates Bot is a bot that allows you to subscribe to your favorite manga series and get notified when a new chapter is released.\n"
            "To get started, the bot needs to be set up first. This can be done by using the `/config setup` command.\n"
            "Note that this command can only be used by a server moderator that has the manage_channels/manage_roles permissions.\n\n"
            "**Commands:**\n"
            "You can subscribe to a series by using the `/subscribe` command."
            "You can also unsubscribe from a series by using the `/unsubscribe` command.\n"
            "You can view all your subscribed series by using the `/list` command.\n"
            "You can also view the latest chapter of a series by using the `/latest` command.\n\n"
            "**Permissions:**\n"
            "The bot needs the following permissions to function properly:\n"
            "• Send Messages\n"
            "• Embed Links\n"
            "• Manage Webhooks\n\n"
            "**Further Help:**\n"
            "If you need further help, you can join the [support server](https://discord.gg/EQ83EWW7Nu) and contact Mooshi#6669 - the bot developer.\n\n"
        )
        em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
        await interaction.response.send_message(embed=em, ephemeral=True)
        return

    @app_commands.command(
        name="search", description="Search for a manga series on Mangadex."
    )
    @app_commands.describe(query="The name of the manga.")
    async def dex_search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if manga_id := MangaDex.get_rx_url_name(query):
            response: dict[str, Any] = await self.bot.mangadex_api.get_manga(manga_id)
        else:
            response: dict[str, Any] = await self.bot.mangadex_api.search(
                query, limit=1
            )
        results: list[dict[str, Any]] = (
            response["data"]
            if isinstance(response["data"], list)
            else [response["data"]]
        )

        if not results:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="No Results Found",
                    description="No results were found for your query.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

        result = results[0]

        chapters = await self.bot.mangadex_api.get_chapters_list(result["id"])
        if chapters:
            latest_chapter = chapters[-1]["attributes"]["chapter"]
        else:
            latest_chapter = "N/A"

        em = discord.Embed(
            title=f"Title: {result['attributes']['title']['en']}",
            color=discord.Color.green(),
        )
        cover_id = [
            x["id"] for x in result["relationships"] if x["type"] == "cover_art"
        ][0]
        cover_url = await self.bot.mangadex_api.get_cover(result["id"], cover_id)
        synopsis = result["attributes"]["description"]["en"]

        em.set_image(url=cover_url)
        em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        em.description = (
            f"**Year:** {result['attributes']['year']}\n"
            f"**Status:** {result['attributes']['status'].title()}\n"
            f"**Latest English Chapter:** {latest_chapter}\n"
        )

        em.add_field(
            name="Tags:",
            value=f"`#{'` `#'.join([x['attributes']['name']['en'] for x in result['attributes']['tags'] if x['type'] == 'tag'])}`",
        )

        max_field_length = 1024
        paragraphs = synopsis.split("\n\n")
        for paragraph in paragraphs:
            if len(paragraph) <= max_field_length:
                em.add_field(name="\u200b", value=paragraph, inline=False)
            else:
                current_field = ""
                sentences = paragraph.split(".")
                for i in range(len(sentences)):
                    sentence = sentences[i].strip() + "."
                    if len(current_field) + len(sentence) > max_field_length:
                        em.add_field(name="\u200b", value=current_field, inline=False)
                        current_field = ""
                    current_field += sentence
                    if i == len(sentences) - 1 and current_field != "":
                        em.add_field(name="\u200b", value=current_field, inline=False)

        em.add_field(
            name="MangaDex Link:",
            value=f"https://mangadex.org/title/{result['id']}",
            inline=False,
        )

        view = SubscribeView(self.bot)

        await interaction.followup.send(
            embed=em,
            ephemeral=True,
            view=view,
        )


async def setup(bot: MangaClient) -> None:
    if bot._debug_mode:
        await bot.add_cog(MangaUpdates(bot), guild=discord.Object(id=bot.test_guild_id))
    else:
        await bot.add_cog(MangaUpdates(bot))
