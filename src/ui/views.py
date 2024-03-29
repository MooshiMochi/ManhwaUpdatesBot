from __future__ import annotations

from typing import Iterable, Optional, TYPE_CHECKING, Union

from discord.app_commands import AppCommandError

from .modals import ScanlatorModal
from ..core.scanlators import scanlators
from ..core.scanlators.classes import AbstractScanlator
from ..static import Emotes

if TYPE_CHECKING:
    from src.core import MangaClient

import discord
import traceback as tb

from functools import partial

from discord import ButtonStyle
from discord.ext import commands
from discord.ui import View, Button
from discord.ext.commands import Context

from src.core.objects import Bookmark, GuildSettings, Manga, ScanlatorChannelAssociation
from src.core.errors import GuildNotConfiguredError, MangaCompletedOrDropped, MangaNotFoundError

from src.utils import (
    check_missing_perms, create_bookmark_embed,
    create_dynamic_grouped_embeds, modify_embeds, respond_if_limit_reached, sort_bookmarks,
    group_items_by,
    get_manga_scanlator_class
)
from src.enums import BookmarkFolderType, BookmarkSortType, BookmarkViewType

from .buttons import CustomButtonCallbacks
from .selects import BookmarkFolderSelect, SortTypeSelect, ViewTypeSelect

from datetime import datetime


class BaseView(View):
    def __init__(
            self,
            bot: MangaClient,
            interaction: discord.Interaction | Context = None,
            timeout: float | None = 60.0,
    ):
        super().__init__(timeout=timeout)
        self.bot: MangaClient = bot
        self.interaction_or_ctx: discord.Interaction | Context = interaction
        self.message: discord.Message | None = None

    async def on_timeout(self) -> None:
        if self.message is not None:
            await self.message.edit(
                view=None,
                embed=discord.Embed(
                    color=discord.Color.red(),
                    title="Timed out",
                    description="No changes were made.",
                ),
            )

    async def on_error(
            self,
            interaction: discord.Interaction,
            error: discord.app_commands.AppCommandError,
            item: discord.ui.Button,
            /,
    ) -> None:
        await self.bot.tree.on_error(interaction, error)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if isinstance(self.interaction_or_ctx, discord.Interaction):
            author = self.interaction_or_ctx.user
        else:
            author = self.interaction_or_ctx.author

        if author.id == interaction.user.id:
            return True
        else:
            embed = discord.Embed(title=f"🚫 You cannot use this menu!", color=0xFF0000)
            await interaction.response.send_message(embed=embed, ephemeral=True)  # noqa
            return False


class BookmarkView(BaseView):
    def __init__(
            self,
            bot: MangaClient,
            interaction: discord.Interaction,
            bookmarks: list[Bookmark],
            view_type: BookmarkViewType = BookmarkViewType.VISUAL,
            folder: BookmarkFolderType = BookmarkFolderType.Reading
    ):
        super().__init__(bot, interaction, timeout=60 * 60 * 24 * 3)  # 3 days timeout
        self.bot: MangaClient = bot
        self.message: discord.Message | None = None

        self.view_type: BookmarkViewType = view_type
        self.sort_type: BookmarkSortType = BookmarkSortType.LAST_UPDATED_TIMESTAMP
        self.folder: BookmarkFolderType = folder

        self.bookmarks: list[Bookmark] = bookmarks
        self.viewable_bookmarks = self.get_bookmarks_from_folder()
        # the method below will sort the bookmarks by the sort_type
        self.text_view_embeds: list[discord.Embed] = self._bookmarks_to_text_embeds()

        self.text_page_index = 0
        self.visual_item_index = 0

        self._btn_callbacks = CustomButtonCallbacks(self.bot, self)
        self.load_components()

    def get_bookmarks_from_folder(self) -> list[Bookmark]:
        return [x for x in self.bookmarks if x.folder == self.folder or self.folder == BookmarkFolderType.All]

    def _load_visual_components_preset(self) -> BookmarkView:
        self.clear_components()
        self.add_item(ViewTypeSelect(self.view_type, row=2))

        self.add_item(
            Button(style=ButtonStyle.grey, label="\u200b", disabled=True, row=3)
        )
        update_btn = Button(
            style=ButtonStyle.blurple, label="Update", custom_id="update_btn", row=3
        )
        update_btn.callback = partial(self._btn_callbacks.update_button_callback)

        search_btn = Button(
            style=ButtonStyle.blurple, label="Search", custom_id="search_btn", row=3
        )
        search_btn.callback = partial(self._btn_callbacks.search_button_callback)

        delete_btn = Button(
            style=ButtonStyle.red, label="Delete", custom_id="delete_btn", row=3
        )
        delete_btn.callback = partial(self._btn_callbacks.delete_button_callback, confirm_view_cls=ConfirmView)

        self.add_item(update_btn)
        self.add_item(search_btn)
        self.add_item(delete_btn)

        self.add_item(
            Button(style=ButtonStyle.grey, label="\u200b", disabled=True, row=3)
        )
        self.add_item(
            BookmarkFolderSelect(row=4, folders=set(x.folder for x in self.bookmarks), current_folder=self.folder)
        )
        return self

    def _load_text_components_preset(self) -> BookmarkView:
        self.clear_components()
        self.add_item(SortTypeSelect(self.sort_type, row=1))
        self.add_item(ViewTypeSelect(self.view_type, row=2))

        def _add_blank_buttons():
            for _ in range(2):
                self.add_item(
                    Button(style=ButtonStyle.grey, label="\u200b", disabled=True, row=3)
                )

        _add_blank_buttons()
        search_btn = Button(
            style=ButtonStyle.blurple, label="Search", custom_id="search_btn", row=3
        )
        search_btn.callback = partial(self._btn_callbacks.search_button_callback)
        self.add_item(search_btn)
        _add_blank_buttons()
        self.add_item(
            BookmarkFolderSelect(row=4, folders=set(x.folder for x in self.bookmarks), current_folder=self.folder)
        )
        return self

    def load_components(self) -> BookmarkView:
        if self.view_type == BookmarkViewType.VISUAL:
            self._load_visual_components_preset()
        else:
            self._load_text_components_preset()
        return self

    def _bookmarks_to_text_embeds(self) -> list[discord.Embed]:
        self.viewable_bookmarks = sort_bookmarks(self.viewable_bookmarks, self.sort_type)

        embeds: list[discord.Embed] = create_dynamic_grouped_embeds(
            [
                {
                    "title": v.manga.title,
                    "url": v.manga.url,
                    "chpt": v.last_read_chapter,
                    "scanlator": v.manga.scanlator.title(),
                    "folder": v.folder.value[0].upper()
                }
                for v in self.viewable_bookmarks
            ],
            "**{index}.** `{folder}` [{title}]({url}) - {chpt}",
            group_key="scanlator",
            indexed=True
        )
        embeds = modify_embeds(
            embeds,
            title_kwargs={"title": f"Bookmarks ({len(self.viewable_bookmarks)})"},
            show_page_number=True
        )

        self.text_view_embeds = embeds
        return embeds

    def toggle_nav_buttons(self, on: bool = True):
        for item in self.children:
            if item.row is not None and item.row == 0:
                item.disabled = not on

    def clear_components(self) -> BookmarkView:
        """
        Summary:
            Clears all components from the view. (Except the navigation buttons)

        Returns:
            self (BookmarkView)
        """
        for item in self.children:
            if item.row is not None and item.row == 0:
                continue
            self.remove_item(item)
        return self

    async def update(self, interaction: discord.Interaction, view: BookmarkView | None = None):
        if view is None:
            view = self

        # update the view components to reflect any changes
        view.clear_components()
        view.load_components()

        if interaction.response.is_done():  # noqa
            response_function = interaction.edit_original_response
        else:
            response_function = interaction.response.edit_message  # noqa
        if len(self.bookmarks) == 0:
            await response_function(  # noqa
                view=None, embed=discord.Embed(title="You have no more bookmarks.")
            )
            self.stop()
            return

        await response_function(  # noqa
            view=view, embed=self._get_display_embed()
        )

    def change_view_type(self, new_view_type: BookmarkViewType) -> bool:
        """
        Summary:
            Changes the view type of the view.

        Parameters:
            new_view_type (BookmarkViewType): The new view type to change to.

        Returns:
            bool: True if the view type was changed, False if it was not.
        """
        if self.view_type == new_view_type:
            return False

        self.view_type = new_view_type
        self.clear_components()
        self.load_components()
        return True

    def change_sort_type(self, new_sort_type: BookmarkSortType) -> bool:
        """
        Summary:
            Changes the sort type of the view.

        Parameters:
            new_sort_type (BookmarkSortType): The new sort type to change to.

        Returns:
            bool: True if the sort type was changed, False if it was not.
        """
        if self.sort_type == new_sort_type:
            return False

        self.sort_type = new_sort_type

        # no need to manually sort bookmarks, the method below will do it for us...
        self.text_view_embeds = self._bookmarks_to_text_embeds()

        self.clear_components()
        self.load_components()
        return True

    def _get_display_embed(self) -> discord.Embed:
        if self.view_type == BookmarkViewType.TEXT:
            return self.text_view_embeds[self.text_page_index]
        else:
            idx = self.visual_item_index
            scanlator = get_manga_scanlator_class(
                scanlators, key=self.viewable_bookmarks[idx].manga.scanlator
            )
            return create_bookmark_embed(
                self.bot, self.viewable_bookmarks[idx], scanlator.json_tree.properties.icon_url
            )

    def _handle_index_change(self):
        if self.text_page_index > len(self.text_view_embeds) - 1:
            self.text_page_index = 0
        elif self.text_page_index < 0:
            self.text_page_index = len(self.text_view_embeds) - 1

        if self.visual_item_index > len(self.viewable_bookmarks) - 1:
            self.visual_item_index = 0
        elif self.visual_item_index < 0:
            self.visual_item_index = len(self.viewable_bookmarks) - 1

    def _increment_index(self, increment: int | float):
        if self.view_type == BookmarkViewType.TEXT:
            self.text_page_index += increment
        else:
            self.visual_item_index += increment
        self._handle_index_change()

    @discord.ui.button(label=f"⏮️", style=discord.ButtonStyle.blurple, row=0)
    async def _first_page(self, interaction: discord.Interaction, _):
        self._increment_index(float("inf"))  # this will set the index to zero internally
        await interaction.response.edit_message(embed=self._get_display_embed())  # noqa

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple, row=0)
    async def back(self, interaction: discord.Interaction, _):
        self._increment_index(-1)
        await interaction.response.edit_message(embed=self._get_display_embed())  # noqa

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red, row=0)
    async def _stop(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(view=None)  # noqa
        self.stop()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple, row=0)
    async def forward(
            self, interaction: discord.Interaction, _
    ):
        self._increment_index(1)
        await interaction.response.edit_message(embed=self._get_display_embed())  # noqa

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple, row=0)
    async def _last_page(self, interaction: discord.Interaction, _):
        self._increment_index(float("-inf"))  # this will set the index to max internally
        await interaction.response.edit_message(embed=self._get_display_embed())  # noqa


