from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from src.ui import autocompletes

if TYPE_CHECKING:
    from src.core import MangaClient
    from src.ext.update_check import UpdateCheckCog

from discord import app_commands
from discord.ext import commands

from src.core.errors import GuildNotConfiguredError, MangaCompletedOrDropped, MangaNotTrackedError, CustomError
from src.core.scanners import *
from src.core.objects import Manga
from src.ui.views import SubscribeListPaginatorView, SubscribeView, PaginatorView, SupportView
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
        self.bot.add_view(SupportView())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        commands_to_check = [
            "subscribe",
            "track",
        ]
        if (
                str(interaction.command.qualified_name).split(" ")[0]
                not in commands_to_check
        ):
            return True

        if interaction.guild_id is None:
            em = Embed(
                bot=self.bot,
                title="Error",
                description="This command can only be used in a server.",
                color=0xFF0000,
            )
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
            return False

        elif await self.bot.db.get_guild_config(interaction.guild_id) is None:
            if interaction.command.qualified_name == "subscribe list":
                try:
                    if interaction.namespace["global"]:
                        return True
                except KeyError:
                    pass
            em = Embed(
                bot=self.bot,
                title="Error",
                description="This server has not been setup yet.\nUse `/config setup` to setup the bot.",
                color=0xFF0000,
            )
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
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
            em = Embed(
                bot=self.bot,
                title="Error",
                description="The update check cog is not loaded.",
                color=0xFF0000,
            )
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
            await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
            return

        next_update_ts = int(updates_cog.check_updates_task.next_iteration.timestamp())
        em = Embed(
            bot=self.bot,
            title="Next Update Check",
            description=(
                f"The next update check is scheduled for "
                f"<t:{next_update_ts}:T> (<t:{next_update_ts}:R>)."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=em, ephemeral=True)  # noqa

    track = app_commands.Group(
        name="track", description="(Mods) Start tracking a manga for the server to get notifications."
    )

    @track.command(
        name="new", description="Start tracking a manga for the server to get notifications."
    )
    @app_commands.describe(
        manga_url="The URL of the manga you want to track.",
        ping_role="The role to ping when a notification is sent."
    )
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.autocomplete(manga_url=autocompletes.manga)
    async def track_new(
            self, interaction: discord.Interaction, manga_url: str, ping_role: Optional[discord.Role] = None
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        scanlator: ABCScan | None = None

        error_em = Embed(
            bot=self.bot,
            title="Invalid URL",
            color=discord.Color.red(),
            description=(
                "The URL you provided does not follow any of the known url formats.\n"
                "See `/supported_websites` for a list of supported websites and their url formats."
            ),
        ).set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)

        if RegExpressions.url.search(manga_url):
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
                series_id = await scanlator.get_manga_id(manga_url)
                series_url = await scanlator.fmt_manga_url(series_id, manga_url)
            else:
                series_url = await scanlator.fmt_manga_url(None, manga_url)  # noqa
                series_id = await scanlator.get_manga_id(series_url)

            # request_url = scanlator.prep_request_url(series_id, series_url)

            manga: Manga | None = await respond_if_limit_reached(
                scanlator.make_manga_object(series_id, series_url), interaction
            )
            # manga: Manga = await scanlator.make_manga_object(self.bot, series_id, series_url)
            if manga == "LIMIT_REACHED":
                return  # Return because we already responded with the respond_if_limit_reached func above
            elif not manga:
                raise MangaNotFoundError(manga_url)
        else:
            manga = await self.bot.db.get_series(manga_url)

        if manga.completed:
            raise MangaCompletedOrDropped(manga.url)

        guild_config = await self.bot.db.get_guild_config(interaction.guild_id)
        if guild_config is None:
            raise GuildNotConfiguredError(interaction.guild_id)

        await self.bot.db.add_series(manga)  # add this series entry to the database if it isn't already

        if not ping_role:
            # check if the manga ID already has a ping role in DB
            ping_role_id = await self.bot.db.get_guild_manga_role_id(interaction.guild_id, manga.id)

            if ping_role_id is None:
                if guild_config.auto_create_role:  # should create and not specified
                    role_name = manga.human_name[:97] + "..." if len(manga.human_name) > 100 else manga.human_name
                    # try to find a role with that name already
                    existing_role = discord.utils.get(interaction.guild.roles, name=role_name)
                    if existing_role is not None:
                        ping_role = existing_role
                    else:
                        ping_role = await interaction.guild.create_role(name=role_name, mentionable=True)
                        await self.bot.db.add_bot_created_role(interaction.guild_id, ping_role.id)

        elif ping_role.is_bot_managed():
            return await interaction.followup.send(
                embed=(
                    Embed(
                        bot=self.bot,
                        title="Error",
                        description=(
                            "The role you provided is managed by a bot.\n"
                            "Please provide a role that is not managed by a bot and try again."
                        ),
                        color=discord.Color.red())),
            )

        elif ping_role >= interaction.guild.me.top_role:
            return await interaction.followup.send(
                embed=(
                    Embed(
                        bot=self.bot,
                        title="Error",
                        description=(
                            "The role you provided is higher than my top role.\n"
                            "Please move the role below my top role and try again."
                        ),
                        color=discord.Color.red())),
            )

        if ping_role:
            await self.bot.db.upsert_guild_sub_role(interaction.guild_id, manga.id, ping_role.id)
            description = f"Tracking **[{manga.human_name}]({manga.url}) ({ping_role.mention})** is successful!"
        else:
            await self.bot.db.upsert_guild_sub_role(interaction.guild_id, manga.id, None)
            description = f"Tracking **[{manga.human_name}]({manga.url})** is successful!"
        description += f"\nNew updates for this manga will be sent in {guild_config.notifications_channel.mention}"
        description += f"\n\n**Note:** You can change the role to ping with `/track update`."
        embed = Embed(
            bot=self.bot,
            title="Tracking Successful",
            color=discord.Color.green(),
            description=description,
        )
        embed.set_image(url=manga.cover_url)
        embed.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @track.command(
        name="update", description="Update a tracked manga for the server to get notifications."
    )
    @app_commands.describe(manga_id="The name of the manga.", role="The new role to ping.")
    @app_commands.autocomplete(manga_id=autocompletes.tracked_manga)
    @app_commands.rename(manga_id="manga")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def track_update(
            self, interaction: discord.Interaction, manga_id: str, role: Optional[discord.Role] = None
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        if not await self.bot.db.is_manga_tracked(interaction.guild_id, manga_id):
            raise MangaNotTrackedError(manga_id)

        if role is not None:
            if role.is_bot_managed():
                return await interaction.followup.send(
                    embed=(
                        Embed(
                            bot=self.bot,
                            title="Error",
                            description=(
                                "The role you provided is managed by a bot.\n"
                                "Please provide a role that is not managed by a bot and try again."
                            ),
                            color=discord.Color.red())),
                )

            elif role >= interaction.guild.me.top_role:
                return await interaction.followup.send(
                    embed=(
                        Embed(
                            bot=self.bot,
                            title="Error",
                            description=(
                                "The role you provided is higher than my top role.\n"
                                "Please move the role below my top role and try again."
                            ),
                            color=discord.Color.red())),
                )
            ping_role_id = await self.bot.db.get_guild_manga_role_id(interaction.guild_id, manga_id)
            if ping_role_id and ping_role_id == role.id:
                return await interaction.followup.send(
                    embed=(
                        Embed(
                            bot=self.bot,
                            title="Error",
                            description=(
                                "The role you provided is already the role for this manga."
                            ),
                            color=discord.Color.red())),
                )

            await self.bot.db.upsert_guild_sub_role(interaction.guild_id, manga_id, role.id)
        else:
            await self.bot.db.upsert_guild_sub_role(interaction.guild_id, manga_id, None)

        manga: Manga = await self.bot.db.get_series(manga_id)
        await interaction.followup.send(
            embed=(
                Embed(
                    bot=self.bot,
                    title="Success",
                    description=(
                        f"The role for {manga} has been updated to {role.mention if role else 'nothing'}."
                    ),
                    color=discord.Color.green()))
            .set_image(url=manga.cover_url)
        )

    @track.command(
        name="remove", description="Stop tracking a manga on this server."
    )
    @app_commands.describe(
        manga_id="The name of the manga.", delete_role="Whether to delete the role associated with the manhwa."
    )
    @app_commands.autocomplete(manga_id=autocompletes.tracked_manga)
    @app_commands.rename(manga_id="manga")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def track_remove(self, interaction: discord.Interaction, manga_id: str, delete_role: Optional[bool] = False):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        if not await self.bot.db.is_manga_tracked(interaction.guild_id, manga_id):
            raise MangaNotTrackedError(manga_id)

        if delete_role is True:
            role_id = await self.bot.db.get_guild_manga_role_id(interaction.guild_id, manga_id)
            if role_id is not None and (role := interaction.guild.get_role(role_id)):
                await role.delete(reason="Untracked a manga.")

        manga: Manga = await self.bot.db.get_series(manga_id)
        await self.bot.db.delete_manga_track_instance(interaction.guild_id, manga_id)
        await interaction.followup.send(
            embed=(
                Embed(
                    bot=self.bot,
                    title="Success",
                    description=(
                        f"Successfully stopped tracking {manga}."
                    ),
                    color=discord.Color.green())),
        )

    @track.command(
        name="list", description="List all the manga that are being tracked in this server."
    )
    async def track_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        tracked_manga: list[Manga] = await self.bot.db.get_all_guild_tracked_manga(interaction.guild_id)
        tracked_manga = sorted(tracked_manga, key=lambda x: x.human_name)

        if not tracked_manga:
            em = Embed(bot=self.bot, title="Nothing found", color=discord.Color.red())
            em.description = "There are no tracked manga in this server."
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        grouped = group_items_by(tracked_manga, ["scanlator"])
        embeds: list[discord.Embed] = []

        def _make_embed(subs_count: int) -> discord.Embed:
            return Embed(
                bot=self.bot,
                title=f"Tracked Manhwa ({subs_count})",
                description="",
                color=discord.Color.blurple(),
            )

        num_tracked = len(tracked_manga)

        em = _make_embed(num_tracked)
        line_index = 0
        for manga_group in grouped:
            scanlator_title_added = False

            for manga in manga_group:
                line_index += 1
                to_add = f"**{line_index}.** [{manga.human_name}]({manga.url}) - {manga.last_chapter}\n"

                if not scanlator_title_added:
                    if len(em.description) + len(manga.scanlator) + 6 > 4096:
                        embeds.append(em)
                        em = _make_embed(num_tracked)
                        em.description += f"**\n{manga.scanlator.title()}**\n"
                        scanlator_title_added = True
                    else:
                        em.description += f"**\n{manga.scanlator.title()}**\n"
                        scanlator_title_added = True

                if len(em.description) + len(to_add) > 4096:
                    embeds.append(em)
                    em = _make_embed(num_tracked)

                em.description += to_add

                if line_index == num_tracked:
                    embeds.append(em)

        view = PaginatorView(embeds, interaction)
        view.message = await interaction.followup.send(embed=embeds[0], view=view)

    subscribe = app_commands.Group(
        name="subscribe", description="Subscribe to a manga to get notifications."
    )

    @subscribe.command(
        name="new", description="Subscribe to a tracked manga to get new release notifications."
    )
    @app_commands.describe(manga_id="The name of the tracked manga you want to subscribe to.")
    @app_commands.rename(manga_id="manga")
    @app_commands.autocomplete(manga_id=autocompletes.tracked_manga)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def subscribe_new(
            self, interaction: discord.Interaction, manga_id: str
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        if RegExpressions.url.search(manga_id):
            input_url = manga_id
            scanlator = get_manga_scanlator_class(SCANLATORS, url=input_url)
            if scanlator is None:
                raise MangaNotFoundError(input_url)
            if scanlator.id_first:
                manga_id = await scanlator.get_manga_id(input_url)
            else:
                manga_url = await scanlator.fmt_manga_url("", input_url)
                manga_id = await scanlator.get_manga_id(manga_url)

        is_tracked = await self.bot.db.is_manga_tracked(interaction.guild_id, manga_id)
        manga = await self.bot.db.get_series(manga_id)
        if not manga:
            raise MangaNotFoundError(manga_id)
        elif not is_tracked:
            raise MangaNotTrackedError(manga_id)
        elif manga.completed:
            raise MangaCompletedOrDropped(manga.url)

        guild_config = await self.bot.db.get_guild_config(interaction.guild_id)
        if guild_config is None:
            raise GuildNotConfiguredError(interaction.guild_id)

        ping_role: discord.Role | None = None
        # check if the manga ID already has a ping role in DB
        ping_role_id = await self.bot.db.get_guild_manga_role_id(interaction.guild_id, manga.id)

        if ping_role_id is None:
            if guild_config.default_ping_role is not None:
                ping_role = guild_config.default_ping_role

        elif ping_role_id is not None:
            # try to get the role object
            ping_role = interaction.guild.get_role(ping_role_id)
            if ping_role is None:
                return await interaction.followup.send(
                    embed=(
                        Embed(
                            bot=self.bot,
                            title="Error",
                            description=(
                                "Even though the role exists in the server, the bot cannot find it?\n"
                                "Ask a moderator to double check my permissions and try again."
                            ),
                            color=discord.Color.red())),
                )

        await self.bot.db.subscribe_user(
            interaction.user.id, interaction.guild_id, manga.id
        )

        await interaction.user.add_roles(ping_role, reason="Subscribed to a manga.")

        description = f"Successfully subscribed to **{manga} ({ping_role.mention})!**"
        description += f"\n\nNew updates for this manga will be sent in {guild_config.notifications_channel.mention}"

        embed = Embed(
            bot=self.bot,
            title="Subscribed to Series",
            color=discord.Color.green(),
            description=description,
        )
        embed.set_image(url=manga.cover_url)
        embed.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @subscribe.command(
        name="delete", description="Unsubscribe from a currently subscribed manga."
    )
    @app_commands.describe(manga_id="The name of the manga.")
    @app_commands.autocomplete(manga_id=autocompletes.user_subbed_manga)
    @app_commands.rename(manga_id="manga")
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def subscribe_delete(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        manga: Manga = await self.bot.db.get_series(manga_id)
        if not manga:
            raise MangaNotFoundError(manga_id)

        ping_role_id = await self.bot.db.get_guild_manga_role_id(interaction.guild_id, manga.id)
        if ping_role_id:
            role = interaction.guild.get_role(ping_role_id)
            if role:
                if role >= interaction.guild.me.top_role:
                    raise CustomError("Target role is higher than my top role")
                await interaction.user.remove_roles(role, reason="Unsubscribed from a manga.")
        await self.bot.db.unsub_user(interaction.user.id, manga_id)

        em = Embed(bot=self.bot, title="Unsubscribed", color=discord.Color.green())
        em.description = f"Successfully unsubscribed from {manga}."
        em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)

        await interaction.followup.send(embed=em, ephemeral=True)
        return

    @subscribe.command(
        name="list", description="List all the manga you're subscribed to."
    )
    @app_commands.describe(_global="Whether to show your subscriptions in all servers.")
    @app_commands.rename(_global="global")
    async def subscribe_list(self, interaction: discord.Interaction, _global: Optional[bool] = False):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        if _global:
            subs: list[Manga] = await self.bot.db.get_user_subs(interaction.user.id)
        else:
            subs: list[Manga] = await self.bot.db.get_user_guild_subs(interaction.guild_id, interaction.user.id)
        subs = sorted(subs, key=lambda x: x.human_name)

        if not subs:
            em = Embed(bot=self.bot, title="No Subscriptions", color=discord.Color.red())
            em.description = "You have no subscriptions."
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        grouped = group_items_by(subs, ["scanlator"])
        embeds: list[discord.Embed] = []

        def _make_embed(subs_count: int) -> discord.Embed:
            return Embed(
                bot=self.bot,
                title=f"Your{' (Global)' if _global else ''} Subscriptions ({subs_count})",
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
        embeds = modify_embeds(embeds, show_page_number=True)
        has_untracked_manga = await self.bot.db.has_untracked_subbed_manga(
            interaction.user.id, interaction.guild_id if not _global else None
        )
        if has_untracked_manga:
            view = SubscribeListPaginatorView(embeds, interaction, _global=_global)
        else:
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
        if not manga:
            raise MangaNotFoundError(manga_id)
        em = Embed(bot=self.bot, title="Latest Chapter", color=discord.Color.green())
        em.description = (
            f"The latest chapter of {manga} is {manga.last_chapter}."
        )
        em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)

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
            footer_kwargs={
                "text": self.bot.user.display_name,
                "icon_url": self.bot.user.display_avatar.url
            }
        )

        view = PaginatorView(embeds, interaction)
        view.message = await interaction.followup.send(embed=embeds[0], view=view)

    @app_commands.command(
        name="supported_websites", description="Get a list of supported websites."
    )
    async def supported_websites(self, interaction: discord.Interaction) -> None:
        em = Embed(bot=self.bot, title="Supported Websites", color=discord.Color.green())
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
                "https://asuracomics.com",  # TODO: temp asura URL
                "https://asuracomics.com/manga/manga-title/",  # TODO: temp asura URL
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
                LSComic,
                "LSComic",
                "https://lscomic.com/",
                "https://lscomic.com/manga/manga-title/",
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
            (
                NightScans,
                "NightScans",
                "https://nightscans.net/",
                "https://nightscans.net/series/manga-title/",
            ),
            (
                SuryaScans,
                "SuryaScans",
                "https://suryascans.com/",
                "https://suryascans.com/manga/manga-title/",
            )
        ]
        supp_webs = sorted(supp_webs, key=lambda x: x[1])
        user_agents = self.bot.config.get("user-agents", {})
        em.description = (
            "Manhwa Updates Bot currently supports the following websites:\n"
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

        em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)

        await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
        return

    @app_commands.command(
        name="help", description="Get started with Manhwa Updates Bot."
    )
    async def help(self, interaction: discord.Interaction) -> None:
        em = Embed(bot=self.bot, title="Manhwa Updates Bot Help", color=discord.Color.green())
        em.description = (
            """
**Getting Started:**
- Before using the bot, you must configure it for your server:
  - `/settings` - See and edit all the bot's settings for your server. *(Requires the `Manage Server` permission)*
        
**Tracking Manhwa:**
*(Requires the "Manage Roles" permission)*
- Start receiving updates by tracking your favorite manhwa:
  - `/track new` - Begin tracking a new manhwa. Optionally, specify a "ping_role" to determine which role gets notified for updates.
  - `/track update` - Update the ping role for a tracked manhwa.
  - `/track remove` - Stop tracking a manhwa. Use the "delete_role" option to decide if the associated role should also be deleted.
  - `/track list` - View all manhwa being tracked on the server. *(Does not require "Manage Roles" permission)*

**Subscribing to Manhwa:**
- Once a manhwa is being tracked, users can subscribe to receive updates:
  - `/subscribe new` - Subscribe to a tracked manhwa.
  - `/subscribe delete` - Unsubscribe from a manhwa.
  - `/subscribe list` - View your subscribed manhwa. Use the "global" option to see subscriptions across all servers or just the current one.

**Bookmarking:**
- Manage and view your manga bookmarks:
  - `/bookmark new` - Bookmark a manga.
  - `/bookmark view` - View your bookmarked manga.
  - `/bookmark delete` - Delete a bookmark.
  - `/bookmark update` - Update a bookmark.

**General Commands:**
- `/help` - Get started with Manhwa Updates Bot (this message).
- `/search` - Search for a manga on MangaDex.
- `/latest` - Get the latest chapter of a manga.
- `/chapters` - Get a list of chapters of a manga.
- `/next_update_check` - Get the time until the next update check.
- `/supported_websites` - Get a list of websites supported by the bot and the bot status on them.
- `/translate` - Translate any text from one language to another.

**Permissions:**
- The bot requires the following permissions for optimal functionality:
  - Send Messages
  - Embed Links
  - Attach Files
  - Manage Webhooks
  - Manage Roles (for tracking commands)

Ensure the bot has these permissions for smooth operation.

**Support:**
- For further assistance or questions, join our [support server](https://discord.gg/TYkw8VBZkr) and contact the bot developer.
    """.strip()
        )
        em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=em, ephemeral=True, view=SupportView())  # noqa
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
        cannot_search_em = Embed(
            bot=self.bot,
            title="Error",
            description=(
                f"The bot cannot search on that website yet.\n"
                "Try searching with the manga name instead."
            ),
            color=discord.Color.red(),
        )
        no_results_em = Embed(
            bot=self.bot,
            title="Error",
            description=(
                f"No results were found for `{query}`.\n"
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
                em = await scanlator.search(query=query, as_em=True)
                if em is None:
                    return await interaction.followup.send(
                        embed=no_results_em, ephemeral=True
                    )
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
                em = await scanlator.search(query=query, as_em=True)
                if em is None:
                    return await interaction.followup.send(
                        embed=no_results_em, ephemeral=True
                    )
                await interaction.followup.send(embed=em, ephemeral=True, view=SubscribeView(self.bot))
            else:
                return await interaction.followup.send(
                    embed=cannot_search_em, ephemeral=True
                )
        else:
            results = [x for x in [
                await scanlator.search(query=query) for scanlator in SCANLATORS.values() if  # noqa
                hasattr(scanlator, "search")
            ] if x is not None]
            if not results:
                return await interaction.followup.send(
                    embed=no_results_em, ephemeral=True
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

        em = Embed(
            bot=self.bot,
            title="Translation Complete 🈳",
            description=f"Language: `{lang_from}` \⟶ `{lang_to}`"
        )
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
        em = Embed(
            bot=self.bot,
            title="Translation Complete 🈳",
            description=f"Language: `{lang_from}` \⟶ `{lang_to}`"
        )
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
        em = Embed(
            bot=self.bot,
            title="Translation Complete 🈳",
            description=f"Language: `{lang_from}` \⟶ `{lang_to}`"
        )
        em.add_field(name="📥 Input", value=f"```{text}```", inline=False)
        em.add_field(name="📤 Result",
                     value=f"```{translated}```", inline=False)
        await interaction.followup.send(embed=em, ephemeral=True)  # noqa


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_ids:
        await bot.add_cog(CommandsCog(bot), guilds=[discord.Object(id=x) for x in bot.test_guild_ids])
    else:
        await bot.add_cog(CommandsCog(bot))
