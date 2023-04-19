from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core import MangaClient

from discord import app_commands
from discord.ext import commands, tasks
import traceback as tb

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

        self.check_updates_task.add_exception_type(Exception)
        self.check_updates_task.start()

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

    @tasks.loop(hours=1.0)
    async def check_updates_task(self):
        self.bot.logger.info("Checking for updates...")
        try:
            series_to_delete: list[Manga] = await self.bot.db.get_series_to_delete()
            if series_to_delete:
                self.bot.logger.warning(
                    "Deleting the following series: ================="
                    + "\n".join(
                        f'({x.scanlator})' + x.human_name for x in series_to_delete
                    )
                )
                await self.bot.db.bulk_delete_series([m.id for m in series_to_delete])

            series_to_update: list[Manga] = await self.bot.db.get_series_to_update()

            if not series_to_update:
                return

            series_webhook_roles: list[tuple[str, str, str]] = await self.bot.db.get_series_webhook_role_pairs()

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

            for manga in series_to_update:
                if manga.completed:
                    self.bot.logger.warning(
                        f"({manga.scanlator}) {manga.human_name} ====> COMPLETED"
                    )

                scanner = self.SCANLATORS.get(manga.scanlator, None)
                if scanner is None:
                    self.bot.logger.warning(
                        f"Unknown scanlator {manga.scanlator} for {manga.human_name}. ID--{manga.id}"
                    )
                    log_em = discord.Embed(
                        title="Unknown Scanlator",
                        description=(f"```diff\n- Scanlator: {manga.scanlator}\n- Name: {manga.human_name}\n- "
                                     f"ID: {manga.id}```"
                                     )
                    )
                    log_em.set_footer(
                        text="Manga Updates Logs", icon_url=self.bot.user.avatar.url
                    )
                    await self.bot.log_to_discord(embed=log_em)
                    continue

                await self.rate_limiter.delay_if_necessary(manga)

                try:
                    update_check_result: ChapterUpdate = await scanner.check_updates(
                        self.bot, manga
                    )
                except Exception as e:
                    self.bot.logger.warning(
                        f"Error while checking for updates for {manga.human_name} ({manga.id})",
                        exc_info=e,
                    )
                    traceback = "".join(
                        tb.format_exception(type(e), e, e.__traceback__)
                    )
                    await self.bot.log_to_discord(f"Error when checking updates: {traceback}"[:-2000])
                    continue

                if not update_check_result.new_chapters and manga.cover_url == update_check_result.new_cover_url:
                    # self.bot._logger.info(f"No updates for {manga.human_name} ({manga.id})")
                    continue

                wh_n_role = series_webhooks_roles.get(manga.id, None)
                if wh_n_role is not None:

                    for webhook_url, role_id in wh_n_role["webhook_role_pairs"]:

                        webhook = discord.Webhook.from_url(
                            webhook_url, session=self.bot.session, client=self.bot
                        )

                        if webhook:

                            for i, new_chapter in enumerate(update_check_result.new_chapters):
                                manga.update(
                                    new_chapter, update_check_result.series_completed, update_check_result.new_cover_url
                                )

                                extra_kwargs = update_check_result.extra_kwargs[i] if len(
                                    update_check_result.extra_kwargs) > i else {}

                                self.bot.logger.info(
                                    f"Sending update for {manga.human_name} ====> Chapter {new_chapter.name} released!"
                                )

                                try:
                                    role_ping = "" if not role_id else f"<@&{role_id}> "
                                    await webhook.send(
                                        (
                                            f"{role_ping}**{manga.human_name}** **{new_chapter.name}**"
                                            f" has been released!\n{new_chapter.url}"
                                        ),
                                        allowed_mentions=discord.AllowedMentions(roles=True),
                                        **extra_kwargs
                                    )
                                    # await asyncio.sleep(1)
                                except discord.HTTPException as e:
                                    self.bot.logger.error(
                                        f"Failed to send update for {manga.human_name}| {new_chapter.name}", exc_info=e
                                    )
                        else:
                            self.bot.logger.error(f"Can't connect to webhook {webhook_url}")
                else:
                    self.bot.logger.warning(
                        f"No webhook found for ({manga.scanlator}) {manga.human_name} =====> updating silently"
                    )

                manga.update(
                    update_check_result.new_chapters[-1] if update_check_result.new_chapters else None,
                    update_check_result.series_completed,
                    update_check_result.new_cover_url
                )
                await self.bot.db.update_series(manga)
        except Exception as e:
            self.bot.logger.error("Error while checking updates", exc_info=e)
            traceback = "".join(
                tb.format_exception(type(e), e, e.__traceback__)
            )
            await self.bot.log_to_discord(("Error while checking updates:\n" + traceback)[:2000])
        self.bot.logger.info("Update check finished =================")

    @check_updates_task.before_loop
    async def before_check_updates_task(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="next_update_check", description="Get the time of the next update check.")
    async def next_update_check(self, interaction: discord.Interaction) -> None:
        # await interaction.response.defer(ephemeral=True, thinking=True)
        next_update_ts = int(self.check_updates_task.next_iteration.timestamp())
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

        elif RegExpressions.aquamanga_url.search(manga_url):
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

        elif RegExpressions.toonily_url.search(manga_url):
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

        elif RegExpressions.aniglisscans_url.search(manga_url):
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
            self, interaction: discord.Interaction, current: str
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete for the /unsubscribe command."""
        subs: list[Manga] = await self.bot.db.get_user_subs(
            interaction.user.id, current
        )
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

    async def latest_chapters_autocomplete(
            self, interaction: discord.Interaction, current: str
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete for the /latest command"""
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
        em.description = (
            """
            Manga Updates Bot currently supports the following websites:
            • [MangaDex](https://mangadex.org/)
             \u200b \u200b \u200b \↪ Format -> `https://mangadex.org/title/1b2c3d/`
            • [Manganato](https://manganato.com/)
            \u200b \u200b \u200b \↪ Format -> `https://manganato.com/manga-m123456` 
            • [Toonily](https://toonily.com)
            \u200b \u200b \u200b \↪ Format -> `https://toonily.net/manga/manga-title/`
            • [TritiniaScans](https://tritinia.org)
            \u200b \u200b \u200b \↪ Format -> `https://tritinia.org/manga/manga-title/`
            • [FlameScans](https://flamescans.org/)
            \u200b \u200b \u200b \↪ Format -> `https://flamescans.org/series/12351-manga-title/`
            • [AsuraScans](https://asurascans.com/)
            \u200b \u200b \u200b \↪ Format -> `https://asurascans.com/manga/12351-manga-title/`
            • [ReaperScans](https://reaperscans.com/)
            \u200b \u200b \u200b \↪ Format -> `https://reaperscans.com/comics/12351-manga-title/`
            • [AniglisScans](https://anigliscans.com/)
            \u200b \u200b \u200b \↪ Format -> `https://anigliscans.com/series/manga-title/`
            • [Comick](https://comick.app/)
            \u200b \u200b \u200b \↪ Format -> `https://comick.app/comic/manga-title/`
            • [Luminous](https://luminousscans.com/)
            \u200b \u200b \u200b \↪ Format -> `https://luminousscans.com/series/12351-manga-title/`
            • [DrakeScans](https://drakescans.com/)
            \u200b \u200b \u200b \↪ Format -> `https://drakescans.com/series/manga-title/`
            • [NitroScans](https://nitroscans.com/)
            \u200b \u200b \u200b \↪ Format -> `https://nitroscans.com/series/manga-title/`
            • [Mangapill](https://mangapill.com/)
            \u200b \u200b \u200b \↪ Format -> `https://mangapill.com/manga/12351/manga-title/`
            • [LeviatanScans](https://en.leviatanscans.com/)
            \u200b \u200b \u200b \↪ Format -> `https://en.leviatanscans.com/home/manga/manga-title/`
            •[Aquamanga](https://aquamanga.com/)
            \u200b \u200b \u200b \↪ Format -> `https://aquamanga.com/read/manga-title/`
            \n__**Note:**__
            More websites will be added in the future. Don't forget to leave suggestions on websites I should add.
            """

            # •[Void-Scans](https://void-scans.com/)
            # \u200b \u200b \u200b \↪ Format -> `https://void-scans.com/manga/manga-title/`
        )
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
            "Mooshi#6669 - the bot developer.\n\n"
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
    if bot._debug_mode and bot.test_guild_id:
        await bot.add_cog(CommandsCog(bot), guild=discord.Object(id=bot.test_guild_id))
    else:
        await bot.add_cog(CommandsCog(bot))
