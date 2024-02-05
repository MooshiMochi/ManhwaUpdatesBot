from __future__ import annotations

import asyncio
from typing import Any, Coroutine, Optional, TYPE_CHECKING

from src.core.scanlators.classes import AbstractScanlator
from src.static import Constants, Emotes, RegExpressions
from src.ui import autocompletes

if TYPE_CHECKING:
    from src.core import MangaClient
    from src.ext.update_check import UpdateCheckCog

from discord import app_commands
from discord.ext import commands
import discord

from src.core import errors, checks
from src.core.scanlators import scanlators
from src.core.objects import Manga, SubscriptionObject
from src.ui.views import ConfirmView, SubscribeListPaginatorView, SubscribeView, PaginatorView, SupportView
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

    @app_commands.command(
        name="next_update_check", description="Get the time of the next update check."
    )
    @checks.has_premium(dm_only=True)
    async def next_update_check(self, interaction: discord.Interaction) -> None:
        # await interaction.response.defer(ephemeral=True, thinking=True)
        updates_cog: UpdateCheckCog | None = self.bot.get_cog("UpdateCheckCog")
        if not updates_cog:
            em = discord.Embed(
                title="Error",
                description="The update check cog is not loaded.",
                color=0xFF0000,
            )
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
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
    @checks.bot_has_permissions(manage_roles=True)
    @checks.has_permissions(manage_roles=True)
    @checks.has_premium(dm_only=True)
    @app_commands.autocomplete(manga_url=autocompletes.track_new_cmd)
    async def track_new(
            self, interaction: discord.Interaction, manga_url: str, ping_role: Optional[discord.Role] = None
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        invoked_in_dm: bool = interaction.guild_id is None
        if (_result := RegExpressions.url.search(manga_url)) is not None:
            manga_url = _result.group(0)
            scanlator = get_manga_scanlator_class(scanlators, manga_url)
            if scanlator is None or self.bot.config["user-agents"].get(scanlator.name, "N/A") is None:
                raise errors.UnsupportedScanlatorURLFormatError(manga_url)
            # get the manga id
            manga_id = await scanlator.get_id(manga_url)
            is_tracked: bool = await self.bot.db.is_manga_tracked(manga_id, scanlator.name)
            manga: Manga | None = await respond_if_limit_reached(
                scanlator.make_manga_object(manga_url, load_from_db=is_tracked), interaction
            )
            if manga == "LIMIT_REACHED":
                return  # Return because we already responded with the respond_if_limit_reached func above
        else:
            try:
                manga_id, scanlator_name = manga_url.split("|")
                scanlator = get_manga_scanlator_class(scanlators, key=scanlator_name)
                if not scanlator:
                    raise errors.UnsupportedScanlatorURLFormatError(manga_url)
            except ValueError:
                raise errors.UnsupportedScanlatorURLFormatError(manga_url)
            manga: Manga = await self.bot.db.get_series(manga_id, scanlator_name)

        if not manga:
            raise errors.MangaNotFoundError(manga_url)

        elif manga.completed:
            raise errors.MangaCompletedOrDropped(manga.url)

        await self.bot.db.add_series(manga)  # add this series entry to the database if it isn't already

        if invoked_in_dm:
            await self.bot.db.upsert_guild_sub_role(interaction.user.id, manga.id, manga.scanlator, None)
            description = (f"Successfully tracked **{manga}**!\nPlease make sure your DMs are open to receive "
                           f"notifications.")
        else:
            # do the role, config and other stuff here
            guild_config = await self.bot.db.get_guild_config(interaction.guild_id)
            if not guild_config:
                raise errors.GuildNotConfiguredError(interaction.guild_id)

            if ping_role is not None:
                invalid_role_reason: str = ""
                if ping_role.is_bot_managed():
                    invalid_role_reason = (
                        "The role you provided is managed by a bot.\n"
                        "Please provide a role that is not managed by a bot and try again."
                    )
                elif ping_role >= interaction.guild.me.top_role:
                    invalid_role_reason = (
                        "The role you provided is higher than my top role.\n"
                        "Please move the role below my top role and try again."
                    )
                if invalid_role_reason != "":
                    return await interaction.followup.send(
                        embed=discord.Embed(title="Error", description=invalid_role_reason, color=discord.Color.red()),
                    )

            elif guild_config.auto_create_role is True:
                if len(manga.title) + len(manga.scanlator) + 3 <= 100:  # 3: 1 space + 2 brackets
                    role_name = f"{manga.title} ({manga.scanlator})"
                else:
                    role_name = manga.title[:100 - 6 - len(manga.scanlator)] + f"... ({manga.scanlator})"
                role_exists = discord.utils.get(interaction.guild.roles, name=role_name)
                if role_exists:
                    ping_role = role_exists
                else:
                    ping_role = await interaction.guild.create_role(
                        name=role_name, mentionable=False, reason="Created a role for a tracked manga.",
                    )
                    await self.bot.db.add_bot_created_role(interaction.guild_id, ping_role.id)

            if ping_role is not None:
                description = f"Tracking **[{manga.title}]({manga.url}) ({ping_role.mention})** is successful!"
                ping_role_id = ping_role.id
            else:
                description = f"Tracking **[{manga.title}]({manga.url})** is successful!"
                ping_role_id = None
            description += f"\nNew updates for this manga will be sent in {guild_config.notifications_channel.mention}"
            description += f"\n\n**Note:** You can change the role to ping with `/track update`."

            await self.bot.db.upsert_guild_sub_role(interaction.guild_id, manga.id, manga.scanlator, ping_role_id)

        embed = discord.Embed(
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
    @checks.has_permissions(manage_roles=True)
    @checks.bot_has_permissions(manage_roles=True)
    @checks.has_premium(dm_only=True)
    async def track_update(
            self, interaction: discord.Interaction, manga_id: str, role: Optional[discord.Role] = None
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        if not interaction.guild_id:  # dm channel
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="Apologies for the interruption...",
                    description="Hey! This command won't have any use in a DM channel since roles cannot be used here "
                                "anyways!\nI took the liberty of cancelling this command 🥰.",
                    color=discord.Color.yellow()
                )
            )
        try:
            manga_id, scanlator_name = manga_id.split("|")
        except ValueError:
            raise errors.MangaNotSubscribedError(manga_id)
        manga: Manga = await self.bot.db.get_series(manga_id, scanlator_name)
        if not manga:
            raise errors.MangaNotFoundError(manga_id)

        if not await self.bot.db.is_manga_tracked(manga.id, manga.scanlator, interaction.guild_id):
            raise errors.MangaNotTrackedError(manga_id)

        if role is not None:
            if role.is_bot_managed():
                return await interaction.followup.send(
                    embed=(
                        discord.Embed(
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
                        discord.Embed(
                            title="Error",
                            description=(
                                "The role you provided is higher than my top role.\n"
                                "Please move the role below my top role and try again."
                            ),
                            color=discord.Color.red())),
                )
            ping_role_id = await self.bot.db.get_guild_manga_role_id(interaction.guild_id, manga.id, manga.scanlator)
            if ping_role_id and ping_role_id == role.id:
                return await interaction.followup.send(
                    embed=(
                        discord.Embed(
                            title="Error",
                            description=(
                                "The role you provided is already the role for this manga."
                            ),
                            color=discord.Color.red())),
                )

            await self.bot.db.upsert_guild_sub_role(interaction.guild_id, manga.id, manga.scanlator, role.id)
        else:
            await self.bot.db.upsert_guild_sub_role(interaction.guild_id, manga_id, manga.scanlator, None)

        await interaction.followup.send(
            embed=(
                discord.Embed(
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
    @checks.has_permissions(manage_roles=True)
    @checks.bot_has_permissions(manage_roles=True)
    @checks.has_premium(dm_only=True)
    async def track_remove(self, interaction: discord.Interaction, manga_id: str, delete_role: Optional[bool] = False):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        try:
            manga_id, scanlator_name = manga_id.split("|")
        except ValueError:
            raise errors.MangaNotTrackedError(manga_id)

        if not await self.bot.db.is_manga_tracked(manga_id, scanlator_name, interaction.guild_id):
            raise errors.MangaNotTrackedError(manga_id)

        manga: Manga = await self.bot.db.get_series(manga_id, scanlator_name)
        if not manga:
            raise errors.MangaNotFoundError(manga_id)

        deleted_role_name: str | None = None
        if delete_role is True:
            role_id = await self.bot.db.get_guild_manga_role_id(interaction.guild_id, manga.id, manga.scanlator)
            if role_id is not None and (role := interaction.guild.get_role(role_id)):
                await role.delete(reason="Untracked a manga.")
                deleted_role_name = role.name
        await self.bot.db.delete_manga_track_instance(interaction.guild_id, manga.id, manga.scanlator)
        description = f"Successfully stopped tracking {manga}"
        if deleted_role_name is not None:
            description += f" and deleted the @{deleted_role_name} role"
        await interaction.followup.send(
            embed=(
                discord.Embed(title="Success", description=f"{description}.", color=discord.Color.green()))
        )

    @track.command(
        name="list", description="List all the manga that are being tracked in this server."
    )
    async def track_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        tracked_manga: list[Manga] = await self.bot.db.get_all_guild_tracked_manga(
            interaction.guild_id or interaction.user.id
        )
        tracked_manga = sorted(tracked_manga, key=lambda x: x.title)

        if not tracked_manga:
            em = discord.Embed(title="Nothing found", color=discord.Color.red())
            em.description = "There are no tracked manga in this server."
            if not interaction.guild_id:
                em.description = "You are not tracking any manga."
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        grouped = group_items_by(tracked_manga, ["scanlator"])
        embeds: list[discord.Embed] = []

        def _make_embed(subs_count: int) -> discord.Embed:
            return discord.Embed(
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
                to_add = f"**{line_index}.** [{manga.title}]({manga.url}) - {manga.last_chapter}\n"

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
    @app_commands.autocomplete(manga_id=autocompletes.subscribe_new_cmd)
    @checks.bot_has_permissions(manage_roles=True)
    @checks.has_premium(dm_only=True)
    async def subscribe_new(
            self, interaction: discord.Interaction, manga_id: str
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        is_all_sub: bool = manga_id == f"{interaction.guild_id or interaction.user.id}-all"
        is_dm_invoked: bool = interaction.guild_id is None

        guild_config = await self.bot.db.get_guild_config(interaction.guild_id)
        if guild_config is None and not is_dm_invoked:
            raise errors.GuildNotConfiguredError(interaction.guild_id)

        if is_all_sub:
            if (not is_dm_invoked and guild_config.default_ping_role and
                    not guild_config.default_ping_role.is_assignable()):
                raise errors.CustomError(
                    f"I cannot assign the {guild_config.default_ping_role.mention} role.\n"
                    "Double check my permissions and role hierarchy and try again!"
                )
            unsubbed_series: list[SubscriptionObject] = await self.bot.db.get_all_user_unsubbed_tracked_series(
                interaction.guild_id or interaction.user.id, interaction.user.id, interaction.guild
            )
            if is_dm_invoked and not unsubbed_series:
                raise errors.AlreadySubscribedError(all=True)
            bypass_prompt = False
            if (not unsubbed_series and guild_config.default_ping_role and guild_config.default_ping_role not in
                    interaction.user.roles and guild_config.default_ping_role.is_assignable()):
                unsubbed_series = [
                    SubscriptionObject(
                        interaction.user.id, interaction.guild_id or interaction.user.id,
                        "@mooshi/BOT", "L Argument", guild_config.default_ping_role.id
                    )
                ]
                bypass_prompt = True  # bypass prompt if it's just adding the default role
            prompt_msg = f"You are about to subscribe to an additional **{len(unsubbed_series)}** tracked series "
            prompt_msg += "from this server.\n\n**Do you wish to continue?**"

            view = ConfirmView(self.bot, interaction)
            _continue: bool = await view.prompt(interaction, prompt_msg, edit_original_response=True,
                                                ephemeral=True)
            if not _continue and not bypass_prompt:
                await interaction.edit_original_response(
                    embed=discord.Embed(title="Operation cancelled!", colour=discord.Color.green()), view=None
                )
                return
            successes, fails = await SubscriptionObject.sub_to_all(self.bot, unsubbed_series)
            if bypass_prompt:
                success_msg = f"You have been given the {guild_config.default_ping_role.mention} role!"
            else:
                success_msg = f"You have successfully subscribed to {successes} series!"
            if fails:
                success_msg += f"\n\n**Note:** I was unable to subscribe to {fails} series because I cannot assign " \
                               f"the role(s) to you!\nDouble check my permissions and role hierarchy and try again!"
            em = discord.Embed(title="Subscribed", color=discord.Color.green(), description=success_msg)
            em.colour = discord.Colour.green() if not fails else discord.Colour.orange()
            await interaction.edit_original_response(embed=em, view=None)
            return

        else:
            if RegExpressions.url.search(manga_id):
                input_url = manga_id
                scanlator = get_manga_scanlator_class(scanlators, url=input_url)
                if scanlator is None:
                    raise errors.UnsupportedScanlatorURLFormatError(input_url)
                manga_id = await scanlator.get_id(raw_url=manga_id)
            else:
                try:
                    manga_id, scanlator_name = manga_id.split("|")
                    scanlator = get_manga_scanlator_class(scanlators, key=scanlator_name)
                    if not scanlator:
                        raise errors.UnsupportedScanlatorURLFormatError(manga_id)
                except ValueError:
                    raise errors.MangaNotFoundError(manga_id)
            is_tracked = await self.bot.db.is_manga_tracked(
                manga_id, scanlator.name, interaction.guild_id or interaction.user.id
            )
            manga = await self.bot.db.get_series(manga_id, scanlator.name)
            if not manga:
                raise errors.MangaNotFoundError(manga_id)
            elif not is_tracked:
                raise errors.MangaNotTrackedError(manga_id)
            elif manga.completed:
                raise errors.MangaCompletedOrDropped(manga.url)

            # check if the manga ID already has a ping role in DB
            description = f"Successfully subscribed to **{manga}"
            if not is_dm_invoked:
                ping_role_id = await self.bot.db.get_guild_manga_role_id(interaction.guild_id, manga.id,
                                                                         manga.scanlator)
                ping_role = interaction.guild.get_role(ping_role_id)
                if ping_role is not None and ping_role not in interaction.user.roles:
                    if not ping_role.is_assignable():
                        raise errors.CustomError(
                            f"I cannot assign the {ping_role.mention} role.\n"
                            "Double check my permissions and role hierarchy and try again!"
                        )
                    await interaction.user.add_roles(ping_role, reason="Subscribed to a manga.")
                description += f" ({ping_role.mention})!**" if ping_role else "!**"
                description += (f"\n\nNew updates for this manga will be sent in "
                                f"{guild_config.notifications_channel.mention}")
            else:
                description += "!**\n\nYou will receive updates for this manhwa in your DMs."

            await self.bot.db.subscribe_user(
                interaction.user.id, interaction.guild_id or interaction.user.id, manga.id, manga.scanlator
            )

            embed = discord.Embed(title="Subscribed to Series", color=discord.Color.green(), description=description)
            embed.set_image(url=manga.cover_url)
            embed.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
            await interaction.followup.send(embed=embed, ephemeral=True)

    @subscribe.command(
        name="delete", description="Unsubscribe from a currently subscribed manga."
    )
    @app_commands.describe(manga_id="The name of the manga.")
    @app_commands.autocomplete(manga_id=autocompletes.subscribe_delete_command)
    @app_commands.rename(manga_id="manga")
    @checks.bot_has_permissions(manage_roles=True)
    @checks.has_premium(dm_only=True)
    async def subscribe_delete(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        is_all_unsub: bool = manga_id == f"{interaction.guild_id or interaction.user.id}-all"
        is_dm_invoked: bool = interaction.guild_id is None
        guild_config = await self.bot.db.get_guild_config(interaction.guild_id)

        if guild_config is None and not is_dm_invoked:
            raise errors.GuildNotConfiguredError(interaction.guild_id)

        if is_all_unsub:
            if (not is_dm_invoked and guild_config.default_ping_role and
                    not guild_config.default_ping_role.is_assignable()):
                raise errors.CustomError(
                    f"I cannot remove the {guild_config.default_ping_role.mention} role from you.\n"
                    "Double check my permissions and role hierarchy and try again!"
                )

            subbed_series: list[SubscriptionObject] = await self.bot.db.get_all_user_subbed_series(
                interaction.guild_id or interaction.user.id, interaction.user.id, interaction.guild)
            if is_dm_invoked and not subbed_series:
                raise errors.AlreadyUnsubscribedError(all=True)

            bypass_prompt = False

            if not subbed_series:
                # create fake Sub objects with the role_ids to delete
                db_role_ids = await self.bot.db.get_guild_tracked_role_ids(interaction.guild_id or interaction.user.id)
                roles: list[discord.Role] = list(filter(
                    lambda x: x is not None and x in interaction.user.roles and
                              x != guild_config.default_ping_role,
                    [interaction.guild.get_role(role_id) for role_id in set(db_role_ids)]))

                subbed_series = [
                    SubscriptionObject(
                        interaction.user.id, interaction.guild_id or interaction.user.id,
                        "@mooshi/BOT", "L Argument", role
                    ) for role in roles if role.is_assignable()
                ]
                bypass_prompt = True

            prompt_msg = f"You are about to unsubscribe from **{len(subbed_series)}** subbed series "
            prompt_msg += "from this server.\n\n**Do you wish to continue?**"

            view = ConfirmView(self.bot, interaction)
            _continue: bool = await view.prompt(interaction, prompt_msg, edit_original_response=True, ephemeral=True)
            if not _continue and not bypass_prompt:
                await interaction.edit_original_response(
                    embed=discord.Embed(title="Operation cancelled!", colour=discord.Color.green()), view=None
                )
                return

            successes, fails = await SubscriptionObject.unsub_from_all(self.bot, subbed_series)
            success_msg = f"You have successfully unsubscribed from {successes} series!"
            if bypass_prompt:
                success_msg = f"You have been removed from {successes} roles!"
            if fails:
                if successes != 0:
                    success_msg += "\n\n**Note:** "
                else:
                    success_msg = ""
                success_msg += (f"I was unable to unsubscribe you from {fails} series because I cannot "
                                f"remove the role(s) from you!\n"
                                f"Double check my permissions and role hierarchy and try again!")
            em = discord.Embed(title="Unsubscribed", color=discord.Color.green(), description=success_msg)
            em.colour = discord.Colour.green() if not fails else discord.Colour.orange()
            await interaction.edit_original_response(embed=em, view=None)
            return

        else:
            try:
                manga_id, scanlator_name = manga_id.split("|")
            except ValueError:
                raise errors.MangaNotSubscribedError(manga_id)
            manga: Manga = await self.bot.db.get_series(manga_id, scanlator_name)
            if not manga:
                raise errors.MangaNotFoundError(manga_id)

            ping_role_id = await self.bot.db.get_guild_manga_role_id(interaction.guild_id, manga.id, manga.scanlator)
            role = interaction.guild.get_role(ping_role_id)
            if role and (role in interaction.user.roles and
                         guild_config.default_ping_role and role != guild_config.default_ping_role):
                if role >= interaction.guild.me.top_role:
                    raise errors.CustomError(f"{role.mention} is higher than my top role.\n"
                                             f"Please move the role below my top role and try again.")
                await interaction.user.remove_roles(role, reason="Unsubscribed from a manga.")
            await self.bot.db.unsub_user(interaction.user.id, manga.id, manga.scanlator)

            em = discord.Embed(title="Unsubscribed", color=discord.Color.green())
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
        subs = sorted(subs, key=lambda x: x.title)

        if not subs:
            em = discord.Embed(title="No Subscriptions", color=discord.Color.red())
            em.description = "You have no subscriptions."
            em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        grouped = group_items_by(subs, ["scanlator"])
        embeds: list[discord.Embed] = []

        def _make_embed(subs_count: int) -> discord.Embed:
            return discord.Embed(
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
                to_add = f"**{line_index}.** [{manga.title}]({manga.url}) - {manga.last_chapter}\n"

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
            view = SubscribeListPaginatorView(embeds, interaction)
        view.message = await interaction.followup.send(embed=embeds[0], view=view)

    @app_commands.command(
        name="chapters", description="Get a list of chapters for a manga."
    )
    @app_commands.describe(manga_id="The name of the manga.")
    @app_commands.autocomplete(manga_id=autocompletes.chapters_cmd)
    @app_commands.rename(manga_id="manga")
    @checks.has_premium(dm_only=True)
    async def chapters(self, interaction: discord.Interaction, manga_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        try:
            manga_id, scanlator_name = manga_id.split("|")
        except ValueError:
            raise errors.MangaNotFoundError(manga_id)
        manga: Manga = await self.bot.db.get_series(manga_id, scanlator_name)

        embeds = create_embeds(
            "{chapter}",
            [{"chapter": chapter} for chapter in manga.available_chapters],
            per_page=20,
        )
        modify_embeds(
            embeds,
            title_kwargs={
                "title": f"Chapters for {manga.title}",
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
    @checks.has_premium(dm_only=True)
    async def supported_websites(self, interaction: discord.Interaction) -> None:
        em = discord.Embed(title="Supported Websites", color=discord.Color.green())
        supp_webs = [
            (
                x,
                y.title(),
                x.json_tree.properties.base_url,
                x.json_tree.properties.format_urls.manga
            ) for y, x, in scanlators.items()
        ]
        supp_webs = sorted(supp_webs, key=lambda x: x[1])
        user_agents = self.bot.config.get("user-agents", {})
        em.description = (
            "Manhwa Updates Bot currently supports the following websites:\n"
        )

        removed = 0
        for i, (scanlator, name, url, _format) in enumerate(supp_webs.copy()):
            # Only remove those that are SET to None in user-agents in config or not in scanlators
            if (
                    scanlator.name not in scanlators
                    or user_agents.get(scanlator.name, True) is None
            ):
                supp_webs.pop(i - removed)
                removed += 1

        embeds = create_embeds(
            "• [{name}]({url})\n\u200b \u200b \u200b \↪ Format -> `{_format}`\n",
            [{"name": x[1], "url": x[2], "_format": x[3]} for x in supp_webs],
            per_page=10
        )
        for embed in embeds:
            embed.add_field(
                name="__Note__",
                value="More websites will be added in the future. "
                      "Don't forget to leave suggestions on websites I should add."
            )
        embeds = modify_embeds(
            embeds,
            footer_kwargs={"text": "Manhwa Updates", "icon_url": self.bot.user.display_avatar.url},
            title_kwargs={"title": f"Supported Websites ({len(supp_webs)})", "color": discord.Color.green()},
            show_page_number=True
        )
        if len(embeds) == 1:
            await interaction.response.send_message(embed=embeds[0], ephemeral=True)  # noqa
            return
        else:
            view = PaginatorView(embeds, interaction, timeout=3 * 24 * 60 * 60)
            await interaction.response.send_message(embed=embeds[0], view=view, ephemeral=True)  # noqa

    @app_commands.command(
        name="help", description="Get started with Manhwa Updates Bot."
    )
    async def help(self, interaction: discord.Interaction) -> None:
        em = discord.Embed(title="Manhwa Updates Bot Help", color=discord.Color.green())
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
- `/chapters` - Get a list of chapters of a manga.
- `/next_update_check` - Get the time until the next update check.
- `/supported_websites` - Get a list of websites supported by the bot and the bot status on them.
- `/translate` - Translate any text from one language to another.
- `/stats` - View general bot statistics.
- `/patreon` - View info about the benefits you get as a Patreon.

**Permissions:**
- The bot requires the following permissions for optimal functionality:
  - Send Messages
  - Embed Links
  - Attach Files
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
        name="info",
        description="Display info about a manhwa."
    )
    @app_commands.rename(series_id="manhwa")
    @app_commands.describe(series_id="The name of the manhwa you want to get info for.")
    @app_commands.autocomplete(series_id=autocompletes.info_cmd)
    @checks.has_premium(dm_only=True)
    async def series_info(
            self,
            interaction: discord.Interaction,
            series_id: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)  # noqa
        try:
            series_id, scanlator_name = series_id.split("|")
        except ValueError:
            raise errors.MangaNotFoundError(series_id)
        manga = await self.bot.db.get_series(series_id, scanlator_name)
        if not manga:
            raise errors.MangaNotFoundError(series_id)
        em = manga.get_display_embed(scanlators)
        view = SubscribeView(self.bot, [em], more_info_btn=False)
        await interaction.followup.send(embed=em, view=view)

    @app_commands.command(
        name="search",
        description="Search for a manga on on all/one scanlator of choice.",
    )
    @app_commands.describe(query="The name of the manga.")
    @app_commands.describe(scanlator_website="The website to search on.")
    @app_commands.rename(scanlator_website="scanlator")
    @app_commands.autocomplete(scanlator_website=autocompletes.scanlator)
    @checks.has_premium(dm_only=True)
    async def search(
            self,
            interaction: discord.Interaction,
            query: str,
            scanlator_website: Optional[str] = None,
    ) -> None:
        await interaction.response.send_message(  # noqa
            embed=(
                discord.Embed(
                    title="Processing your request, please wait!",
                    description=f"{Emotes.loading} Searching for **{query}** on {scanlator_website or 'all known websites'}...",
                    color=discord.Color.green(),
                )
                .set_footer(text=self.bot.user.display_name, icon_url=self.bot.user.display_avatar.url)
            ),
            ephemeral=True,
        )
        cannot_search_em = discord.Embed(
            title="Error",
            description=(
                f"The bot cannot search on that website yet.\n"
                "Try searching with the manga name instead."
            ),
            color=discord.Color.red(),
        )
        no_results_em = discord.Embed(
            title="Error",
            description=(
                f"No results were found for `{query}`.\n"
            ),
            color=discord.Color.red(),
        )

        async def _try_request(
                coro: Coroutine, _scanlator: Optional[AbstractScanlator] = None, raise_error: bool = False
        ) -> Any:
            try:
                return await coro
            except Exception as _err:
                if _scanlator:
                    self.bot.logger.error(f"[{_scanlator.name.title()}] Error when searching: {query}!")
                else:
                    self.bot.logger.error(f"Error when searching: {query}!")
                await self.bot.log_to_discord(f"<@!{self.bot.owner_id}> Error when searching", error=_err)
                if raise_error:
                    raise errors.CustomError(
                        "An unknown error has occured.\n"
                        "The developer has been notified and will fix as soon as he can!")

        if RegExpressions.url.search(
                query
        ):  # if the query is a URL, try to get the manga from the URL
            scanlator = get_manga_scanlator_class(scanlators, url=query)
            if scanlator is None:
                await interaction.edit_original_response(embed=no_results_em)
                return
            if hasattr(scanlator, "search"):
                embeds: list[discord.Embed] = await _try_request(
                    scanlator.search(query=query, as_em=True), scanlator, True
                )
                em = (embeds or [None])[0]
                if em is None:
                    await interaction.edit_original_response(embed=no_results_em)
                    return
                view = SubscribeView(self.bot, items=[em])
                await interaction.edit_original_response(embed=em, view=view)
                return
            else:
                await interaction.edit_original_response(embed=cannot_search_em)
                return
        elif scanlator_website:
            scanlator = scanlators.get(scanlator_website.lower())
            if not scanlator:
                await interaction.edit_original_response(
                    embed=discord.Embed(
                        title="Error",
                        description=f"Could not find a scanlator with the name `{scanlator_website}`.",
                    )
                    .set_footer(
                        text=self.bot.user.display_name, icon_url=self.bot.user.display_avatar.url
                    )
                )
                return
            if hasattr(scanlator, "search"):
                embeds = await _try_request(scanlator.search(query=query, as_em=True), scanlator, True)
                if not embeds:
                    await interaction.edit_original_response(embed=no_results_em)
                    return
                view = SubscribeView(self.bot, items=embeds, author_id=interaction.user.id)  # noqa
                await interaction.edit_original_response(embed=embeds[0], view=view)
            else:
                await interaction.edit_original_response(embed=cannot_search_em)
                return
        else:
            results = await asyncio.gather(*[
                _try_request(scanlator.search(query=query, as_em=True), scanlator, False)
                for scanlator in scanlators.values()
                if hasattr(scanlator, "search")
            ])
            results = [x for x in results if x is not None]
            if not results:
                await interaction.edit_original_response(embed=no_results_em)
                return
            else:
                results = [x[0] for x in results if x]  # grab the first result of each
                view = SubscribeView(self.bot, items=results, author_id=interaction.user.id)  # noqa
                await interaction.edit_original_response(embed=results[0], view=view)
                return

    @app_commands.command(name="translate", description="Translate any text from one language to another")
    @app_commands.describe(text="The text to translate", to="The language to translate to",
                           from_="The language to translate from")
    @app_commands.rename(from_="from")
    @app_commands.autocomplete(to=autocompletes.google_language, from_=autocompletes.google_language)
    @checks.has_premium(dm_only=True)
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

        em = discord.Embed(
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
        em = discord.Embed(
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
        em = discord.Embed(
            title="Translation Complete 🈳",
            description=f"Language: `{lang_from}` \⟶ `{lang_to}`"
        )
        em.add_field(name="📥 Input", value=f"```{text}```", inline=False)
        em.add_field(name="📤 Result",
                     value=f"```{translated}```", inline=False)
        await interaction.followup.send(embed=em, ephemeral=True)  # noqa

    # @app_commands.command(name="report_incorrect_chapters")
    # async def report_incorrect_chapters(self, interaction: discord.Interaction):
    #     await interaction.response.defer(ephemeral=True, thinking=True)

    @app_commands.command(name="stats", description="Get some basic info and stats about the bot.")
    @checks.has_premium(dm_only=True)
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)  # noqa

        (bookmarks_count,), = await self.bot.db.execute(
            "SELECT COUNT(user_id || '-' || series_id || '-' || scanlator) FROM bookmarks;"
        )
        (tracks_count,), = await self.bot.db.execute(
            "SELECT COUNT(DISTINCT series_id || '-' || scanlator) FROM tracked_guild_series;"
        )
        (subs_count,), = await self.bot.db.execute(
            "SELECT COUNT(DISTINCT id) FROM user_subs;"
        )
        (manhwa_count,), = await self.bot.db.execute(
            "SELECT COUNT(DISTINCT id || '-' || scanlator) FROM series;"
        )
        scanlators_count = len(self.bot._all_scanners)  # noqa
        guilds_count = len(self.bot.guilds)
        (users_count,), = await self.bot.db.execute(
            """
            SELECT COUNT(user_identifier) AS unique_users FROM (
                SELECT user_id AS user_identifier FROM bookmarks
                UNION
                SELECT id AS user_identifier FROM user_subs
            );
            """
        )

        uptime_str = f"Since <t:{int(self.bot.start_time.timestamp())}:R>\n"
        embed = discord.Embed(
            title="Manhwa Updates Bot Statistics",
            description="Here are the current statistics of the bot:",
            color=0x1abc9c  # Teal color
        )

        embed.add_field(name="🔖 Bookmarks", value=str(bookmarks_count), inline=True)
        embed.add_field(name="📚 Tracked Manhwas", value=str(tracks_count), inline=True)
        embed.add_field(name="👥 Users subbed to Manhwa", value=str(subs_count), inline=True)
        # embed.add_field(name="\u200b", value="\u200b", inline=False)
        embed.add_field(name="📘 Total Manhwas", value=str(manhwa_count), inline=True)
        embed.add_field(name="🔍 Supported Websites", value=str(scanlators_count), inline=True)
        embed.add_field(name="🌐 Total Servers", value=str(guilds_count), inline=True)
        # embed.add_field(name="\u200b", value="\u200b", inline=False)
        embed.add_field(name="👤 Total Users", value=str(users_count), inline=True)
        embed.add_field(name="⌛ Total Uptime", value=str(uptime_str), inline=True)
        embed.add_field(name="🐣 Born", value=f"<t:{int(self.bot.user.created_at.timestamp())}:R>", inline=True)

        embed.set_footer(text="Manhwa Updates Bot | Stats")
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)  # noqa

    @app_commands.command(name="patreon",
                          description="Help fund the server and manage your current patreon subscription")
    async def patreon(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(  # noqa
            embed=discord.Embed(
                title="Patreon", url="https://www.patreon.com/mooshi69",
                color=discord.Color.gold(),
                description=(
                    "You can donate to our [Patreon](https://www.patreon.com/mooshi69) or "
                    "[Ko-fi](https://ko-fi.com/mooshi69) to support the server and the development. "
                    "I have been working on the Manhwa Updates bot for just over 1 year now and have "
                    "tried my best to make your manhwa reading experience the best that it can be. "
                    "By becoming a Patreon you can support my work and pay for the server cost.\n\n"
                    "Manage your Patreon subscription using this command to view your patreon status and change your "
                    "custom embed color. Subscriptions may take up to `10 minutes` to refresh. "
                    "Also make sure your Discord account is linked with Patreon."
                )
            ).add_field(
                name='"Hello World" Supporter (£3/month)',
                value=(
                    "• Get the `\"Hello World\" Supporter` role in the support server.\n"
                    "• Get access to bot commands in DMs.\n"
                    "• Help fund the server and the development."
                ),
                inline=False
            ).add_field(
                name='Bot Whisperer (£5/month)',
                value=(
                    "• Get the `Bot Whisperer` role in the support server.\n"
                    "• Get access to bot commands in DMs.\n"
                    "• Help fund the server and the development."
                ),
                inline=False
            ).add_field(
                name='The Full Stack (£10/month)',
                value=(
                    "• Get `The Full Stack` role in the support server.\n"
                    "• Get access to bot commands in DMs.\n"
                    "• Help fund the server and the development."
                ),
                inline=False
            ).set_footer(
                text="Manhwa Updates Bot",
                icon_url=self.bot.user.display_avatar.url
            ),
            view=discord.ui.View().add_item(
                discord.ui.Button(
                    label="Patreon",
                    style=discord.ButtonStyle.link,
                    url="https://www.patreon.com/mooshi69"
                )
            ).add_item(
                discord.ui.Button(
                    label="Ko-fi",
                    style=discord.ButtonStyle.link,
                    url="https://ko-fi.com/mooshi69"
                )
            )
        )


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_ids:
        await bot.add_cog(CommandsCog(bot), guilds=[discord.Object(id=x) for x in bot.test_guild_ids])
    else:
        await bot.add_cog(CommandsCog(bot))
