from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from src.ui import autocompletes

if TYPE_CHECKING:
    from src.core import MangaClient
    from src.ext.update_check import UpdateCheckCog

from discord import app_commands
from discord.ext import commands

from src.core.errors import MangaCompletedOrDropped
from src.core.scanners import *
from src.core.objects import Manga
from src.ui.views import SubscribeView, PaginatorView
from src.ui.modals import InputModal
from src.utils import (
    group_items_by,
    create_embeds,
    modify_embeds,
    get_manga_scanlator_class,
    respond_if_limit_reached,
    translate
)


class CommandsCog(commands.Cog):
    def __init__(self, bot: MangaClient):
        self.bot: MangaClient = bot
        self.SCANLATORS: dict[str, ABCScan] = SCANLATORS

        ctx_menu_translate = app_commands.ContextMenu(
            name="Translate",
            callback=self.translate_context_menu
        )
        ctx_menu_translate_to = app_commands.ContextMenu(
            name="Translate to...",
            callback=self.translate_to_context_menu
        )
        self.bot.tree.add_command(ctx_menu_translate)
        self.bot.tree.add_command(ctx_menu_translate_to)

    async def cog_load(self):
        self.bot.logger.info("Loaded Commands Cog...")
        self.bot.add_view(SubscribeView(self.bot))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        commands_to_check = [
            "subscribe",
        ]
        if (
                str(interaction.command.qualified_name).split(" ")[0]
                not in commands_to_check
        ):
            return True
        if interaction.guild_id is None:
            em = discord.Embed(
                title="Error",
                description="This command can only be used in a server.",
                color=0xFF0000,
            )
            em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
            return False

        elif await self.bot.db.get_guild_config(interaction.guild_id) is None:
            em = discord.Embed(
                title="Error",
                description="This server has not been setup yet.",
                color=0xFF0000,
            )
            em.set_footer(text="Manga Bot", icon_url=self.bot.user.avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
            return False

        return True

    @app_commands.command(
        name="next_update_check", description="Get the time of the next update check."
    )
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
            await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
            return

        next_update_ts = int(updates_cog.check_updates_task.next_iteration.timestamp())
        em = discord.Embed(
            title="Next Update Check",
            description=(
                f"The next update check is scheduled for "
                f"<t:{next_update_ts}:T> (<t:{next_update_ts}:R>)."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=em, ephemeral=True)  # noqa

    subscribe = app_commands.Group(
        name="subscribe", description="Subscribe to a manga to get notifications."
    )

    @subscribe.command(
        name="new", description="Subscribe to a manga to get new release notifications."
    )
    @app_commands.describe(manga_url="The URL of the manga you want to subscribe to.")
    async def subscribe_new(
            self, interaction: discord.Interaction, manga_url: str
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        scanlator: ABCScan | None = None

        error_em = discord.Embed(
            title="Invalid URL",
            color=discord.Color.red(),
            description=(
                "The URL you provided does not follow any of the known url formats.\n"
                "See `/supported_websites` for a list of supported websites and their url formats."
            ),
        ).set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        for scan in self.SCANLATORS.values():
            if scan.rx.search(manga_url):
                scanlator = scan
                break

        if (
                scanlator is None
                or self.bot.config["user-agents"].get(scanlator.name, "N/A") is None
        ):
            await interaction.followup.send(embed=error_em, ephemeral=True)
            return

        if scanlator.id_first:
            series_id = await scanlator.get_manga_id(self.bot, manga_url)
            series_url = await scanlator.fmt_manga_url(self.bot, series_id, manga_url)
        else:
            series_url = await scanlator.fmt_manga_url(self.bot, None, manga_url)  # noqa
            series_id = await scanlator.get_manga_id(self.bot, series_url)

        manga: Manga | None = await respond_if_limit_reached(
            scanlator.make_manga_object(self.bot, series_id, series_url), interaction
        )
        # manga: Manga = await scanlator.make_manga_object(self.bot, series_id, series_url)
        if manga == "LIMIT_REACHED":
            return

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

    @subscribe.command(
        name="delete", description="Unsubscribe from a currently subscribed manga."
    )
    @app_commands.describe(manga_id="The name of the manga.")
    @app_commands.autocomplete(manga_id=autocompletes.user_subbed_manga)
    @app_commands.rename(manga_id="manga")
    async def subscribe_delete(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

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

    @subscribe.command(
        name="list", description="List all the manga you're subscribed to."
    )
    async def subscribe_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

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
                color=discord.Color.blurple(),
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
    @app_commands.autocomplete(manga_id=autocompletes.manga)
    @app_commands.rename(manga_id="manga")
    async def latest_chapter(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

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
    @app_commands.autocomplete(manga_id=autocompletes.manga)
    @app_commands.rename(manga_id="manga")
    async def chapters(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        manga: Manga = await self.bot.db.get_series(manga_id)

        embeds = create_embeds(
            "{chapter}",
            [{"chapter": chapter} for chapter in manga.available_chapters],
            per_page=20,
        )
        modify_embeds(
            embeds,
            title_kwargs={
                "title": f"Chapters for {manga.human_name}",
                "color": discord.Color.green(),
            },
        )

        view = PaginatorView(embeds, interaction)
        view.message = await interaction.followup.send(embed=embeds[0], view=view)

    @app_commands.command(
        name="supported_websites", description="Get a list of supported websites."
    )
    async def supported_websites(self, interaction: discord.Interaction) -> None:
        em = discord.Embed(title="Supported Websites", color=discord.Color.green())
        supp_webs = [
            (
                MangaDex,
                "MangaDex",
                "https://mangadex.org/",
                "https://mangadex.org/title/1b2c3d/",
            ),
            (
                Manganato,
                "Manganato",
                "https://manganato.com/",
                "https://manganato.com/manga-m123456",
            ),
            (
                TritiniaScans,
                "TritiniaScans",
                "https://tritinia.org",
                "https://tritinia.org/manga/manga-title/",
            ),
            (
                FlameScans,
                "FlameScans",
                "https://flamescans.org/",
                "https://flamescans.org/series/manga-title/",
            ),
            (
                Asura,
                "Asura",
                # "https://asura.gg/",
                # "https://asura.gg/manga/manga-title/",
                "https://asura.nacm.xyz",  # TODO: temp asura URL
                "https://asura.nacm.xyz/manga/manga-title/",  # TODO: temp asura URL
            ),
            (
                ReaperScans,
                "ReaperScans",
                "https://reaperscans.com/",
                "https://reaperscans.com/comics/12351-manga-title/",
            ),
            (
                Comick,
                "Comick",
                "https://comick.app/",
                "https://comick.app/comic/manga-title/",
            ),
            (
                LuminousScans,
                "Luminous",
                "https://luminousscans.com/",
                "https://luminousscans.com/series/12351-manga-title/",
            ),
            (
                DrakeScans,
                "DrakeScans",
                "https://drakescans.com/",
                "https://drakescans.com/series/manga-title/",
            ),
            (
                Mangabaz,
                "Mangabaz",
                "https://mangabaz.net/",
                "https://mangabaz.net/mangas/manga-title/",
            ),
            (
                Mangapill,
                "Mangapill",
                "https://mangapill.com/",
                "https://mangapill.com/manga/12351/manga-title/",
            ),
            (
                LeviatanScans,
                "LeviatanScans",
                "https://en.leviatanscans.com/",
                "https://en.leviatanscans.com/home/manga/manga-title/",
            ),
            (
                Bato,
                "Bato.to",
                "https://bato.to/",
                "https://bato.to/series/12351/manga-title/",
            ),
            (
                Toonily,
                "Toonily",
                "https://toonily.com",
                "https://toonily.net/manga/manga-title/",
            ),
            (
                OmegaScans,
                "OmegaScans",
                "https://omegascans.org/",
                "https://omegascans.org/series/manga-title/",
            ),
            (
                VoidScans,
                "VoidScans",
                "https://void-scans.com/",
                "https://void-scans.com/manga/manga-title/",
            ),
            # Scanlators requiring user-agents
            (
                AnigliScans,
                "AnigliScans",
                "https://anigliscans.com/",
                "https://anigliscans.com/series/manga-title/",
            ),
            (
                Aquamanga,
                "Aquamanga",
                "https://aquamanga.com/",
                "https://aquamanga.com/read/manga-title/",
            ),
        ]
        supp_webs = sorted(supp_webs, key=lambda x: x[1])
        user_agents = self.bot.config.get("user-agents", {})
        em.description = (
            "Manga Updates Bot currently supports the following websites:\n"
        )

        for scanlator, name, url, _format in supp_webs:
            # Only remove those that are SET to None in user-agents in config or not in SCANLATORS
            if (
                    scanlator.name not in SCANLATORS
                    or user_agents.get(scanlator.name, True) is None
            ):
                continue
            if scanlator.last_known_status:
                status_code = scanlator.last_known_status[0]
                status_ts = int(scanlator.last_known_status[1])
            else:
                status_code = "N/A"
                status_ts = int(datetime.now().timestamp())

            status_str = (
                "OK" if status_code == 200 else
                "Rate-Limited" if status_code == 429 else
                "Temp-Banned" if status_code == 403 else "Unknown"
            )
            em.description += f"• [{name}]({url}) (`{status_code}:` {status_str} @ <t:{status_ts}:R>)\n"
            em.description += f"\u200b \u200b \u200b \↪ Format -> `{_format}`\n"

        em.description += "\n\n__**Note:**__"
        em.description += "\nMore websites will be added in the future. "
        em.description += "Don't forget to leave suggestions on websites I should add."

        em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
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
            "`/next_update_check` - Get the time until the next update check.\n"
            "`/supported_websites` - Get a list of websites supported by the bot and the bot status on them.\n\n"
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
            "**Miscellaneous Commands:**\n"
            "`/translate` - Translate with Google between languages.\n\n"
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
        await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
        return

    @app_commands.command(
        name="search",
        description="Search for a manga on on all/one scanlator of choice.",
    )
    @app_commands.describe(query="The name of the manga.")
    @app_commands.describe(scanlator_website="The website to search on.")
    @app_commands.rename(scanlator_website="scanlator")
    @app_commands.autocomplete(scanlator_website=autocompletes.scanlator)
    async def search(
            self,
            interaction: discord.Interaction,
            query: str,
            scanlator_website: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=False)  # noqa
        cannot_search_em = discord.Embed(
            title="Error",
            description=(
                f"The bot cannot search on that website yet.\n"
                "Try searching with the manga name instead."
            ),
            color=discord.Color.red(),
        )
        if RegExpressions.url.search(
                query
        ):  # if the query is a URL, try to get the manga from the URL
            scanlator = get_manga_scanlator_class(SCANLATORS, url=query)
            if scanlator is None:
                return await interaction.followup.send(
                    f"Could not find a manga on `{query}`.", ephemeral=True
                )
            if hasattr(scanlator, "search"):
                em = await scanlator.search(self.bot, query=query, as_em=True)
                view = SubscribeView(self.bot)
                return await interaction.followup.send(embed=em, ephemeral=True, view=view)
            else:
                return await interaction.followup.send(
                    embed=cannot_search_em, ephemeral=True
                )
        elif scanlator_website:
            scanlator = SCANLATORS.get(scanlator_website.lower())
            if not scanlator:
                return await interaction.followup.send(
                    f"Could not find a scanlator with the name `{scanlator_website}`.",
                    ephemeral=True,
                )
            if hasattr(scanlator, "search"):
                em = await scanlator.search(self.bot, query=query, as_em=True)
                await interaction.followup.send(embed=em, ephemeral=True, view=SubscribeView(self.bot))
            else:
                return await interaction.followup.send(
                    embed=cannot_search_em, ephemeral=True
                )
        else:
            results = [x for x in [
                await scanlator.search(self.bot, query=query) for scanlator in SCANLATORS.values() if  # noqa
                hasattr(scanlator, "search")
            ] if x is not None]
            if not results:
                return await interaction.followup.send(
                    f"No results were found for `{query}`", ephemeral=True
                )
            else:
                view = SubscribeView(self.bot, items=results, author_id=interaction.user.id)
                await interaction.followup.send(embed=results[0], view=view, ephemeral=False)
                return

    @app_commands.command(name="translate", description="Translate any text from one language to another")
    @app_commands.describe(text="The text to translate", to="The language to translate to",
                           from_="The language to translate from")
    @app_commands.rename(from_="from")
    @app_commands.autocomplete(to=autocompletes.google_language, from_=autocompletes.google_language)
    async def translate_slash(self, interaction: discord.Interaction, text: str, to: Optional[str],
                              from_: Optional[str] = None):
        if not from_:
            from_ = "auto"

        if not to:
            to = "en"

        if len(text) > 2000:
            return await interaction.response.send_message(  # noqa
                "The text is too long to translate. Max character limit is 2000.", ephemeral=True)

        translated, from_ = await translate(self.bot.session, text, from_, to)

        lang_from = "Unknown"
        lang_to = "Unknown"
        for lang in Constants.google_translate_langs:
            if lang["code"] == from_:
                lang_from = lang["language"]
            if lang["code"] == to:
                lang_to = lang["language"]

        em = discord.Embed(title="Translation Complete 🈳",
                           description=f"Language: `{lang_from}` \⟶ `{lang_to}`")
        em.add_field(name="📥 Input", value=f"```{text}```", inline=False)
        em.add_field(name="📤 Result",
                     value=f"```{translated}```", inline=False)
        await interaction.response.send_message(embed=em, ephemeral=True)  # noqa

    # used for the context menu ('Translate with Google')
    async def translate_context_menu(self, interaction: discord.Interaction, message: discord.Message):
        from_ = "auto"
        to = "en"
        text = message.content
        if len(text) > 2000:
            return await interaction.response.send_message(  # noqa
                "The text is too long to translate. Max character limit is 2000.", ephemeral=True)

        translated, from_ = await translate(self.bot.session, text, from_, to)
        lang_from = "Unknown"
        lang_to = "Unknown"
        for lang in Constants.google_translate_langs:
            if lang["code"] == from_:
                lang_from = lang["language"]
            if lang["code"] == to:
                lang_to = lang["language"]
        em = discord.Embed(title="Translation Complete 🈳",
                           description=f"Language: `{lang_from}` \⟶ `{lang_to}`")
        em.add_field(name="📥 Input", value=f"```{text}```", inline=False)
        em.add_field(name="📤 Result",
                     value=f"```{translated}```", inline=False)
        await interaction.response.send_message(embed=em, ephemeral=True)  # noqa

    # used for the context menu ('Translate with Google to')
    async def translate_to_context_menu(self, interaction: discord.Interaction, message: discord.Message):
        modal = InputModal()
        await interaction.response.send_modal(modal)  # noqa
        await modal.wait()
        if modal.language is None:
            return await interaction.followup.send("You didn't select a language.", ephemeral=True)
        from_ = "auto"
        to = modal.language
        text = message.content
        if len(text) > 2000:
            return await interaction.response.send_message(  # noqa
                "The text is too long to translate. Max character limit is 2000.", ephemeral=True)
        translated, from_ = await translate(self.bot.session, text, from_, to["code"])
        lang_from = "Unknown"
        lang_to = "Unknown"
        for lang in Constants.google_translate_langs:
            if lang["code"] == from_:
                lang_from = lang["language"]
            if lang["code"] == to:
                lang_to = lang["language"]
        em = discord.Embed(title="Translation Complete 🈳",
                           description=f"Language: `{lang_from}` \⟶ `{lang_to}`")
        em.add_field(name="📥 Input", value=f"```{text}```", inline=False)
        em.add_field(name="📤 Result",
                     value=f"```{translated}```", inline=False)
        await interaction.followup.send(embed=em, ephemeral=True)  # noqa


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_id:
        await bot.add_cog(CommandsCog(bot), guild=discord.Object(id=bot.test_guild_id))
    else:
        await bot.add_cog(CommandsCog(bot))
