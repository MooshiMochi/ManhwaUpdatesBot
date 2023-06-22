from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core import MangaClient
    from src.ext.update_check import UpdateCheckCog

from discord import app_commands
from discord.ext import commands

from src.core.errors import MangaCompletedOrDropped
from src.core.scanners import *
from src.core.objects import Manga, PaginatorView
from src.core.ratelimiter import RateLimiter
from src.ui.views import SubscribeView
from src.utils import group_items_by, create_embeds, modify_embeds


class CommandsCog(commands.Cog):
    def __init__(self, bot: MangaClient):
        self.bot: MangaClient = bot
        self.SCANLATORS: dict[str, ABCScan] = SCANLATORS
        self.rate_limiter: RateLimiter = RateLimiter()

    async def cog_load(self):
        self.bot.logger.info("Loaded Commands Cog...")
        self.bot.add_view(SubscribeView(self.bot))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        commands_to_check = [
            "subscribe",
        ]
        if str(interaction.command.qualified_name).split(" ")[0] not in commands_to_check:
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

    @app_commands.command(name="next_update_check", description="Get the time of the next update check.")
    async def next_update_check(self, interaction: discord.Interaction) -> None:
        # await interaction.response.defer(ephemeral=True, thinking=True)
        updates_cog: UpdateCheckCog | None = self.bot.get_cog("UpdateCheckCog")
        if not updates_cog:
            em = discord.Embed(
                title="Error",
                description="The update check cog is not loaded.",
                color=0xFF0000,
            )
            em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)
            return

        next_update_ts = int(updates_cog.check_updates_task.next_iteration.timestamp())
        em = discord.Embed(
            title="Next Update Check",
            description=(
                f"The next update check is scheduled for "
                f"<t:{next_update_ts}:T> (<t:{next_update_ts}:R>)."
            ),
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=em, ephemeral=True)

    subscribe = app_commands.Group(name="subscribe", description="Subscribe to a manga to get notifications.")

    @subscribe.command(name="new", description="Subscribe to a manga to get new release notifications.")
    @app_commands.describe(manga_url="The URL of the manga you want to subscribe to.")
    async def subscribe_new(self, interaction: discord.Interaction, manga_url: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        if RegExpressions.manganato_url.search(manga_url):
            scanlator = Manganato

            series_id = await Manganato.get_manga_id(self.bot, manga_url)
            series_url: str = Manganato.fmt_url.format(manga_id=series_id)

        elif (
                RegExpressions.aquamanga_url.search(manga_url) and
                self.bot.config["user-agents"][Aquamanga.name] is not None
        ):
            scanlator = Aquamanga

            url_name = RegExpressions.aquamanga_url.search(manga_url).group(1)
            series_url = Aquamanga.fmt_url.format(manga_url_name=url_name)
            series_id = await Aquamanga.get_manga_id(self.bot, series_url)

        # elif RegExpressions.voidscans_url.search(manga_url):
        #     scanlator = VoidScans
        #
        #     url_name = RegExpressions.voidscans_url.search(manga_url).group(1)
        #     series_url: str = VoidScans.fmt_url.format(manga_url_name=url_name)
        #     series_id = await VoidScans.get_manga_id(self.bot, series_url)

        elif RegExpressions.tritinia_url.search(manga_url):
            scanlator = TritiniaScans

            url_name = RegExpressions.tritinia_url.search(manga_url).group(1)
            series_url: str = TritiniaScans.base_url + url_name
            series_id = await TritiniaScans.get_manga_id(self.bot, series_url)

        elif (
                RegExpressions.toonily_url.search(manga_url)
                and self.bot.config["user-agents"][Toonily.name] is not None
        ):
            scanlator = Toonily

            url_name = RegExpressions.toonily_url.search(manga_url).group(1)
            series_url: str = Toonily.base_url + url_name
            series_id = await Toonily.get_manga_id(self.bot, series_url)

        elif RegExpressions.mangadex_url.search(manga_url):
            scanlator = MangaDex

            series_id = await MangaDex.get_manga_id(self.bot, manga_url)
            series_url: str = MangaDex.fmt_url.format(manga_id=series_id)

        elif RegExpressions.flamescans_url.search(manga_url):
            scanlator = FlameScans

            url_name = RegExpressions.flamescans_url.search(manga_url).group(1)
            series_url: str = FlameScans.fmt_url.format(manga_url_name=url_name)
            series_id = await FlameScans.get_manga_id(self.bot, series_url)

        elif RegExpressions.asurascans_url.search(manga_url):
            scanlator = AsuraScans

            url_name = RegExpressions.asurascans_url.search(manga_url).group(1)
            series_id = await AsuraScans.get_manga_id(self.bot, manga_url)
            series_url: str = AsuraScans.fmt_url.format(manga_id=series_id, manga_url_name=url_name)

        elif RegExpressions.reaperscans_url.search(manga_url):
            scanlator = ReaperScans

            url_name = RegExpressions.reaperscans_url.search(manga_url).group(2)
            series_id = await ReaperScans.get_manga_id(self.bot, manga_url)
            series_url: str = ReaperScans.fmt_url.format(manga_id=series_id, manga_url_name=url_name)

        elif RegExpressions.comick_url.search(manga_url):
            scanlator = Comick

            url_name = RegExpressions.comick_url.search(manga_url).group(1)
            series_id = await Comick.get_manga_id(self.bot, manga_url)
            series_url: str = Comick.fmt_url.format(manga_url_name=url_name)

        elif (
                RegExpressions.aniglisscans_url.search(manga_url) and
                self.bot.config["user-agents"][AniglisScans.name] is not None
        ):
            scanlator = AniglisScans

            url_name = RegExpressions.aniglisscans_url.search(manga_url).group(1)
            series_url: str = AniglisScans.fmt_url.format(manga_url_name=url_name)
            series_id = await AniglisScans.get_manga_id(self.bot, series_url)

        elif RegExpressions.luminousscans_url.search(manga_url):
            scanlator = LuminousScans

            series_id = await LuminousScans.get_manga_id(self.bot, manga_url)
            series_url: str = await LuminousScans.fmt_manga_url(self.bot, series_id, manga_url)

        elif RegExpressions.drakescans_url.search(manga_url):
            scanlator = DrakeScans

            url_name = RegExpressions.drakescans_url.search(manga_url).group(1)
            series_url: str = DrakeScans.fmt_url.format(manga_url_name=url_name)
            series_id = await DrakeScans.get_manga_id(self.bot, series_url)

        elif RegExpressions.nitroscans_url.search(manga_url):
            scanlator = NitroScans

            url_name = RegExpressions.nitroscans_url.search(manga_url).group(1)
            series_url: str = NitroScans.fmt_url.format(manga_url_name=url_name)
            series_id = await NitroScans.get_manga_id(self.bot, series_url)

        elif RegExpressions.mangapill_url.search(manga_url):
            scanlator = Mangapill

            series_id = await Mangapill.get_manga_id(self.bot, manga_url)
            series_url: str = await Mangapill.fmt_manga_url(self.bot, series_id, manga_url)

        elif RegExpressions.leviatanscans_url.search(manga_url):
            scanlator = LeviatanScans

            url_name = RegExpressions.leviatanscans_url.search(manga_url).group(1)
            series_url: str = LeviatanScans.fmt_url.format(manga_url_name=url_name)
            series_id = await LeviatanScans.get_manga_id(self.bot, series_url)

        elif RegExpressions.bato_url.search(manga_url):
            scanlator = Bato

            series_url: str = await Bato.fmt_manga_url(self.bot, None, manga_url)
            series_id = await Bato.get_manga_id(self.bot, series_url)

        else:
            em = discord.Embed(title="Invalid URL", color=discord.Color.red())
            em.description = (
                "The URL you provided does not follow any of the known url formats.\n"
                "See `/supported_websites` for a list of supported websites and their url formats."
            )
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        manga: Manga = await scanlator.make_manga_object(self.bot, series_id, series_url)

        if manga.completed:
            raise MangaCompletedOrDropped(series_url)

        await self.bot.db.add_series(manga)

        await self.bot.db.subscribe_user(
            interaction.user.id, interaction.guild_id, manga.id
        )

        embed = discord.Embed(
            title="Subscribed to Series",
            color=discord.Color.green(),
            description=f"Successfully subscribed to **[{manga.human_name}]({manga.url})!**",
        )
        embed.set_image(url=manga.cover_url)
        embed.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def manga_autocomplete(
            self: Any, interaction: discord.Interaction, current: str
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
            self: Any, _: discord.Interaction, current: str
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete for the /latest command"""
        # noinspection PyProtectedMember
        subs: list[Manga] = await self.bot.db._get_all_series_autocomplete(current)
        # subs = list(reversed(subs))
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

    @subscribe.command(
        name="delete", description="Unsubscribe from a currently subscribed manga."
    )
    @app_commands.describe(manga_id="The name of the manga.")
    @app_commands.autocomplete(manga_id=manga_autocomplete)
    @app_commands.rename(manga_id="manga")
    async def subscribe_delete(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        manga: Manga = await self.bot.db.get_series(manga_id)

        if not manga:
            em = discord.Embed(title="Invalid Manga", color=discord.Color.red())
            em.description = "The manga you provided is not in the database."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        await self.bot.db.unsub_user(interaction.user.id, manga_id)

        em = discord.Embed(title="Unsubscribed", color=discord.Color.green())
        em.description = f"Successfully unsubscribed from `{manga.human_name}`."
        em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.followup.send(embed=em, ephemeral=True)
        return

    @subscribe.command(name="list", description="List all the manga you're subscribed to.")
    async def subscribe_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        subs: list[Manga] = await self.bot.db.get_user_subs(interaction.user.id)
        subs = sorted(subs, key=lambda x: x.human_name)

        if not subs:
            em = discord.Embed(title="No Subscriptions", color=discord.Color.red())
            em.description = "You have no subscriptions."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        grouped = group_items_by(subs, ["scanlator"])
        embeds: list[discord.Embed] = []

        def _make_embed(subs_count: int) -> discord.Embed:
            return discord.Embed(
                title=f"Your Subscriptions ({subs_count})",
                description="",
                color=discord.Color.blurple()
            )

        num_subs = len(subs)

        em = _make_embed(num_subs)
        line_index = 0
        for manga_group in grouped:
            scanlator_title_added = False

            for manga in manga_group:
                line_index += 1
                to_add = f"**{line_index}.** [{manga.human_name}]({manga.url}) - {manga.last_chapter}\n"

                if not scanlator_title_added:
                    if len(em.description) + len(manga.scanlator) + 6 > 4096:
                        embeds.append(em)
                        em = _make_embed(num_subs)
                        em.description += f"**\n{manga.scanlator.title()}**\n"
                        scanlator_title_added = True
                    else:
                        em.description += f"**\n{manga.scanlator.title()}**\n"
                        scanlator_title_added = True

                if len(em.description) + len(to_add) > 4096:
                    embeds.append(em)
                    em = _make_embed(num_subs)

                em.description += to_add

                if line_index == num_subs:
                    embeds.append(em)

        view = PaginatorView(embeds, interaction)
        view.message = await interaction.followup.send(embed=embeds[0], view=view)

    @app_commands.command(
        name="latest", description="Get the latest chapter of a manga."
    )
    @app_commands.describe(manga_id="The name of the manga.")
    @app_commands.autocomplete(manga_id=latest_chapters_autocomplete)
    @app_commands.rename(manga_id="manga")
    async def latest_chapter(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        manga: Manga = await self.bot.db.get_series(manga_id)

        em = discord.Embed(title="Latest Chapter", color=discord.Color.green())
        em.description = (
            f"The latest chapter of `{manga.human_name}` is {manga.last_chapter}."
        )
        em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.followup.send(embed=em, ephemeral=True)
        return

    # @app_commands.command(
    #     name="last_chapter_read", description="Get the last chapter you read of a manga."
    # )
    # @app_commands.describe(manga_id="The name of the manga.")
    # @app_commands.autocomplete(manga_id=latest_chapters_autocomplete)
    # @app_commands.rename(manga_id="manga")
    # async def last_chapter_read(self, interaction: discord.Interaction, manga_id: str):
    #     await interaction.response.defer(ephemeral=True, thinking=True)
    #
    #     bookmark = await self.bot.db.get_user_bookmark(interaction.user.id, manga_id)
    #     if not bookmark:
    #         em = discord.Embed(title="No info available", color=discord.Color.red())
    #         em.description = f"You have not marked any chapters as read for this manga."
    #         em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
    #         return await interaction.followup.send(embed=em, ephemeral=True)
    #
    #     if len(bookmark.manga.available_chapters) - 1 > bookmark.last_read_chapter.index:
    #         next_available_chapter = bookmark.manga.available_chapters[bookmark.last_read_chapter.index + 1]
    #     elif bookmark.manga.completed:
    #         next_available_chapter = "`N/A (Manga is completed)`"
    #     else:
    #         next_available_chapter = "`Wait for updates`"
    #
    #     em = discord.Embed(title="Last Chapter Read", color=discord.Color.green())
    #     em.description = (
    #         f"The last chapter you read of `{bookmark.manga.human_name}` is {bookmark.last_read_chapter}.\n"
    #         f"Next chapter: {next_available_chapter}"
    #     )
    #     em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
    #
    #     await interaction.followup.send(embed=em, ephemeral=True)
    #     return

    @app_commands.command(
        name="chapters", description="Get a list of chapters for a manga."
    )
    @app_commands.describe(manga_id="The name of the manga.")
    @app_commands.autocomplete(manga_id=latest_chapters_autocomplete)
    @app_commands.rename(manga_id="manga")
    async def chapters(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        manga: Manga = await self.bot.db.get_series(manga_id)

        embeds = create_embeds(
            "{chapter}",
            [
                {"chapter": chapter}
                for chapter in manga.available_chapters],
            per_page=20,
        )
        modify_embeds(embeds,
                      title_kwargs={"title": f"Chapters for {manga.human_name}", "color": discord.Color.green()}
                      )

        view = PaginatorView(embeds, interaction)
        view.message = await interaction.followup.send(embed=embeds[0], view=view)

    @app_commands.command(
        name="supported_websites", description="Get a list of supported websites."
    )
    async def supported_websites(self, interaction: discord.Interaction) -> None:
        em = discord.Embed(title="Supported Websites", color=discord.Color.green())
        supp_webs = [
            ("MangaDex", "https://mangadex.org/", "https://mangadex.org/title/1b2c3d/"),
            ("Manganato", "https://manganato.com/", "https://manganato.com/manga-m123456"),
            ("Toonily", "https://toonily.com", "https://toonily.net/manga/manga-title/"),
            ("TritiniaScans", "https://tritinia.org", "https://tritinia.org/manga/manga-title/"),
            ("FlameScans", "https://flamescans.org/", "https://flamescans.org/series/manga-title/"),
            ("AsuraScans", "https://asurascans.com/", "https://asurascans.com/manga/manga-title/"),
            ("ReaperScans", "https://reaperscans.com/", "https://reaperscans.com/comics/12351-manga-title/"),
            ("Comick", "https://comick.app/", "https://comick.app/comic/manga-title/"),
            ("Luminous", "https://luminousscans.com/", "https://luminousscans.com/series/12351-manga-title/"),
            ("DrakeScans", "https://drakescans.com/", "https://drakescans.com/series/manga-title/"),
            ("NitroScans", "https://nitroscans.com/", "https://nitroscans.com/series/manga-title/"),
            ("Mangapill", "https://mangapill.com/", "https://mangapill.com/manga/12351/manga-title/"),
            ("LeviatanScans", "https://en.leviatanscans.com/", "https://en.leviatanscans.com/home/manga/manga-title/"),
            ("Bato.to", "https://bato.to/", "https://bato.to/series/12351/manga-title/"),
            ("OmegaScans", "https://omegascans.org/", "https://omegascans.org/series/manga-title/"),
            ("Void-Scans", "https://void-scans.com/", "https://void-scans.com/manga/manga-title/"),
            
            # Scanlators requiring user-agents
            ("AniglisScans", "https://anigliscans.com/", "https://anigliscans.com/series/manga-title/"),
            ("Aquamanga", "https://aquamanga.com/", "https://aquamanga.com/read/manga-title/"),
        ]
        supp_webs = sorted(supp_webs, key=lambda x: x[0])
        if self.bot.config.get('user-agents', {}).get(AniglisScans.name) is None:
            supp_webs.pop(-1)
        if self.bot.config.get('user-agents', {}).get(Aquamanga.name) is None:
            supp_webs.pop(-1)
        em.description = "Manga Updates Bot currently supports the following websites:\n"
        for name, url, _format in supp_webs:
            if name.lower() not in SCANLATORS:
                continue
            em.description += f"• [{name}]({url})\n"
            em.description += f"\u200b \u200b \u200b \↪ Format -> `{_format}`\n"

        em.description += "\n\n__**Note:**__"
        em.description += "\nMore websites will be added in the future. "
        em.description += "Don't forget to leave suggestions on websites I should add."

        em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.response.send_message(embed=em, ephemeral=True)
        return

    @app_commands.command(
        name="help", description="Get started with Manga Updates Bot."
    )
    async def help(self, interaction: discord.Interaction) -> None:
        em = discord.Embed(title="Manga Updates Bot", color=discord.Color.green())
        em.description = (
            "Manga Updates Bot is a bot that allows you to subscribe to your favorite manga and get notified "
            "when a new chapter is released.\n\n"
            "To get started, the bot needs to be set up first. This can be done by using the `/config setup` command.\n"
            "Note that this command can only be used by a server moderator that has the manage_channels/manage_roles "
            "permissions.\n\n"

            "**General Commands:**\n"
            "`/help` - Get started with Manga Updates Bot (this message).\n"
            "`/search` - Search for a manga on MangaDex.\n"
            "`/latest` - Get the latest chapter of a manga.\n"
            "`/chapters` - Get a list of chapters of a manga.\n"
            "`/last_chapter_read` - Get the last chapter you read.\n"
            "`/supported_websites` - Get a list of websites supported by the bot.\n\n"

            "**Subscription Commands:**\n"
            "`/subscribe new` - Subscribe to a manga.\n"
            "`/subscribe delete` - Unsubscribe from a manga.\n"
            "`/subscribe list` - List all your subscribed manga.\n\n"

            "**Bookmark Commands:**\n"
            "`/bookmark new` - Bookmark a manga.\n"
            "`/bookmark view` - View your bookmarked manga.\n"
            "`/bookmark delete` - Delete a bookmark.\n"
            "`/bookmark update` - Update a bookmark.\n\n"

            "**Config Commands:**\n"
            "`/config setup` - Set up the bot.\n"
            "`/config show` - Show the current configuration.\n"
            "`/config delete` - Delete the current configuration.\n\n"

            "**Permissions:**\n"
            "The bot needs the following permissions to function properly:\n"
            "• Send Messages\n"
            "• Embed Links\n"
            "• Manage Webhooks\n\n"
            "**Further Help:**\n"
            "If you need further help, you can join the [support server](https://discord.gg/EQ83EWW7Nu) and contact "
            ".mooshi - the bot developer.\n\n"
        )
        em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
        await interaction.response.send_message(embed=em, ephemeral=True)
        return

    @app_commands.command(
        name="search", description="Search for a manga on Mangadex."
    )
    @app_commands.describe(query="The name of the manga.")
    async def dex_search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if RegExpressions.mangadex_url.search(query) and (manga_id := await MangaDex.get_manga_id(self.bot, query)):
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
        synopsis = result["attributes"]["description"].get("en")
        if not synopsis:
            # If the synopsis is not available in English, use the first available language.
            synopsis = result["attributes"]["description"].values()[0]

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
    if bot.debug and bot.test_guild_id:
        await bot.add_cog(CommandsCog(bot), guild=discord.Object(id=bot.test_guild_id))
    else:
        await bot.add_cog(CommandsCog(bot))