class PaginatorView(discord.ui.View):
    def __init__(
            self,
            items: list[Union[str, int, discord.Embed]] = None,
            interaction: Union[discord.Interaction, Context] = None,
            timeout: float = 3 * 3600,  # 3 hours,
            *args,
            **kwargs
    ) -> None:
        self.iter_items = items
        self.interaction: discord.Interaction = interaction
        self.page: int = 0
        self.message: Optional[discord.Message] = None

        if not self.iter_items and not self.interaction:
            raise AttributeError(
                "A list of items of type 'Union[str, int, discord.Embed]' was not provided to iterate through as well "
                "as the interaction."
            )

        elif not items:
            raise AttributeError(
                "A list of items of type 'Union[str, int, discord.Embed]' was not provided to iterate through."
            )

        elif not interaction:
            raise AttributeError("The command interaction was not provided.")

        if not isinstance(items, Iterable):
            raise AttributeError(
                "An iterable containing items of type 'Union[str, int, discord.Embed]' classes is required."
            )

        elif not all(isinstance(item, (str, int, discord.Embed)) for item in items):
            raise AttributeError(
                "All items within the iterable must be of type 'str', 'int' or 'discord.Embed'."
            )

        super().__init__(timeout=timeout)
        self.iter_items = list(self.iter_items)
        if len(self.iter_items) == 1:  # no need to paginate if there's only one item to display
            for _child in self.children:
                if _child.row == 0:
                    self.remove_item(_child)

    def __get_response_kwargs(self):
        if isinstance(self.iter_items[self.page], discord.Embed):
            return {"embed": self.iter_items[self.page]}
        else:
            return {"content": self.iter_items[self.page]}

    @discord.ui.button(label=f"⏮️", style=discord.ButtonStyle.blurple, row=0)
    async def _first_page(
            self, interaction: discord.Interaction, _
    ):
        self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple, row=0)
    async def back(self, interaction: discord.Interaction, _):
        self.page -= 1
        if self.page == -1:
            self.page = len(self.iter_items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red, row=0)
    async def _stop(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(view=None)  # noqa
        self.stop()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple, row=0)
    async def forward(self, interaction: discord.Interaction, _):
        self.page += 1
        if self.page == len(self.iter_items):
            self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple, row=0)
    async def _last_page(
            self, interaction: discord.Interaction, _
    ):
        self.page = len(self.iter_items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if isinstance(self.interaction, discord.Interaction):
            author = self.interaction.user
        else:
            author = self.interaction.author

        if author.id == interaction.user.id:
            return True
        else:
            embed = discord.Embed(title=f"🚫 You cannot use this menu!", color=0xFF0000)
            await interaction.response.send_message(embed=embed, ephemeral=True)  # noqa
            return False

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass  # irrelevant  
        self.stop()

    async def on_error(
            self, interaction: discord.Interaction, error: Exception, item
    ) -> None:
        if isinstance(error, TimeoutError):
            pass
        else:
            traceback = "".join(
                tb.format_exception(type(error), error, error.__traceback__)
            )
            em = discord.Embed(
                title=f"🚫 An unknown error occurred!",
                description=f"{traceback[-2000:]}",
                color=0xFF0000,
            )
            interaction.client.logger.error(traceback)

            if interaction.response.is_done():  # noqa
                await interaction.followup.send(embed=em, ephemeral=True)
            else:
                await interaction.response.send_message(embed=em, ephemeral=True)  # noqa


class SubscribeView(View):
    def __init__(
            self,
            bot: MangaClient,
            items: list[Union[str, int, discord.Embed]] = None,
            author_id: int = None,
            more_info_btn: bool = True
    ) -> None:
        self.bot: MangaClient = bot
        self.iter_items = [item for item in items if item is not None] if items else None
        self.page: int = 0
        self.author_id: int = author_id

        if self.iter_items:
            if not isinstance(self.iter_items, Iterable):
                raise AttributeError(
                    "An iterable containing items of type 'discord.Embed' is required."
                )

            if not all(isinstance(item, discord.Embed) for item in self.iter_items):
                raise AttributeError(
                    "All items within the iterable must be of type 'discord.Embed'."
                )

        super().__init__(timeout=None)
        if self.iter_items:
            self.iter_items = list(self.iter_items)
            if len(self.iter_items) == 1:
                self._delete_nav_buttons()
        if more_info_btn is False:
            children = [x for x in self.children if x.row != 0]
            target_btn = children[1]  # 2nd button
            target_btn.disabled = True
            target_btn.label = "\u200b"
            target_btn.style = ButtonStyle.grey

    def __get_response_kwargs(self):
        if isinstance(self.iter_items[self.page], discord.Embed):
            return {"embed": self.iter_items[self.page]}
        else:
            return {"content": self.iter_items[self.page]}

    def _delete_nav_buttons(self):
        for child in self.children:
            if child.row == 0:
                self.remove_item(child)

    @discord.ui.button(label=f"⏮️", style=discord.ButtonStyle.blurple, custom_id="nav_fast_left", row=0)
    async def _first_page(
            self, interaction: discord.Interaction, _
    ):
        self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple, custom_id="nav_left", row=0)
    async def back(self, interaction: discord.Interaction, _):
        self.page -= 1
        if self.page == -1:
            self.page = len(self.iter_items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red, custom_id="nav_stop", row=0)
    async def _stop(self, interaction: discord.Interaction, _):
        self._delete_nav_buttons()
        await interaction.response.edit_message(view=self)  # noqa

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple, custom_id="nav_right", row=0)
    async def forward(self, interaction: discord.Interaction, _):
        self.page += 1
        if self.page == len(self.iter_items):
            self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple, custom_id="nav_fast_right", row=0)
    async def _last_page(
            self, interaction: discord.Interaction, _
    ):
        self.page = len(self.iter_items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(
        label="Track and Subscribe",
        style=ButtonStyle.blurple,
        emoji="📚",
        custom_id="search_subscribe",
    )
    async def subscribe(self, interaction: discord.Interaction, _):
        await interaction.response.defer(thinking=True, ephemeral=True)  # noqa

        message: discord.Message = interaction.message
        manga_home_url = message.embeds[0].url

        scanlator: AbstractScanlator = get_manga_scanlator_class(scanlators, manga_home_url)

        manga_url: str = manga_home_url
        manga_id = await scanlator.get_id(manga_url)
        is_tracked: bool = await self.bot.db.is_manga_tracked(manga_id, scanlator.name)

        manga: Manga | None = await respond_if_limit_reached(
            scanlator.make_manga_object(manga_url, load_from_db=is_tracked),
            interaction
        )
        if manga == "LIMIT_REACHED":
            return

        if manga.completed:
            raise MangaCompletedOrDropped(manga.url)

        # By default, searching for a manga will save it to DB, so no need to re-add it to database
        # But we will add it anyway in case of any updates to the manga.
        # Even though if it's saved in DB, it will get fetched from DB so that doesn't really make sense,
        # but it is what it is.
        await self.bot.db.add_series(manga)
        started_tracking = False

        if not await self.bot.db.is_manga_tracked(manga.id, manga.scanlator, interaction.guild_id):
            if not interaction.user.guild_permissions.manage_roles:
                return await interaction.followup.send(
                    embed=discord.Embed(
                        title="🚫 Missing Permissions",
                        description="You are missing the `Manage Roles` to track this manhwa.\n"
                                    "Inform a staff memebr to track this manhwa before you can subscribe!",
                    ).set_author(name=self.bot.user.global_name,
                                 icon_url=self.bot.user.display_avatar.url),
                )
            else:
                # check if the manga ID already has a ping role in DB
                guild_config = await self.bot.db.get_guild_config(interaction.guild_id)
                if not guild_config:
                    error = GuildNotConfiguredError(interaction.guild_id)
                    em = discord.Embed(
                        title="Error",
                        description=error.error_msg,
                        color=0xFF0000,
                    )
                    em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
                    await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
                    return

                ping_role: discord.Role | None = None
                ping_role_id = await self.bot.db.get_guild_manga_role_id(
                    interaction.guild_id, manga.id, manga.scanlator
                )
                if ping_role_id is None:
                    if guild_config.auto_create_role:  # should create and not specified
                        role_name = manga.title[:97] + "..." if len(manga.title) > 100 else manga.title
                        # try to find a role with that name already
                        existing_role = discord.utils.get(interaction.guild.roles, name=role_name)
                        if existing_role is not None:
                            ping_role = existing_role
                        else:
                            ping_role = await interaction.guild.create_role(name=role_name, mentionable=True)
                            await self.bot.db.add_bot_created_role(interaction.guild_id, ping_role.id)
                # the command below tracks the manhwa
                await self.bot.db.upsert_guild_sub_role(interaction.guild_id, manga.id, manga.scanlator, ping_role)
                started_tracking = True

        current_user_subs: list[Manga] = await self.bot.db.get_user_guild_subs(
            interaction.guild_id, interaction.user.id
        )
        if current_user_subs:
            for loop_manga in current_user_subs:
                if loop_manga.id == manga.id and loop_manga.scanlator == manga.scanlator:
                    em = discord.Embed(
                        title="Already Subscribed", color=discord.Color.red()
                    )
                    em.description = "You are already subscribed to this series."
                    em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
                    return await interaction.followup.send(embed=em, ephemeral=True)

        await self.bot.db.subscribe_user(
            interaction.user.id, interaction.guild_id, manga.id, manga.scanlator
        )

        embed = discord.Embed(
            title="Subscribed to Series",
            color=discord.Color.green(),
            description=f"Successfully{' tracked and' if started_tracking else ''} "
                        f"subscribed to **[{manga.title}]({manga.url})!**",
        )
        embed.set_image(url=manga.cover_url)
        embed.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="More Info", style=discord.ButtonStyle.blurple,
                       custom_id="search_more_info")
    async def _none_one(self, interaction: discord.Interaction, _):
        await interaction.response.defer()  # noqa: PyCharm doesn't support Dynamic Typing :(
        em = (interaction.message.embeds or [None])[0]
        if em.description and em.description.strip() != "":
            return  # already fetched more info before

        item_index = None
        if self.iter_items:
            for i, embed in enumerate(self.iter_items):
                if embed.url == em.url:
                    item_index = i
                    break

        if em.author.name not in scanlators:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="Website is disabled",
                    description=(
                        "This website is currently disabled"
                        "*If you have any questions head to the support server in `/help`.*"
                    )
                ),
                ephemeral=True
            )
        manga = await scanlators[em.author.name].make_manga_object(em.url)
        new_em = manga.get_display_embed(scanlators)
        if item_index:
            self.iter_items[item_index] = new_em
        await interaction.edit_original_response(embed=new_em)

    @discord.ui.button(
        label="Bookmark",
        style=ButtonStyle.blurple,
        emoji="🔖",
        custom_id="search_bookmark"
    )
    async def bookmark(self, interaction: discord.Interaction, _):
        await interaction.response.defer(thinking=True, ephemeral=True)  # noqa

        manga_url = interaction.message.embeds[0].url
        # get the scanlator
        scanlator = get_manga_scanlator_class(scanlators, url=manga_url)

        # get the ID:
        manga_id = await scanlator.get_id(manga_url)
        user_bookmarks = await self.bot.db.get_user_bookmarks(interaction.user.id)
        if user_bookmarks:
            for bookmark in user_bookmarks:
                if bookmark.manga.id == manga_id and bookmark.manga.scanlator == scanlator.name:
                    return await interaction.followup.send(embed=discord.Embed(
                        title="Already Bookmarked",
                        description="You have already bookmarked this series.",
                        color=discord.Color.red()
                    ), ephemeral=True)
        # make bookmark obj
        bookmark_obj = await scanlator.make_bookmark_object(
            manga_url, interaction.user.id, interaction.guild_id or interaction.user.id
        )
        await self.bot.db.upsert_bookmark(bookmark_obj)

        embed = discord.Embed(
            title="Bookmarked!",
            color=discord.Color.green(),
            description=f"Successfully bookmarked **[{bookmark_obj.manga.title}]({bookmark_obj.manga.url})**",
        )
        embed.set_image(url=bookmark_obj.manga.cover_url)
        embed.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data["custom_id"]
        if custom_id.startswith("nav"):
            if self.author_id is None:
                self._delete_nav_buttons()
                await interaction.response.edit_message(view=self)  # noqa
                return False
            elif self.author_id == interaction.user.id:
                return True
            else:
                embed = discord.Embed(
                    title=f"🚫 You cannot use this menu!",
                    color=0xFF0000,
                    description="Try the buttons below. They should work 😉!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)  # noqa
                return False
        else:
            return True

    async def on_error(
            self, interaction: discord.Interaction, error: Exception, item
    ) -> None:
        if isinstance(error, TimeoutError):
            pass
        return await interaction.client.tree.on_error(interaction, error)


class ConfirmView(BaseView):
    def __init__(
            self,
            bot: MangaClient,
            interaction_or_ctx: discord.Interaction | commands.Context,
    ):
        super().__init__(bot, interaction_or_ctx)
        self.value = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
        self.value = True
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
        self.value = False
        self.stop()

    @property
    def result(self) -> bool:
        return self.value is not None and self.value is True

    async def prompt(
            self,
            interaction: discord.Interaction,
            prompt_message: str | None = None,
            prompt_title: str = "Are you sure?",
            edit_original_response: bool = False,
            ephemeral: bool = True
    ) -> bool:
        """
        Summary:
            Prompts the user to confirm or cancel an action.

        Args:
            interaction: The interaction object.
            prompt_message: The message to prompt the user with.
            prompt_title: The title of the prompt embed.
            edit_original_response: Whether to edit the original response or send a new one.
            ephemeral: Whether to send the prompt as an ephemeral message.

        Returns:
            bool: True if the user confirmed, False if the user canceled.
        """
        embed = discord.Embed(
            title=prompt_title,
            description=prompt_message,
            color=discord.Colour.orange()
        )
        if interaction.response.is_done():  # noqa
            if edit_original_response:
                await interaction.edit_original_response(embed=embed, view=self)
                self.message = await interaction.original_response()  # noqas
            else:
                self.message = await interaction.followup.send(embed=embed, ephemeral=ephemeral, view=self, wait=True)
        else:
            self.message = await interaction.response.send_message(embed=embed, ephemeral=ephemeral, view=self)  # noqa
        await self.wait()
        return self.result


class BookmarkChapterView(View):
    def __init__(self, bot: MangaClient, chapter_link: Optional[str] = None):
        self.bot: MangaClient = bot
        super().__init__(timeout=None)  # View is persistent ∴ no timeout
        if chapter_link:
            _children_copy = self.children.copy()
            self.clear_items()
            self.add_item(discord.ui.Button(
                label="Read Chapter",
                url=chapter_link,
            ))
            for child in _children_copy:
                self.add_item(child)

    @discord.ui.button(
        label="Mark Read", style=discord.ButtonStyle.blurple, custom_id="btn_mark_read", emoji=Emotes.success
    )
    async def mark_read(self, interaction: discord.Interaction, btn: Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
        manga_id, scanlator_name, chapter_index = self._extract_keys(interaction, btn)

        bookmark: Bookmark = await self.bot.db.get_user_bookmark(
            interaction.user.id, manga_id, scanlator_name
        )
        if bookmark is None:
            manga: Manga = await self.bot.db.get_series(manga_id, scanlator_name)
            bookmark = Bookmark(
                interaction.user.id,
                manga,
                None,  # temp value, will be updated below # noqa
                interaction.guild_id or interaction.user.id,
            )
            if not manga:
                raise MangaNotFoundError(manga_id)

        if bookmark.last_read_chapter == bookmark.manga.available_chapters[chapter_index]:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="Already Read",
                    description="This chapter is already marked as read.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

        bookmark.last_read_chapter = bookmark.manga.available_chapters[chapter_index]
        bookmark.last_updated_ts = datetime.now().timestamp()
        await self.bot.db.upsert_bookmark(bookmark)

        await interaction.followup.send(
            embed=discord.Embed(
                title="Marked Read",
                description=f"Successfully marked chapter **{bookmark.last_read_chapter}** as read.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="📖 Mark Unread",
        style=discord.ButtonStyle.red,
        custom_id="btn_mark_unread",
    )
    async def mark_unread(self, interaction: discord.Interaction, btn: Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
        # await self.bot.db.mark_chapter_unread(self.chapter)
        manga_id, scanlator_name, chapter_index = self._extract_keys(interaction, btn)

        bookmark: Bookmark = await self.bot.db.get_user_bookmark(
            interaction.user.id, manga_id, scanlator_name
        )
        if bookmark is None:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="Not Read",
                    description="This chapter is not marked as read.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

        if bookmark.last_read_chapter == bookmark.manga.available_chapters[chapter_index]:
            if chapter_index - 1 >= 0:  # if there is a previous chapter
                bookmark.last_read_chapter = bookmark.manga.available_chapters[chapter_index - 1]
                bookmark.last_updated_ts = datetime.now().timestamp()
                await self.bot.db.upsert_bookmark(bookmark)
            else:
                await self.bot.db.delete_bookmark(
                    interaction.user.id, bookmark.manga.id, bookmark.manga.scanlator
                )
            del_bookmark_view = DeleteBookmarkView(self.bot, interaction, manga_id, scanlator_name)
            del_bookmark_view.message = await interaction.followup.send(
                embed=discord.Embed(
                    title="Marked Unread",
                    description=f"Successfully marked chapter "
                                f"{bookmark.manga.available_chapters[chapter_index]} as unread.",
                    color=discord.Color.green(),
                ),
                ephemeral=True,
                view=del_bookmark_view
            )
            return
        else:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="Not Read",
                    description="This chapter is not marked as read.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

    @discord.ui.button(
        label="My last read chapter 🔖",
        style=discord.ButtonStyle.blurple,
        custom_id="btn_last_read",
    )
    async def last_read(self, interaction: discord.Interaction, btn: Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
        manga_id, scanlator_name, _ = self._extract_keys(interaction, btn)

        bookmark: Bookmark = await self.bot.db.get_user_bookmark(
            interaction.user.id, manga_id, scanlator_name
        )
        if bookmark is None:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="Not Read",
                    description="You haven't read any chapters of this manga yet.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

        last_read_index = bookmark.last_read_chapter.index
        next_chapter = next((x for x in bookmark.manga.available_chapters if x.index > last_read_index), None)
        next_not_available = "`Wait for updates!`" if not bookmark.manga.completed else "`None, manga is finished!`"

        await interaction.followup.send(
            embed=discord.Embed(
                title="Last Chapter Read",
                description=(
                    f"The last chapter you read **{bookmark.last_read_chapter}**.\n"
                    f"Next chapter: {next_chapter if next_chapter else next_not_available}\n"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @staticmethod
    def _extract_keys(
            interaction: discord.Interaction, _: Button, /,
    ) -> tuple[str, str, int]:
        key_message: str = interaction.message.content.split("||")[1]
        # f"||<ID:SCANLATOR:CH_IDX>-{update.manga_id}|{update.scanlator}|{chapter.index}>||\n"
        manga_id, scanlator, chapter_index = key_message.split("|")
        return manga_id.strip(), scanlator.strip(), int(chapter_index.strip())

    async def on_error(
            self,
            interaction: discord.Interaction,
            error: AppCommandError,
            item: discord.ui.Button,
            /,
    ) -> None:
        await self.bot.tree.on_error(interaction, error)


class DeleteBookmarkView(BaseView):
    def __init__(self, bot: MangaClient, interaction: discord.Interaction, manga_id: str, scanlator: str):
        super().__init__(bot, interaction=interaction)
        self.manga_id: str = manga_id
        self.scanlator_name: str = scanlator

    @discord.ui.button(label="Delete 'hidden bookmark'", style=discord.ButtonStyle.red)
    async def delete_last_read(self, interaction: discord.Interaction, btn: Button):
        btn.disabled = True
        await interaction.response.edit_message(view=self)  # noqa

        confirm_view: ConfirmView = ConfirmView(self.bot, interaction)
        confirm_view.message = await interaction.followup.send(
            embed=discord.Embed(
                title="Are you sure?",
                description=f"Are you sure you want to delete the 'hidden bookmark' for this manga?",
                color=discord.Color.red()
            ),
            ephemeral=True,
            view=confirm_view
        )
        await confirm_view.wait()
        if confirm_view.value is None:  # timed out
            btn.disabled = False
            await self.message.edit(view=self)
            self.stop()
            return
        elif confirm_view.value is False:  # cancelled = False
            btn.disabled = False
            await self.message.edit(view=self)
            await confirm_view.message.delete()
            self.stop()
            return

        await self.message.edit(view=None)
        await self.bot.db.delete_bookmark(interaction.user.id, self.manga_id, self.scanlator_name)
        await confirm_view.message.edit(
            embed=discord.Embed(
                title="Deleted",
                description=f"Successfully deleted the 'hidden bookmark' for this manga.",
                color=discord.Color.green(),
            ),
            view=None
        )
        self.stop()


class SupportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Support Server",
                url="https://discord.gg/TYkw8VBZkr",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Invite",
                url="https://discord.com/api/oauth2/authorize?client_id=1031998059447590955&permissions=412854111296"
                    "&scope=bot%20applications.commands",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="GitHub",
                url="https://github.com/MooshiMochi/ManhwaUpdatesBot",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="TOS",
                url="https://github.com/MooshiMochi/ManhwaUpdatesBot/blob/master/.discord/terms.md"
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Privacy",
                url="https://github.com/MooshiMochi/ManhwaUpdatesBot/blob/master/.discord/privacy.md"
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Patreon",
                url="https://www.patreon.com/mooshi69",
                row=1
            ),
        )
        self.add_item(
            discord.ui.Button(
                label="Ko-fi",
                url="https://ko-fi.com/mooshi69",
                row=1
            )
        )


class SubscribeListPaginatorView(PaginatorView):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if kwargs.get("unsub_button_only", None) is True:
            for child in self.children:
                if child.row == 1:
                    self.remove_item(child)
        else:
            for child in self.children:
                if child.row == 2:
                    self.remove_item(child)

        self.is_global_view: bool = kwargs.get("_global", False)

    @discord.ui.button(label="\u200b", style=discord.ButtonStyle.grey, disabled=True, row=1)
    async def _none_one(self, interaction: discord.Interaction, _):
        pass

    @discord.ui.button(label="Show Untracked Manhwa", style=discord.ButtonStyle.blurple, row=1)
    async def show_untracked(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        bot: MangaClient = interaction.client
        mangas: list[Manga] = await bot.db.get_user_untracked_subs(
            interaction.user.id, interaction.guild_id if not self.is_global_view else None
        )
        grouped_by_scanlator: dict[str, list[Manga]] = group_items_by(mangas, ["scanlator"], as_dict=True)
        grouped_list = []
        for key, value in grouped_by_scanlator.items():
            for manga in value:
                grouped_list.extend(
                    [{"scanlator": key.title(), "manga": manga, "last_chapter": manga.last_chapter}]
                )
        embeds = create_dynamic_grouped_embeds(
            grouped_list, "**{index}.** {manga} - {last_chapter}", group_key="scanlator"
        )
        embeds = modify_embeds(
            embeds, title_kwargs={
                "title": f"Your{' Global' if self.is_global_view else ''} Untracked Manhwa",
                "color": discord.Colour.blurple()
            },
            show_page_number=True,
            footer_kwargs={
                "text": interaction.client.user.display_name,
                "icon_url": interaction.client.user.display_avatar.url
            }
        )

        if not embeds:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="No Untracked Manhwa",
                    description="You have no untracked manhwa.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

        paginator_view = SubscribeListPaginatorView(
            embeds, interaction, unsub_button_only=True, _global=self.is_global_view
        )
        paginator_view.message = await interaction.followup.send(
            embed=embeds[0],
            view=paginator_view
        )

    @discord.ui.button(label="\u200b", style=discord.ButtonStyle.grey, disabled=True, row=1)
    async def _none_two(self, interaction: discord.Interaction, _):
        pass

    @discord.ui.button(label="Unsubscribe from all untracked Manhwa", style=discord.ButtonStyle.red, row=2)
    async def unsubscribe_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        await interaction.response.edit_message(view=self)  # noqa
        bot: MangaClient = interaction.client
        mangas: list[Manga] = await bot.db.get_user_untracked_subs(
            interaction.user.id, interaction.guild_id
        )
        if not mangas:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="No Untracked Manhwa",
                    description="You are not subscribed to any untracked manhwa.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

        confirm_view: ConfirmView = ConfirmView(bot, interaction)
        confirm_view.message = await interaction.followup.send(
            embed=discord.Embed(
                title="Are you sure?",
                description=f"Are you sure you want to unsubscribe from all untracked manhwa?",
                color=discord.Color.red()
            ),
            ephemeral=True,
            view=confirm_view
        )
        await confirm_view.wait()

        if not confirm_view.result:  # cancelled = False
            button.disabled = False
            await interaction.edit_original_response(view=self)
            await confirm_view.message.delete()
            return

        if self.is_global_view:
            unsub_count = await bot.db.unsubscribe_user_from_all_untracked(interaction.user.id)
        else:
            unsub_count = await bot.db.unsubscribe_user_from_all_untracked(interaction.user.id, interaction.guild_id)

        await confirm_view.message.edit(
            embed=discord.Embed(
                title="Unsubscribed",
                description=(
                    f"Successfully unsubscribed from {unsub_count} untracked manhwa"
                    f"{' globally' if self.is_global_view else ''}."
                ),
                color=discord.Color.green(),
            ),
            view=None
        )


class SettingsView(BaseView):
    def __init__(self, bot: MangaClient, interaction: discord.Interaction, guild_config: GuildSettings):
        super().__init__(bot, interaction, timeout=2 * 24 * 60 * 60)  # 2 days timeout
        self.bot = bot
        self._init_guild_config: GuildSettings = GuildSettings.from_tuple(self.bot, guild_config.to_tuple())
        self.guild_config: GuildSettings = guild_config
        self.selected_option: str | None = None

        self.child_map: dict[
            int | str, discord.ui.Select | list[discord.ui.Button] | discord.ui.Item[SettingsView]] = {
            child.row: child for child in self.children
        }
        self.child_map.pop(4)

        self.child_map["default"] = self.child_map.pop(0)
        self.child_map["bool"] = self.child_map.pop(1)
        self.child_map["channel"] = self.child_map.pop(2)
        self.child_map["role"] = self.child_map.pop(3)
        self.child_map["buttons"]: list[discord.ui.Button] = [x for x in self.children if x.row == 4]  # noqa

        self.delete_mode: bool = False

        self.clear_items()
        self._refresh_components()

    def create_embed(self) -> discord.Embed:
        channel = self.guild_config.notifications_channel
        ping_role = self.guild_config.default_ping_role
        bot_manager_role = self.guild_config.bot_manager_role
        system_channel = self.guild_config.system_channel
        auto_create_role = self.guild_config.auto_create_role
        show_update_buttons = self.guild_config.show_update_buttons
        paid_chapter_notifs = self.guild_config.paid_chapter_notifs

        text = f"""
        **#️⃣ Updates Channel:** {channel.mention if channel else "Not set."}
        \u200b \u200b \u200b **^** `The channel the bot will send chapter updates to.`
        **🔔 Default Ping Role:** {ping_role.mention if ping_role else "Not set."}
        \u200b \u200b \u200b **^** `The role that will be pinged for all updates.`
        **🔄️ Auto Create Role:** {Emotes.success if auto_create_role else Emotes.error}
        \u200b \u200b \u200b **^** `Whether to auto create roles for new tracked manhwa.`
        **❗ System Alerts Channel:** {system_channel.mention if system_channel else "Not set."}
        \u200b \u200b \u200b **^** `The channel to send critical/dev/system alerts to.`
        **🔧 Bot Manager Role:** {bot_manager_role.mention if bot_manager_role else "Not set."}
        \u200b \u200b \u200b **^** `The role the bot will consider as a manager role.`
        **🔘Show Update Buttons:** {Emotes.success if show_update_buttons else Emotes.error}
        \u200b \u200b \u200b **^** `Whether to show buttons for chapter updates.`
        **🗨️ Custom Scanlator Channels**: Select for details.
        \u200b \u200b \u200b **^** `Set custom notification channels for specific scanlators.`
        **💰 Notify for Paid Chapter releases:** {Emotes.success if paid_chapter_notifs else Emotes.error}
        \u200b \u200b \u200b **^** `Whether to notify for paid chapter releases.`
        """
        desc = f"__Select the setting you want to edit.__"
        if self.delete_mode:
            desc = (f"{Emotes.warning} **DELETE MODE IS ENABLED** {Emotes.warning}\n"
                    f"__Select the setting you want to delete.__")

        return discord.Embed(title="Settings", description=desc + "\n" + text, color=discord.Color.blurple())

    def _refresh_components(self):
        self.clear_items()
        if self.selected_option is None or self.selected_option == "default":
            self.add_item(self.child_map["default"])
            for item in self.child_map["buttons"]:
                self.add_item(item)
        elif self.selected_option in ["channel", "system_channel"]:
            self.add_item(self.child_map["channel"])
        elif self.selected_option in ["default_ping_role", "bot_manager_role"]:
            self.add_item(self.child_map["role"])
        elif self.selected_option in ["auto_create_role", "dev_ping", "show_update_buttons", "paid_chapter_notifs"]:
            self.add_item(self.child_map["bool"])
        else:
            raise ValueError(f"Invalid value: {self.selected_option}")

    @discord.ui.select(
        options=[
            discord.SelectOption(label="Set the updates channel", value="channel", emoji="#️⃣"),
            discord.SelectOption(label="Set Default ping role", value="default_ping_role", emoji="🔔"),
            discord.SelectOption(label="Auto create role for new tracked manhwa", value="auto_create_role", emoji="🔄"),
            discord.SelectOption(label="Set the bot manager role", value="bot_manager_role", emoji="🔧"),
            discord.SelectOption(label="Set the system notifications channel", value="system_channel", emoji="❗"),
            discord.SelectOption(label="Show buttons for chapter updates", value="show_update_buttons", emoji="🔘"),
            discord.SelectOption(label="Custom Scanlator Channels", value="custom_scanlator_channels", emoji="🗨️"),
            discord.SelectOption(label="Notify for Paid Chapter releases", value="paid_chapter_notifs", emoji="💵"),
        ],
        max_values=1,
        min_values=1,
        placeholder="Select the option to edit.",
        row=0
    )
    async def _default_select_callback(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        if select.values[0] == "custom_scanlator_channels":
            scanlator_channels_view = ScanlatorChannelAssociationView(self.bot, interaction, self.guild_config)
            embed: discord.Embed = await scanlator_channels_view.get_display_embed()
            if not self.guild_config.notifications_channel:
                await interaction.response.send_message(embed=embed, ephemeral=True)  # noqa
            else:
                await interaction.response.edit_message(embed=embed, view=scanlator_channels_view)  # noqa
            return

        if self.delete_mode:
            match select.values[0]:
                case "default_ping_role":
                    self.guild_config.default_ping_role = None
                case "bot_manager_role":
                    self.guild_config.bot_manager_role = None
                case "system_channel":
                    self.guild_config.system_channel = None
                case "auto_create_role":
                    self.guild_config.auto_create_role = False
                case "show_update_buttons":
                    self.guild_config.show_update_buttons = False
                case "paid_chapter_notifs":
                    self.guild_config.paid_chapter_notifs = False
                case "channel":
                    return await interaction.response.send_message(  # noqa
                        embed=discord.Embed(
                            title="Cannot delete updates channel",
                            description="If you truly wish to remove it, use the `🗑️ Delete config` button instead.",
                            colour=discord.Colour.red()
                        ),
                        ephemeral=True
                    )
        else:
            self.selected_option = select.values[0]
        embed = self.create_embed()
        self._refresh_components()
        await interaction.response.edit_message(embed=embed, view=self)  # noqa

    @discord.ui.select(
        options=[
            discord.SelectOption(label="Enabled", value="True", emoji=Emotes.success),
            discord.SelectOption(label="Disabled", value="False", emoji=Emotes.error),
        ],
        max_values=1,
        min_values=1,
        placeholder="Set to Enabled or Disabled.",
        row=1
    )
    async def _bool_select_callback(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        if self.selected_option == "auto_create_role":
            self.guild_config.auto_create_role = select.values[0] == "True"
        elif self.selected_option == "show_update_buttons":
            self.guild_config.show_update_buttons = select.values[0] == "True"
        elif self.selected_option == "paid_chapter_notifs":
            self.guild_config.paid_chapter_notifs = select.values[0] == "True"
        else:
            raise ValueError(f"Invalid value: {self.selected_option}")
        self.selected_option = None
        self._refresh_components()
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)  # noqa

    @discord.ui.select(
        cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], row=2,
        placeholder="Select a channel to send updates to."
    )
    async def _channel_select_callback(
            self, interaction: discord.Interaction, select: discord.ui.ChannelSelect
    ) -> None:
        channel_id = select.values[0].id
        channel = interaction.guild.get_channel(channel_id)
        if not channel:
            embed = self.create_embed()
            self.selected_option = None
            self._refresh_components()
            await interaction.response.edit_message(embed=embed, view=self)  # noqa
            await interaction.followup.send(  # noqa
                embed=discord.Embed(
                    title="Channel not found",
                    description=f"Could not find the channel <#{channel_id}>!\n"
                                f"Please ensure I have all required permissions.",
                    colour=discord.Colour.red()
                ),
                ephemeral=True
            )
            return
        my_perms = channel.permissions_for(interaction.guild.me)
        required_perms: list[tuple[str, bool]] = [
            ("Send Messages", my_perms.send_messages),
            ("Attach Files", my_perms.attach_files),
            ("discord.Embed Links", my_perms.embed_links)
        ]
        if not all([x[1] for x in required_perms]):
            embed = self.create_embed()
            self.selected_option = None
            self._refresh_components()
            await interaction.response.edit_message(embed=embed, view=self)  # noqa
            perms = ", ".join(x[0] for x in required_perms)  # noqa
            await interaction.followup.send(  # noqa
                embed=discord.Embed(
                    title=f"Missing Required Permissions",
                    colour=discord.Colour.red(),
                    description=f"Sorry, I don't have the required permissions `{perms}` for "
                                + f"the {channel.mention}.\nPlease ask a server administrator to fix this issue.",
                ),
                ephemeral=True
            )
            return
        if self.selected_option == "system_channel":
            self.guild_config.system_channel = channel
        else:
            self.guild_config.notifications_channel = channel
        self.selected_option = None
        self._refresh_components()
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)  # noqa

    @discord.ui.select(cls=discord.ui.RoleSelect, row=3, placeholder="Select a default role to ping for updates.")
    async def _role_select_callback(self, interaction: discord.Interaction, select: discord.ui.RoleSelect) -> None:
        role_id = select.values[0].id
        role = interaction.guild.get_role(role_id)
        if not role:
            embed = self.create_embed()
            self.selected_option = None
            self._refresh_components()
            await interaction.response.edit_message(embed=embed, view=self)  # noqa
            await interaction.followup.send(  # noqa
                embed=discord.Embed(
                    title="Role not found",
                    description=f"Could not find the <@&{role_id}> role!\n"
                                f"Please ensure I have all required permissions.",
                    colour=discord.Colour.red()
                ),
                ephemeral=True
            )
            return

        elif role.position >= interaction.guild.me.top_role.position:
            embed = self.create_embed()
            self.selected_option = None
            self._refresh_components()
            await interaction.response.edit_message(embed=embed, view=self)  # noqa
            await interaction.followup.send(  # noqa
                embed=discord.Embed(
                    title="Role too high",
                    description=f"The <@&{role.id}> role is too high for me to ping!\n"
                                f"Please move it below my top role.",
                    colour=discord.Colour.red(),
                ),
                ephemeral=True
            )
            return
        elif not role.is_assignable() or role.is_bot_managed() or role.is_integration():
            embed = self.create_embed()
            self.selected_option = None
            self._refresh_components()
            await interaction.response.edit_message(embed=embed, view=self)  # noqa
            await interaction.followup.send(  # noqa
                embed=discord.Embed(
                    title="Role is not assignable",
                    description=f"I cannot assign the <@&{role.id}> role to users.\n"
                                f"Please use a different role.",
                ),
                ephemeral=True
            )
            return

        if self.selected_option == "default_ping_role":
            self.guild_config.default_ping_role = role

        elif self.selected_option == "bot_manager_role":
            self.guild_config.bot_manager_role = role

        self.selected_option = None
        self._refresh_components()
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)  # noqa

    @discord.ui.button(label="Done", emoji=Emotes.success, style=discord.ButtonStyle.blurple, row=4)
    async def done_btn_callback(self, interaction: discord.Interaction, _) -> None:
        if not self.guild_config.notifications_channel:
            await interaction.response.send_message(  # noqa
                embed=discord.Embed(
                    title="Cannot save changes",
                    description="You must set a channel to send updates to.\n"
                                "If you are deleting settings, please use the `🗑️ Delete Config` button instead.",
                    color=discord.Color.red(),
                ),
                ephemeral=True
            )
            return

        if (self._init_guild_config.bot_manager_role is not None and
                self._init_guild_config.bot_manager_role != self.guild_config.bot_manager_role):
            missing_perms = check_missing_perms(interaction.permissions, discord.Permissions(manage_guild=True))
            is_bot_manager = self._init_guild_config.bot_manager_role.id in [role.id for role in interaction.user.roles]
            if is_bot_manager and missing_perms:
                self.guild_config.bot_manager_role = self._init_guild_config.bot_manager_role
                self.selected_option = None
                self._refresh_components()
                embed = self.create_embed()
                await interaction.response.edit_message(embed=embed, view=self)  # noqa
                missing_perms = ", ".join([s.replace("_", " ").title() for s in missing_perms])
                return await interaction.followup.send(  # noqa
                    embed=discord.Embed(
                        title="Missing Permissions",
                        description=f"Sorry, you don't have the required permissions to edit or "
                                    f"remove the `bot manager role`.\n"
                                    f"Missing permissions: `{missing_perms}`",
                        colour=discord.Colour.red()
                    ), ephemeral=True
                )

        await self.bot.db.upsert_config(self.guild_config)
        await interaction.response.edit_message(view=None)  # noqa
        await interaction.followup.send(  # noqa
            embed=discord.Embed(
                title="Settings Updated",
                description="Successfully updated the settings.",
                color=discord.Color.green(),
            ),
            ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Cancel", emoji=Emotes.error, style=discord.ButtonStyle.blurple, row=4)
    async def cancel_btn_callback(self, interaction: discord.Interaction, _) -> None:
        await interaction.response.edit_message(  # noqas
            embed=discord.Embed(
                title="Cancelled",
                description="Setting changes have been cancelled.",
                color=discord.Color.green(),
            ),
            view=None
        )
        self.stop()

    @discord.ui.button(label="Delete Mode: Off", emoji=Emotes.warning, style=discord.ButtonStyle.green, row=4)
    async def delete_mode_btn_callback(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.delete_mode = not self.delete_mode
        if self.delete_mode:
            button.label = "Delete Mode: On"
            button.style = discord.ButtonStyle.red
        else:
            button.label = "Delete Mode: Off"
            button.style = discord.ButtonStyle.green
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)  # noqa

    @discord.ui.button(label="Delete config", emoji="🗑️", style=discord.ButtonStyle.red, row=4)
    async def delete_config_btn_callback(self, interaction: discord.Interaction, _) -> None:
        await self.bot.db.delete_config(interaction.guild_id)
        await interaction.response.edit_message(view=None)  # noqa
        bot_created_roles = await self.bot.db.get_all_guild_bot_created_roles(interaction.guild_id)
        embed = discord.Embed(
            title="Guild config deleted",
            description="Successfully deleted guild settings.",
            color=discord.Color.green(),
        )
        view: ConfirmView | None = None
        send_kwargs = {"embed": embed, "wait": True, "ephemeral": True}
        if bot_created_roles:
            extra = f"Would you like the bot to delete all {len(bot_created_roles)} roles it created?"
            embed.description += "\n" + extra
            view = ConfirmView(self.bot, interaction)
            send_kwargs["view"] = view

        msg = await interaction.followup.send(**send_kwargs)
        if view is not None:
            await view.wait()
            if not view.result:
                return await msg.edit(view=None, embed=discord.Embed(
                    title="Operation Cancelled",
                    description="The bot will not delete the roles it created.",
                    color=discord.Color.green(),
                ))
            else:  # value is True
                success_count = 0
                for role in interaction.guild.roles:
                    if role.id in bot_created_roles:
                        try:
                            await role.delete()
                            success_count += 1
                        except discord.HTTPException:
                            pass
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="Deleted Roles",
                        description=f"Successfully deleted {success_count} roles.",
                        color=discord.Color.green(),
                    ),
                    ephemeral=True
                )
                await self.bot.db.delete_all_guild_created_roles(interaction.guild_id)
        self.stop()


class ScanlatorChannelAssociationView(BaseView):
    def __init__(self, bot: MangaClient, interaction: discord.Interaction, temp_config: GuildSettings):
        super().__init__(bot, interaction)
        self.interaction: discord.Interaction = interaction
        self.temp_config: GuildSettings = temp_config

        self.selected_scanlator: str | None = None
        self.selected_channel: discord.TextChannel | None = None
        self.used_guild_scanlators: list[str] = []
        self.current_associations: list[ScanlatorChannelAssociation] = []
        self.pending_removals: list[str] = []
        # self._refresh_components()

    async def get_display_embed(self) -> discord.Embed:
        """
        Creats an embed showing the current custom scanlator-channel associations, as well as possible new associations

        Returns:
            discord.Embed: The embed to display

        """
        if not self.temp_config.notifications_channel:
            return discord.Embed(
                title="Channel not set",
                description="You must set a **Notifications Channel** first and track a manhwa to use this setting.",
                color=discord.Color.red(),
            )
        em = discord.Embed(
            title="Custom Scanlator Channels",
            description="Press `New Association` to create a new redirect for a scanlator's notifications.\n",
            color=discord.Color.blurple()
        )
        db_associations = await self.bot.db.get_scanlator_channel_associations(
            self.interaction.guild_id
        )
        db_associations = [x for x in db_associations if x.scanlator not in self.pending_removals]
        self.current_associations = db_associations + self.current_associations
        self.current_associations = list({x.scanlator: x for x in self.current_associations}.values())

        em.set_footer(text=self.bot.user.display_name, icon_url=self.bot.user.display_avatar.url)
        if not self.current_associations:
            em.description += "\n`No custom scanlator channels set.`\n"
        else:
            for association in sorted(self.current_associations, key=lambda x: x.scanlator.lower()):
                scanlator_name = association.scanlator
                channel = association.channel
                em.description += f"\n**`{scanlator_name.title()}`** - {channel.mention}"
        em.description += "\n"

        association_strings = [x.scanlator for x in self.current_associations]
        self.used_guild_scanlators = await self.bot.db.get_used_scanlator_names(self.interaction.guild_id)
        available_associations = sorted(
            [scanlator.title() for scanlator in self.used_guild_scanlators if scanlator not in association_strings]
        )

        if available_associations:
            em.description += "\n**Available Associations**\n"
            for scanlator in available_associations:
                em.description += f"**`{scanlator}`**\n"
        return em

    @discord.ui.button(label="New Association", style=discord.ButtonStyle.blurple, row=0)
    async def new_association_btn_callback(self, interaction: discord.Interaction, _) -> None:
        modal = ScanlatorModal(self, self.used_guild_scanlators)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if not modal.scanlator:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title=f"Scanlator not found",
                    description="Please copy and paste the name from the **available scanaltors** provided."
                ).set_footer(
                    text=interaction.client.user.display_name,
                    icon_url=interaction.client.user.display_avatar.url
                ),
                ephemeral=True
            )

        response_embed = discord.Embed(
            title="Select channel",
            description=f"Select the channel to redirect updates to for **`{modal.scanlator.title()}`**"
        )
        select_view = ChannelSelectorView(
            self.bot, interaction, self, [discord.ChannelType.text], modal.scanlator
        )
        select_msg = await interaction.followup.send(embed=response_embed, view=select_view, ephemeral=True, wait=True)
        await select_view.wait()

        # check that the bot has the required permissions in the selected channel
        from ..utils import check_missing_perms
        missing_perms = check_missing_perms(
            select_view.selected_channel.permissions, discord.Permissions(
                send_messages=True, embed_links=True, attach_files=True
            )
        )
        if missing_perms:
            await select_msg.edit(
                embed=discord.Embed(
                    title="Missing Permissions",
                    description=f"I am missing the following permissions in {select_view.selected_channel.mention}:\n"
                                f"{' '.join(missing_perms)}\nPlease select another channel or update my permissions "
                                f"in the selected channel and try agin.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        guild_config: GuildSettings = await interaction.client.db.get_guild_config(interaction.guild_id)
        if select_view.selected_channel.id == guild_config.notifications_channel.id:
            return await select_msg.edit(
                embed=discord.Embed(
                    title="Already Set",
                    description="This channel is already set as the updates channel.",
                    color=discord.Color.red()
                ),
                view=None
            )

        await select_msg.edit(
            embed=discord.Embed(
                title="Redirect Set",
                description=f"Notifications from **{modal.scanlator.title()}** will "
                            f"now be sent to {select_view.selected_channel.mention}.\n\n*Don't forget to save your "
                            f"changes!*",
                color=discord.Color.green()
            ),
            view=None
        )

        self.current_associations.append(
            ScanlatorChannelAssociation(
                self.bot,
                guild_id=interaction.guild_id,
                scanlator=modal.scanlator,
                channel_id=select_view.selected_channel.id
            )
        )
        if modal.scanlator in self.pending_removals:
            self.pending_removals.remove(modal.scanlator)

        await self.interaction.edit_original_response(embed=await self.get_display_embed(), view=self)

    @discord.ui.button(label="Delete Association", style=discord.ButtonStyle.red, row=0)
    async def delete_association_btn_callback(self, interaction: discord.Interaction, _) -> None:
        modal = ScanlatorModal(self, self.used_guild_scanlators)
        await interaction.response.send_modal(modal)  # noqa: Dynamic typing issue on pycharm :(
        await modal.wait()
        if not modal.scanlator:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title=f"Scanlator '{modal.input_value.value}' not found",
                    description="Please copy and paste the name from the **available scanaltors** provided."
                ).set_footer(
                    text=interaction.client.user.display_name,
                    icon_url=interaction.client.user.display_avatar.url
                ),
                ephemeral=True
            )
        target_association = [x for x in self.current_associations if x.scanlator != self.selected_scanlator]
        if not target_association:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="Association not found",
                    description=f"No association found for **`{modal.input_value.value}`**.",
                    color=discord.Color.red()
                ).set_footer(
                    text=interaction.client.user.display_name,
                    icon_url=interaction.client.user.display_avatar.url),
                ephemeral=True
            )
        await interaction.followup.send(
            embed=discord.Embed(
                title="Deleted",
                description=f"Successfully deleted the association for **`{modal.scanlator.title()}`**\n\n*Don't "
                            f"forget to save your changes!*",
                color=discord.Color.green()
            ).set_footer(
                text=interaction.client.user.display_name,
                icon_url=interaction.client.user.display_avatar.url
            ),
            ephemeral=True
        )
        self.current_associations.remove(target_association[0])  # remove the association
        self.pending_removals.append(modal.scanlator)
        embed = await self.get_display_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Save changes", emoji="💾", style=discord.ButtonStyle.green, row=1)
    async def done_btn_callback(self, interaction: discord.Interaction, _) -> None:
        # save the association changes here
        if self.current_associations:
            associations_to_delete = [x for x in self.current_associations if x.scanlator in self.pending_removals]
            self.current_associations = [
                x for x in self.current_associations if x.scanlator not in self.pending_removals
            ]

            await ScanlatorChannelAssociation.delete_many(associations_to_delete)
            await ScanlatorChannelAssociation.upsert_many(self.bot, self.current_associations)

        new_view = SettingsView(self.bot, interaction, self.temp_config)
        embed = new_view.create_embed()
        await interaction.response.edit_message(embed=embed, view=new_view)  # noqa
        await interaction.followup.send(
            embed=discord.Embed(
                title="Changes Saved",
                description=f"{Emotes.success} Successfully saved the changes.",
                colour=discord.Colour.green()
            ).set_footer(
                text=interaction.client.user.display_name,
                icon_url=interaction.client.user.display_avatar.url
            ),
            ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.red, row=1)
    async def cancel_btn_callback(self, interaction: discord.Interaction, _) -> None:
        new_view = SettingsView(self.bot, interaction, self.temp_config)
        embed = new_view.create_embed()
        await interaction.response.edit_message(embed=embed, view=new_view)
        self.stop()

    @discord.ui.button(label="Delete all", emoji="🗑️", style=discord.ButtonStyle.red, row=1)
    async def delete_all_btn_callback(self, interaction: discord.Interaction, _) -> None:
        if not self.current_associations:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="No Associations",
                    description="There are no custom scanlator-channel associations to delete.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        await interaction.response.defer(thinking=False, ephemeral=True)  # noqa

        confirm_view = ConfirmView(self.bot, interaction)
        result = await confirm_view.prompt(
            interaction,
            "Are you sure you want to delete all custom scanlator-channel associations?"
        )
        if not result:
            await confirm_view.message.edit(
                embed=discord.Embed(
                    title="Operation Cancelled",
                    description="The operation was cancelled.",
                    color=discord.Color.green()
                ),
                view=None
            )
            return
        self.pending_removals = [x.scanlator for x in self.current_associations]
        self.current_associations = []
        await confirm_view.message.edit(
            embed=discord.Embed(
                title="Deleted",
                description="Successfully deleted all custom scanlator-channel associations.\n\n*Don't forget to "
                            "save your changes!*",
                color=discord.Color.green()
            ),
            view=None
        )

        embed = await self.get_display_embed()
        await interaction.edit_original_response(embed=embed, view=self)


class ChannelSelectorView(BaseView):
    def __init__(self, bot: MangaClient, interaction: discord.Interaction, parent: ScanlatorChannelAssociationView,
                 channel_types: list[discord.ChannelType], selected_scanlator: str):
        super().__init__(bot, interaction, timeout=None)
        self._channel_types: list[discord.ChannelType] = channel_types
        self.association_view: ScanlatorChannelAssociationView = parent
        self.selected_scanlator: str = selected_scanlator

        self.selected_channel: discord.app_commands.AppCommandChannel | None = None

        select_to_add = discord.ui.ChannelSelect(
            placeholder="Select a channel...",
            channel_types=self._channel_types
        )
        select_to_add.callback = partial(self._channel_select_callback, select=select_to_add)
        self.add_item(select_to_add)

    async def _channel_select_callback(self, interaction: discord.Interaction,
                                       select: discord.ui.ChannelSelect) -> None:
        self.selected_channel: discord.app_commands.AppCommandChannel = select.values[0]
        await interaction.response.defer(ephemeral=True, thinking=False)  # acknowledge the interaction
        self.stop()
