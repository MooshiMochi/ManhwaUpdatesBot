from __future__ import annotations

from typing import Iterable, Optional, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from src.core import MangaClient

import discord
import traceback as tb

from functools import partial

from discord import ButtonStyle
from discord.ext import commands
from discord.ui import View, Button
from discord.ext.commands import Context

from src.core.objects import Bookmark, ABCScan, GuildSettings, Manga
from src.core.scanners import SCANLATORS
from src.core.errors import MangaCompletedOrDropped

from src.utils import (
    create_bookmark_embed,
    create_dynamic_grouped_embeds, modify_embeds, respond_if_limit_reached, sort_bookmarks,
    group_items_by,
    get_manga_scanlator_class
)
from src.enums import BookmarkSortType, BookmarkViewType
from src.overwrites import Embed

from .buttons import CustomButtonCallbacks
from .selects import SortTypeSelect, ViewTypeSelect

from datetime import datetime


class BaseView(View):
    def __init__(
            self,
            bot: MangaClient,
            interaction: discord.Interaction | Context = None,
            timeout: float | None = 60.0,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.interaction_or_ctx: discord.Interaction | Context = interaction
        self.message: discord.Message | None = None

    async def on_timeout(self) -> None:
        if self.message is not None:
            await self.message.edit(
                view=None,
                embed=Embed(
                    bot=self.bot,
                    color=discord.Color.red(),
                    title="Timed out",
                    description="No changes were made.",
                ),
            )

    async def on_error(
            self,
            interaction: discord.Interaction,
            error: Exception,
            item: discord.ui.Button,
            /,
    ) -> None:
        traceback = "".join(
            tb.format_exception(type(error), error, error.__traceback__)
        )
        self.bot.logger.error(traceback)
        if not interaction.response.is_done():  # noqa
            await interaction.response.send_message(  # noqa
                f"An error occurred: ```py\n{traceback[-1800:]}```", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"An error occurred: ```py\n{traceback[-1800:]}```", ephemeral=True
            )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if isinstance(self.interaction_or_ctx, discord.Interaction):
            author = self.interaction_or_ctx.user
        else:
            author = self.interaction_or_ctx.author

        if author.id == interaction.user.id:
            return True
        else:
            embed = Embed(bot=self.bot, title=f"🚫 You cannot use this menu!", color=0xFF0000)
            await interaction.response.send_message(embed=embed, ephemeral=True)  # noqa
            return False


class BookmarkView(BaseView):
    def __init__(
            self,
            bot: MangaClient,
            interaction: discord.Interaction,
            bookmarks: list[Bookmark],
            view_type: BookmarkViewType = BookmarkViewType.VISUAL,
    ):
        super().__init__(bot, interaction, timeout=60 * 60 * 1)  # 1 hour timeout
        self.bot: MangaClient = bot
        self.message: discord.Message | None = None

        self.view_type: BookmarkViewType = view_type
        self.sort_type: BookmarkSortType = BookmarkSortType.LAST_UPDATED_TIMESTAMP

        self.bookmarks: list[Bookmark] = bookmarks
        # the method below will sort the bookmarks by the sort_type
        self.text_view_embeds: list[Embed] = self._bookmarks_to_text_embeds()

        self.text_page_index = 0
        self.visual_item_index = 0

        self._btn_callbacks = CustomButtonCallbacks(self.bot, self)
        self.load_components()

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
        return self

    def load_components(self) -> BookmarkView:
        if self.view_type == BookmarkViewType.VISUAL:
            self._load_visual_components_preset()
        else:
            self._load_text_components_preset()
        return self

    def _bookmarks_to_text_embeds(self) -> list[Embed]:
        self.bookmarks = sort_bookmarks(self.bookmarks, self.sort_type)
        grouped = group_items_by(self.bookmarks, ["manga.scanlator"])
        embeds: list[Embed] = []

        def _make_embed() -> Embed:
            return Embed(
                bot=self.bot,
                title=f"Bookmarks ({len(self.bookmarks)})",
                color=discord.Color.blurple(),
                description="",
            )

        em = _make_embed()
        line_index = 0
        for bookmark_group in grouped:
            scanlator_title_added = False

            for bookmark in bookmark_group:
                line_index += 1
                to_add = (
                    f"**{line_index}.** "
                    f"[{bookmark.manga.human_name}]({bookmark.manga.url}) - {bookmark.last_read_chapter}\n"
                )
                if not scanlator_title_added:
                    if len(em.description) + len(bookmark.manga.scanlator) + 6 > 4096:
                        embeds.append(em)
                        em = _make_embed()
                        em.description += f"**\n{bookmark.manga.scanlator.title()}**\n"
                        scanlator_title_added = True
                    else:
                        em.description += f"**\n{bookmark.manga.scanlator.title()}**\n"
                        scanlator_title_added = True

                if len(em.description) + len(to_add) > 4096:
                    embeds.append(em)
                    em = _make_embed()

                em.description += to_add

                if line_index == len(self.bookmarks):
                    embeds.append(em)

        self.items = embeds
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
        if interaction.response.is_done():  # noqa
            response_function = interaction.edit_original_response
        else:
            response_function = interaction.response.edit_message  # noqa
        if len(self.bookmarks) == 0:
            await response_function(  # noqa
                view=None, embed=Embed(bot=self.bot, title="You have no more bookmarks.")
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

    def _get_display_embed(self) -> Embed:
        if self.view_type == BookmarkViewType.TEXT:
            return self.text_view_embeds[self.text_page_index]
        else:
            idx = self.visual_item_index
            scanlator = get_manga_scanlator_class(
                SCANLATORS, key=self.bookmarks[idx].manga.scanlator
            )
            return create_bookmark_embed(
                self.bot, self.bookmarks[idx], scanlator.icon_url
            )

    def _handle_index_change(self):
        if self.text_page_index > len(self.text_view_embeds) - 1:
            self.text_page_index = 0
        elif self.text_page_index < 0:
            self.text_page_index = len(self.text_view_embeds) - 1

        if self.visual_item_index > len(self.bookmarks) - 1:
            self.visual_item_index = 0
        elif self.visual_item_index < 0:
            self.visual_item_index = len(self.bookmarks) - 1

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
            items: list[Union[str, int, Embed]] = None,
            interaction: Union[discord.Interaction, Context] = None,
            timeout: float = 3 * 3600,  # 3 hours,
            *args,
            **kwargs
    ) -> None:
        self.items = items
        self.interaction: discord.Interaction = interaction
        self.page: int = 0
        self.message: Optional[discord.Message] = None

        if not self.items and not self.interaction:
            raise AttributeError(
                "A list of items of type 'Union[str, int, Embed]' was not provided to iterate through as well as the "
                "interaction."
            )

        elif not items:
            raise AttributeError(
                "A list of items of type 'Union[str, int, Embed]' was not provided to iterate through."
            )

        elif not interaction:
            raise AttributeError("The command interaction was not provided.")

        if not isinstance(items, Iterable):
            raise AttributeError(
                "An iterable containing items of type 'Union[str, int, Embed]' classes is required."
            )

        elif not all(isinstance(item, (str, int, Embed)) for item in items):
            raise AttributeError(
                "All items within the iterable must be of type 'str', 'int' or 'Embed'."
            )

        super().__init__(timeout=timeout)
        self.items = list(self.items)
        if len(self.items) == 1:  # no need to paginate if there's only one item to display
            for _child in self.children:
                if _child.row == 0:
                    self.remove_item(_child)

    def __get_response_kwargs(self):
        if isinstance(self.items[self.page], Embed):
            return {"embed": self.items[self.page]}
        else:
            return {"content": self.items[self.page]}

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
            self.page = len(self.items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red, row=0)
    async def _stop(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(view=None)  # noqa
        self.stop()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple, row=0)
    async def forward(self, interaction: discord.Interaction, _):
        self.page += 1
        if self.page == len(self.items):
            self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple, row=0)
    async def _last_page(
            self, interaction: discord.Interaction, _
    ):
        self.page = len(self.items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if isinstance(self.interaction, discord.Interaction):
            author = self.interaction.user
        else:
            author = self.interaction.author

        if author.id == interaction.user.id:
            return True
        else:
            embed = Embed(bot=interaction.client, title=f"🚫 You cannot use this menu!", color=0xFF0000)
            await interaction.response.send_message(embed=embed, ephemeral=True)  # noqa
            return False

    async def on_timeout(self) -> None:
        if self.message is not None:
            await self.message.edit(view=None)
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
            em = Embed(bot=interaction.client,
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
            items: list[Union[str, int, Embed]] = None,
            author_id: int = None
    ) -> None:
        self.bot: MangaClient = bot
        self.items = [item for item in items if item is not None] if items else None
        self.page: int = 0
        self.author_id: int = author_id

        if not self.author_id:
            pass

        elif not isinstance(items, Iterable):
            raise AttributeError(
                "An iterable containing items of type 'Union[str, int, Embed]bot=self.bot,' classes is required."
            )

        elif not all(isinstance(item, Embed) for item in self.items):
            raise AttributeError(
                "All items within the iterable must be of type 'Embed'bot=self.bot,."
            )

        super().__init__(timeout=None)
        if self.items:
            self.items = list(self.items)
        else:
            self._delete_nav_buttons()

    def __get_response_kwargs(self):
        if isinstance(self.items[self.page], Embed):
            return {"embed": self.items[self.page]}
        else:
            return {"content": self.items[self.page]}

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
            self.page = len(self.items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red, custom_id="nav_stop", row=0)
    async def _stop(self, interaction: discord.Interaction, _):
        self._delete_nav_buttons()
        await interaction.response.edit_message(view=self)  # noqa

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple, custom_id="nav_right", row=0)
    async def forward(self, interaction: discord.Interaction, _):
        self.page += 1
        if self.page == len(self.items):
            self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())  # noqa

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple, custom_id="nav_fast_right", row=0)
    async def _last_page(
            self, interaction: discord.Interaction, _
    ):
        self.page = len(self.items) - 1
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

        scanlator: ABCScan = get_manga_scanlator_class(SCANLATORS, manga_home_url)

        manga_url: str = manga_home_url
        series_id = await scanlator.get_manga_id(manga_url)

        manga: Manga | None = await respond_if_limit_reached(
            scanlator.make_manga_object(series_id, manga_url),
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

        if not await self.bot.db.is_manga_tracked(interaction.guild_id, manga.id):
            if not interaction.user.guild_permissions.manage_roles:
                return await interaction.followup.send(
                    embed=Embed(bot=self.bot,
                                title="🚫 Missing Permissions",
                                description="You are missing the `Manage Roles` to track this manhwa.\n"
                                            "Inform a staff memebr to track this manhwa before you can subscribe!",
                                ).set_author(name=self.bot.user.global_name, icon_url=self.bot.user.display_avatar.url),
                )
            else:
                # check if the manga ID already has a ping role in DB
                guild_config = await self.bot.db.get_guild_config(interaction.guild_id)
                if not guild_config:
                    em = Embed(bot=self.bot,
                               title="Error",
                               description="This server has not been setup yet.\nUse `/config setup` to setup the bot.",
                               color=0xFF0000,
                               )
                    em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
                    await interaction.response.send_message(embed=em, ephemeral=True)  # noqa
                    return

                ping_role: discord.Role | None = None
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
                await self.bot.db.upsert_guild_sub_role(interaction.guild_id, manga.id, ping_role)
                await self.bot.db.subscribe_user(interaction.user.id, interaction.guild_id, manga.id)
                await interaction.response.followup.send(  # noqa
                    embed=Embed(bot=self.bot,
                                title="Subscribed to Series",
                                color=discord.Color.green(),
                                description=f"Successfully tracked and subscribed to **{manga}!**",
                                )
                )
                return

        current_user_subs: list[Manga] = await self.bot.db.get_user_guild_subs(
            interaction.guild_id, interaction.user.id
        )
        if current_user_subs:
            for manga in current_user_subs:
                if manga.id == series_id:
                    em = Embed(bot=self.bot,
                               title="Already Subscribed", color=discord.Color.red()
                               )
                    em.description = "You are already subscribed to this series."
                    em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
                    return await interaction.followup.send(embed=em, ephemeral=True)

        await self.bot.db.subscribe_user(
            interaction.user.id, interaction.guild_id, manga.id
        )

        embed = Embed(bot=self.bot,
                      title="Subscribed to Series",
                      color=discord.Color.green(),
                      description=f"Successfully subscribed to **[{manga.human_name}]({manga.url})!**",
                      )
        embed.set_image(url=manga.cover_url)
        embed.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="\u200b", style=discord.ButtonStyle.grey, disabled=True, custom_id="none_one")
    async def _none_one(self, interaction: discord.Interaction, _):
        pass

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
        scanlator = get_manga_scanlator_class(SCANLATORS, url=manga_url)

        # get the ID:
        manga_id = await scanlator.get_manga_id(manga_url)
        user_bookmarks = await self.bot.db.get_user_bookmarks(interaction.user.id)
        if user_bookmarks:
            for bookmark in user_bookmarks:
                if bookmark.manga.id == manga_id:
                    return await interaction.followup.send(embed=Embed(
                        bot=self.bot,
                        title="Already Bookmarked",
                        description="You have already bookmarked this series.",
                        color=discord.Color.red()
                    ), ephemeral=True)
        # make bookmark obj
        bookmark_obj = await scanlator.make_bookmark_object(
            manga_id, manga_url, interaction.user.id, interaction.guild_id, user_created=True
        )
        await self.bot.db.upsert_bookmark(bookmark_obj)

        embed = Embed(
            bot=self.bot,
            title="Bookmarked!",
            color=discord.Color.green(),
            description=f"Successfully bookmarked **[{bookmark_obj.manga.human_name}]({bookmark_obj.manga.url})**",
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
                embed = Embed(bot=self.bot,
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
        else:
            traceback = "".join(
                tb.format_exception(type(error), error, error.__traceback__)
            )
            em = Embed(bot=self.bot,
                       title=f"🚫 An unknown error occurred!",
                       description=f"{traceback[-2000:]}",
                       color=0xFF0000,
                       )
            interaction.client.logger.error(traceback)
            if interaction.response.is_done():  # noqa
                await interaction.followup.send(embed=em, ephemeral=True)
            else:
                await interaction.response.send_message(embed=em, ephemeral=True)  # noqa


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
        label="☑️ Mark Read", style=discord.ButtonStyle.green, custom_id="btn_mark_read"
    )
    async def mark_read(self, interaction: discord.Interaction, btn: Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
        manga_id, chapter_index = self._extract_keys(interaction, btn)

        bookmark: Bookmark = await self.bot.db.get_user_bookmark(
            interaction.user.id, manga_id
        )
        if bookmark is None:
            manga: Manga = await self.bot.db.get_series(manga_id)
            bookmark = Bookmark(
                interaction.user.id,
                manga,
                None,  # temp value, will be updated below # noqa
                interaction.guild_id,
            )

        if bookmark.last_read_chapter == bookmark.manga.available_chapters[chapter_index]:
            return await interaction.followup.send(
                embed=Embed(bot=self.bot,
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
            embed=Embed(bot=self.bot,
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
        manga_id, chapter_index = self._extract_keys(interaction, btn)

        bookmark: Bookmark = await self.bot.db.get_user_bookmark(
            interaction.user.id, manga_id
        )
        if bookmark is None:
            return await interaction.followup.send(
                embed=Embed(bot=self.bot,
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
                    interaction.user.id, bookmark.manga.id
                )
            del_bookmark_view = DeleteBookmarkView(self.bot, interaction, manga_id)
            del_bookmark_view.message = await interaction.followup.send(
                embed=Embed(bot=self.bot,
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
                embed=Embed(bot=self.bot,
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
        manga_id, _ = self._extract_keys(interaction, btn)

        bookmark: Bookmark = await self.bot.db.get_user_bookmark(
            interaction.user.id, manga_id
        )
        if bookmark is None:
            return await interaction.followup.send(
                embed=Embed(bot=self.bot,
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
            embed=Embed(bot=self.bot,
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
    ) -> tuple[str, int]:
        key_message = interaction.message.content.split("||")[1]
        manga_id, chapter_index = key_message.split(" | ")
        manga_id = manga_id.strip().lstrip("<Manga ID: ")
        chapter_index = chapter_index.strip().lstrip("Chapter Index: ").rstrip(">")

        return manga_id, int(chapter_index)

    async def on_error(
            self,
            interaction: discord.Interaction,
            error: Exception,
            item: discord.ui.Button,
            /,
    ) -> None:
        traceback = "".join(
            tb.format_exception(type(error), error, error.__traceback__)
        )
        self.bot.logger.error(traceback)
        if not interaction.response.is_done():  # noqa
            await interaction.response.send_message(  # noqa
                f"An error occurred: ```py\n{traceback[-1800:]}```", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"An error occurred: ```py\n{traceback[-1800:]}```", ephemeral=True
            )


class DeleteBookmarkView(BaseView):
    def __init__(self, bot: MangaClient, interaction: discord.Interaction, manga_id: str):
        super().__init__(bot, interaction=interaction)
        self.manga_id: str = manga_id

    @discord.ui.button(label="Delete 'hidden bookmark'", style=discord.ButtonStyle.red)
    async def delete_last_read(self, interaction: discord.Interaction, btn: Button):
        btn.disabled = True
        await interaction.response.edit_message(view=self)  # noqa

        confirm_view: ConfirmView = ConfirmView(self.bot, interaction)
        confirm_view.message = await interaction.followup.send(
            embed=Embed(bot=self.bot,
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
        await self.bot.db.delete_bookmark(interaction.user.id, self.manga_id)
        await confirm_view.message.edit(
            embed=Embed(bot=self.bot,
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
                style=discord.ButtonStyle.blurple,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Invite",
                url="https://discord.com/api/oauth2/authorize?client_id=1031998059447590955&permissions=412854111296"
                    "&scope=bot%20applications.commands",
                style=discord.ButtonStyle.blurple,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="GitHub",
                url="https://github.com/MooshiMochi/ManhwaUpdatesBot",
                style=discord.ButtonStyle.blurple,
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
                embed=Embed(bot=interaction.client,
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
                embed=Embed(bot=interaction.client,
                            title="No Untracked Manhwa",
                            description="You are not subscribed to any untracked manhwa.",
                            color=discord.Color.red(),
                            ),
                ephemeral=True,
            )

        confirm_view: ConfirmView = ConfirmView(bot, interaction)
        confirm_view.message = await interaction.followup.send(
            embed=Embed(bot=interaction.client,
                        title="Are you sure?",
                        description=f"Are you sure you want to unsubscribe from all untracked manhwa?",
                        color=discord.Color.red()
                        ),
            ephemeral=True,
            view=confirm_view
        )
        await confirm_view.wait()

        if confirm_view.value is None or confirm_view.value is False:  # cancelled = False
            button.disabled = False
            await interaction.edit_original_response(view=self)
            await confirm_view.message.delete()
            return

        if self.is_global_view:
            unsub_count = await bot.db.unsubscribe_user_from_all_untracked(interaction.user.id)
        else:
            unsub_count = await bot.db.unsubscribe_user_from_all_untracked(interaction.user.id, interaction.guild_id)

        await confirm_view.message.edit(
            embed=Embed(bot=interaction.client,
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
        self.guild_config: GuildSettings = guild_config
        self.selected_option: str | None = None

        self.child_map: dict[
            int | str, discord.ui.Select | list[discord.ui.Button]] = {
            child.row: child for child in self.children
        }
        self.child_map.pop(4)

        self.child_map["default"] = self.child_map.pop(0)
        self.child_map["bool"] = self.child_map.pop(1)
        self.child_map["channel"] = self.child_map.pop(2)
        self.child_map["role"] = self.child_map.pop(3)
        self.child_map["buttons"]: list[discord.ui.Button] = [x for x in self.children if x.row == 4]  # noqa

        self.clear_items()
        self._refresh_components()

    def _create_embed(self) -> discord.Embed:
        channel = self.guild_config.notifications_channel
        role = self.guild_config.default_ping_role
        auto_create_role = self.guild_config.auto_create_role
        dev_ping = self.guild_config.dev_notifications_ping
        show_update_buttons = self.guild_config.show_update_buttons

        text = f"""
        **#️⃣ Updates Channel:** {channel.mention if channel else "Nont set."}
        \u200b \u200b \u200b **^** `The channel the bot will send chapter updates to.`
        **🔔 Default Ping Role:** {role.mention if role else "Not set."}
        \u200b \u200b \u200b **^** `The role that will be pinged for all updates.`
        **🔄️ Auto Create Role:** {'Yes' if auto_create_role else 'No'}
        \u200b \u200b \u200b **^** `Whether to auto create roles for new tracked manhwa.`
        **👨‍💻 Ping for Developer Updates:** {'Yes' if dev_ping else 'No'}
        \u200b \u200b \u200b **^** `Whether to ping for developer updates.`
        **🔘Show Update Buttons:** {'Yes' if show_update_buttons else 'No'}
        \u200b \u200b \u200b **^** `Whether to show buttons for chapter updates.`
        """
        return Embed(
            bot=self.bot,
            title="Settings",
            description=f"__Select the setting you want to edit.__\n{text}",
            color=discord.Color.blurple(),
        )

    def _refresh_components(self):
        self.clear_items()
        if self.selected_option is None or self.selected_option == "default":
            self.add_item(self.child_map["default"])
            for item in self.child_map["buttons"]:
                self.add_item(item)
        elif self.selected_option == "channel":
            self.add_item(self.child_map["channel"])
        elif self.selected_option == "default_ping_role":
            self.add_item(self.child_map["role"])
        elif self.selected_option in ["auto_create_role", "dev_ping", "show_update_buttons"]:
            self.add_item(self.child_map["bool"])
        else:
            raise ValueError(f"Invalid value: {self.selected_option}")

    @discord.ui.select(
        options=[
            discord.SelectOption(label="Change the updates channel", value="channel", emoji="#️⃣"),
            discord.SelectOption(label="Set Default ping role", value="default_ping_role", emoji="🔔"),
            discord.SelectOption(label="Auto create role for new tracked manhwa", value="auto_create_role", emoji="🔄"),
            discord.SelectOption(label="Ping for developer notifications", value="dev_ping", emoji="👨‍💻"),
            discord.SelectOption(label="Show buttons for chapter updates", value="show_update_buttons", emoji="🔘"),
        ],
        max_values=1,
        min_values=1,
        placeholder="Select the option to edit.",
        row=0
    )
    async def _default_select_callback(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        embed = self._create_embed()
        self.selected_option = select.values[0]
        self._refresh_components()
        await interaction.response.edit_message(embed=embed, view=self)  # noqa

    @discord.ui.select(
        options=[
            discord.SelectOption(label="Enabled", value="True", emoji="✅"),
            discord.SelectOption(label="Disabled", value="False", emoji="❌"),
        ],
        max_values=1,
        min_values=1,
        placeholder="Set to Enabled or Disabled.",
        row=1
    )
    async def _bool_select_callback(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        if self.selected_option == "auto_create_role":
            self.guild_config.auto_create_role = select.values[0] == "True"
        elif self.selected_option == "dev_ping":
            self.guild_config.dev_notifications_ping = select.values[0] == "True"
        elif self.selected_option == "show_update_buttons":
            self.guild_config.show_update_buttons = select.values[0] == "True"
        else:
            raise ValueError(f"Invalid value: {self.selected_option}")
        self.selected_option = None
        self._refresh_components()
        embed = self._create_embed()
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
            embed = self._create_embed()
            self.selected_option = None
            self._refresh_components()
            await interaction.response.edit_message(embed=embed, view=self)  # noqa
            await interaction.followup.send(  # noqa
                embed=Embed(
                    bot=self.bot,
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
            ("Embed Links", my_perms.embed_links)
        ]
        if not all([x[1] for x in required_perms]):
            embed = self._create_embed()
            self.selected_option = None
            self._refresh_components()
            await interaction.response.edit_message(embed=embed, view=self)  # noqa
            perms = ", ".join(x[0] for x in required_perms)  # noqa
            await interaction.followup.send(  # noqa
                embed=Embed(
                    bot=interaction.client,
                    title=f"Missing Required Permissions",
                    colour=discord.Colour.red(),
                    description=f"Sorry, I don't have the required permissions `{perms}` for "
                                + f"the {channel.mention}.\nPlease ask a server administrator to fix this issue.",
                ),
                ephemeral=True
            )
            return
        self.guild_config.notifications_channel = channel
        self.selected_option = None
        self._refresh_components()
        embed = self._create_embed()
        await interaction.response.edit_message(embed=embed, view=self)  # noqa

    @discord.ui.select(cls=discord.ui.RoleSelect, row=3, placeholder="Select a default role to ping for updates.")
    async def _role_select_callback(self, interaction: discord.Interaction, select: discord.ui.RoleSelect) -> None:
        role_id = select.values[0].id
        role = interaction.guild.get_role(role_id)
        if not role:
            embed = self._create_embed()
            self.selected_option = None
            self._refresh_components()
            await interaction.response.edit_message(embed=embed, view=self)  # noqa
            await interaction.followup.send(  # noqa
                embed=Embed(
                    bot=self.bot,
                    title="Role not found",
                    description=f"Could not find the <@&{role_id}> role!\n"
                                f"Please ensure I have all required permissions.",
                    colour=discord.Colour.red()
                ),
                ephemeral=True
            )
            return
        elif role.position >= interaction.guild.me.top_role.position:
            embed = self._create_embed()
            self.selected_option = None
            self._refresh_components()
            await interaction.response.edit_message(embed=embed, view=self)  # noqa
            await interaction.followup.send(  # noqa
                embed=Embed(
                    bot=self.bot,
                    title="Role too high",
                    description=f"The <@&{role_id}> role is too high for me to ping!\n"
                                f"Please move it below my top role.",
                    colour=discord.Colour.red(),
                ),
                ephemeral=True
            )
            return
        self.guild_config.default_ping_role = role
        self.selected_option = None
        self._refresh_components()
        embed = self._create_embed()
        await interaction.response.edit_message(embed=embed, view=self)  # noqa

    @discord.ui.button(label="Done", emoji="☑️", style=discord.ButtonStyle.green, row=4)
    async def done_btn_callback(self, interaction: discord.Interaction, _) -> None:
        if not self.guild_config.notifications_channel:
            await interaction.response.send_message(  # noqa
                embed=Embed(
                    bot=self.bot,
                    title="Channel not set",
                    description="You must set a channel to send updates to.",
                    color=discord.Color.red(),
                ),
                ephemeral=True
            )
            return

        await self.bot.db.upsert_config(self.guild_config)
        await interaction.response.edit_message(view=None)  # noqa
        await interaction.followup.send(  # noqa
            embed=Embed(
                bot=self.bot,
                title="Settings Updated",
                description="Successfully updated the settings.",
                color=discord.Color.green(),
            ),
            ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Delete config", emoji="🗑️", style=discord.ButtonStyle.red, row=4)
    async def delete_config_btn_callback(self, interaction: discord.Interaction, _) -> None:
        await self.bot.db.delete_config(interaction.guild_id)
        await interaction.response.edit_message(view=None)  # noqa
        bot_created_roles = await self.bot.db.get_all_guild_bot_created_roles(interaction.guild_id)
        embed = Embed(
            bot=self.bot,
            title="Guild config deleted",
            description="Successfully deleted guild settings.",
            color=discord.Color.green(),
        )
        view: ConfirmView | None = None
        send_kwargs = {"embed": embed, "wait": True, "ephemeral": True}
        if bot_created_roles:
            extra = f"Would you like the bot to delete all {len(bot_created_roles)} it created?"
            embed.description += "\n" + extra
            view = ConfirmView(self.bot, interaction)
            send_kwargs["view"] = view

        msg = await interaction.followup.send(**send_kwargs)
        if view is not None:
            await view.wait()
            if view.value is False or view.value is None:
                return await msg.edit(view=None, embed=Embed(
                    bot=self.bot,
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
                    embed=Embed(
                        bot=self.bot,
                        title="Deleted Roles",
                        description=f"Successfully deleted {success_count} roles.",
                        color=discord.Color.green(),
                    ),
                    ephemeral=True
                )
                await self.bot.db.delete_all_guild_created_roles(interaction.guild_id)
        self.stop()

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.red, row=4)
    async def cancel_btn_callback(self, interaction: discord.Interaction, _) -> None:
        await interaction.response.edit_message(  # noqas
            embed=Embed(
                bot=self.bot,
                title="Cancelled",
                description="Setting changes have been cancelled.",
                color=discord.Color.green(),
            ),
            view=None
        )
        self.stop()
