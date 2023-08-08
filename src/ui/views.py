from __future__ import annotations

from typing import Iterable, Optional, Self, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from src.core import MangaClient

import discord
import traceback as tb

from functools import partial

from discord import ButtonStyle
from discord.ext import commands
from discord.ui import View, Button
from discord.ext.commands import Context

from src.core.objects import Bookmark, ABCScan, Manga
from src.core.scanners import SCANLATORS
from src.core.errors import MangaCompletedOrDropped

from src.utils import (
    create_bookmark_embed,
    respond_if_limit_reached, sort_bookmarks,
    group_items_by,
    get_manga_scanlator_class
)
from src.enums import BookmarkSortType, BookmarkViewType

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
                embed=discord.Embed(
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
        self.bot.logger.error(
            tb.print_exception(type(error), error, error.__traceback__)
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"An error occurred: ```py\n{str(error)[-1800:]}```", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"An error occurred: ```py\n{str(error)[-1800:]}```", ephemeral=True
            )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if isinstance(self.interaction_or_ctx, discord.Interaction):
            author = self.interaction_or_ctx.user
        else:
            author = self.interaction_or_ctx.author

        if author.id == interaction.user.id:
            return True
        else:
            embed = discord.Embed(title=f"🚫 You cannot use this menu!", color=0xFF0000)
            await interaction.response.send_message(embed=embed, ephemeral=True)
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
        self.text_view_embeds: list[discord.Embed] = self._bookmarks_to_text_embeds()

        self.text_page_index = 0
        self.visual_item_index = 0

        self._btn_callbacks = CustomButtonCallbacks(self.bot, self)
        self.load_components()

    def _load_visual_components_preset(self) -> Self:
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
        delete_btn.callback = partial(self._btn_callbacks.delete_button_callback)

        self.add_item(update_btn)
        self.add_item(search_btn)
        self.add_item(delete_btn)

        self.add_item(
            Button(style=ButtonStyle.grey, label="\u200b", disabled=True, row=3)
        )
        return self

    def _load_text_components_preset(self) -> Self:
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

    def load_components(self) -> Self:
        if self.view_type == BookmarkViewType.VISUAL:
            self._load_visual_components_preset()
        else:
            self._load_text_components_preset()
        return self

    def _bookmarks_to_text_embeds(self) -> list[discord.Embed]:
        self.bookmarks = sort_bookmarks(self.bookmarks, self.sort_type)
        grouped = group_items_by(self.bookmarks, ["manga.scanlator"])
        embeds: list[discord.Embed] = []

        def _make_embed() -> discord.Embed:
            return discord.Embed(
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

    def clear_components(self) -> Self:
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

    async def update(self, interaction: discord.Interaction, view: Self | None = None):
        if view is None:
            view = self
        if len(self.bookmarks) == 0:
            await interaction.response.edit_message(
                view=None, embed=discord.Embed(title="You have no more bookmarks.")
            )
            self.stop()
            return

        await interaction.response.edit_message(
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
        self._increment_index(float("inf"))  # this will set index to 0 internally
        await interaction.response.edit_message(embed=self._get_display_embed())

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple, row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._increment_index(-1)
        await interaction.response.edit_message(embed=self._get_display_embed())

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red, row=0)
    async def _stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple, row=0)
    async def forward(
            self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self._increment_index(1)
        await interaction.response.edit_message(embed=self._get_display_embed())

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple, row=0)
    async def _last_page(self, interaction: discord.Interaction, _):
        self._increment_index(float("-inf"))  # this will set index to max internally
        await interaction.response.edit_message(embed=self._get_display_embed())


class PaginatorView(discord.ui.View):
    def __init__(
            self,
            items: list[Union[str, int, discord.Embed]] = None,
            interaction: Union[discord.Interaction, Context] = None,
            timeout: float = 3 * 3600  # 3 hours
    ) -> None:
        self.items = items
        self.interaction: discord.Interaction = interaction
        self.page: int = 0
        self.message: Optional[discord.Message] = None

        if not self.items and not self.interaction:
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
        self.items = list(self.items)

    def __get_response_kwargs(self):
        if isinstance(self.items[self.page], discord.Embed):
            return {"embed": self.items[self.page]}
        else:
            return {"content": self.items[self.page]}

    @discord.ui.button(label=f"⏮️", style=discord.ButtonStyle.blurple)
    async def _first_page(
            self, interaction: discord.Interaction, _
    ):
        self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple)
    async def back(self, interaction: discord.Interaction, _):
        self.page -= 1
        if self.page == -1:
            self.page = len(self.items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red)
    async def _stop(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple)
    async def forward(self, interaction: discord.Interaction, _):
        self.page += 1
        if self.page == len(self.items):
            self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple)
    async def _last_page(
            self, interaction: discord.Interaction, _
    ):
        self.page = len(self.items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if isinstance(self.interaction, discord.Interaction):
            author = self.interaction.user
        else:
            author = self.interaction.author

        if author.id == interaction.user.id:
            return True
        else:
            embed = discord.Embed(title=f"🚫 You cannot use this menu!", color=0xFF0000)
            await interaction.response.send_message(embed=embed, ephemeral=True)
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
            em = discord.Embed(
                title=f"🚫 An unknown error occurred!",
                description=f"{str(error)[-1500:]}",
                color=0xFF0000,
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=em, ephemeral=True)
            else:
                await interaction.response.send_message(embed=em, ephemeral=True)


class SubscribeView(View):
    def __init__(
            self,
            bot: MangaClient,
            items: list[Union[str, int, discord.Embed]] = None,
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
                "An iterable containing items of type 'Union[str, int, discord.Embed]' classes is required."
            )

        elif not all(isinstance(item, discord.Embed) for item in self.items):
            raise AttributeError(
                "All items within the iterable must be of type 'discord.Embed'."
            )

        super().__init__(timeout=None)
        if self.items:
            self.items = list(self.items)

    def __get_response_kwargs(self):
        if isinstance(self.items[self.page], discord.Embed):
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
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple, custom_id="nav_left", row=0)
    async def back(self, interaction: discord.Interaction, _):
        self.page -= 1
        if self.page == -1:
            self.page = len(self.items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red, custom_id="nav_stop", row=0)
    async def _stop(self, interaction: discord.Interaction, _):
        self._delete_nav_buttons()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple, custom_id="nav_right", row=0)
    async def forward(self, interaction: discord.Interaction, _):
        self.page += 1
        if self.page == len(self.items):
            self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple, custom_id="nav_fast_right", row=0)
    async def _last_page(
            self, interaction: discord.Interaction, _
    ):
        self.page = len(self.items) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(
        label="Subscribe",
        style=ButtonStyle.blurple,
        emoji="📚",
        custom_id="search_subscribe",
    )
    async def subscribe(self, interaction: discord.Interaction, _):
        await interaction.response.defer(thinking=True, ephemeral=True)

        message: discord.Message = interaction.message
        manga_home_url = message.embeds[0].url

        scanlator: ABCScan = get_manga_scanlator_class(SCANLATORS, manga_home_url)

        manga_url: str = manga_home_url
        series_id = await scanlator.get_manga_id(self.bot, manga_url)

        current_user_subs: list[Manga] = await self.bot.db.get_user_subs(
            interaction.user.id
        )
        if current_user_subs:
            for manga in current_user_subs:
                if manga.id == series_id:
                    em = discord.Embed(
                        title="Already Subscribed", color=discord.Color.red()
                    )
                    em.description = "You are already subscribed to this series."
                    em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
                    return await interaction.followup.send(embed=em, ephemeral=True)

        manga: Manga | None = await respond_if_limit_reached(
            scanlator.make_manga_object(self.bot, series_id, manga_url),
            interaction
        )
        if manga == "LIMIT_REACHED":
            return

        if manga.completed:
            raise MangaCompletedOrDropped(manga.url)

        # by default, searching for a manga will save it to DB, so no need to re-add it to database
        # But we will add it anyway in case of any updates to the manga.
        # Even though if it's saved in DB, it will get fetched from DB so that doesn't really make sense,
        # but it is what it is.
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
        await interaction.response.defer(thinking=True, ephemeral=True)

        manga_url = interaction.message.embeds[0].url
        # get the scanlator
        scanlator = get_manga_scanlator_class(SCANLATORS, url=manga_url)

        # get the ID:
        manga_id = await scanlator.get_manga_id(self.bot, manga_url)
        user_bookmarks = await self.bot.db.get_user_bookmarks(interaction.user.id)
        if user_bookmarks:
            for bookmark in user_bookmarks:
                if bookmark.manga.id == manga_id:
                    return await interaction.followup.send(embed=discord.Embed(
                        title="Already Bookmarked",
                        description="You have already bookmarked this series.",
                        color=discord.Color.red()
                    ), ephemeral=True)
        # make bookmark obj
        bookmark_obj = await scanlator.make_bookmark_object(
            self.bot, manga_id, manga_url, interaction.user.id, interaction.guild_id
        )
        await self.bot.db.upsert_bookmark(bookmark_obj)

        embed = discord.Embed(
            title="Bookmarked!",
            color=discord.Color.green(),
            description=f"Successfully bookmarked **[{bookmark_obj.manga.human_name}]({bookmark_obj.manga.url})**",
        )
        embed.set_image(url=bookmark_obj.manga.cover_url)
        embed.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data["custom_id"]
        if custom_id.startswith("nav"):
            if self.author_id is None:
                self._delete_nav_buttons()
                await interaction.response.edit_message(view=self)
                # await interaction.followup.send(
                #     discord.Embed(
                #         title="🚫 There are no items to paginate!",
                #         color=0xFF0000,
                #         description="This menu has been updated. Please use any of the buttons below."
                #     )
                # )
                return False
            elif self.author_id == interaction.user.id:
                return True
            else:
                embed = discord.Embed(
                    title=f"🚫 You cannot use this menu!",
                    color=0xFF0000,
                    description="Try the buttons below. They should work 😉!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return False
        else:
            return True

    async def on_error(
            self, interaction: discord.Interaction, error: Exception, item
    ) -> None:
        if isinstance(error, TimeoutError):
            pass
        else:
            em = discord.Embed(
                title=f"🚫 An unknown error occurred!",
                description=f"{str(error)[-1500:]}",
                color=0xFF0000,
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=em, ephemeral=True)
            else:
                await interaction.response.send_message(embed=em, ephemeral=True)


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
        await interaction.response.defer(ephemeral=True, thinking=False)
        self.value = True
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=False)
        self.value = False
        self.stop()


class BookmarkChapterView(View):
    def __init__(self, bot: MangaClient):
        self.bot: MangaClient = bot
        super().__init__(timeout=None)  # View is persistent ∴ no timeout

    @discord.ui.button(
        label="✉️ Mark Read", style=discord.ButtonStyle.green, custom_id="btn_mark_read"
    )
    async def mark_read(self, interaction: discord.Interaction, btn: Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=False)
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
                embed=discord.Embed(
                    title="Already Read",
                    description="This chapter is already marked as read.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

        bookmark.last_read_chapter = bookmark.manga.available_chapters[chapter_index]
        bookmark.last_updated_ts = datetime.utcnow().timestamp()
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
        manga_id, chapter_index = self._extract_keys(interaction, btn)

        bookmark: Bookmark = await self.bot.db.get_user_bookmark(
            interaction.user.id, manga_id
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
                bookmark.last_updated_ts = datetime.utcnow().timestamp()
                await self.bot.db.upsert_bookmark(bookmark)
            else:
                await self.bot.db.delete_bookmark(
                    interaction.user.id, bookmark.manga.id
                )
            del_bookmark_view = DeleteBookmarkView(self.bot, interaction, manga_id)
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
        manga_id, _ = self._extract_keys(interaction, btn)

        bookmark: Bookmark = await self.bot.db.get_user_bookmark(
            interaction.user.id, manga_id
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

        last_read_index = bookmark.last_read_chapter.index
        next_chapter = next((x for x in bookmark.manga.available_chapters if x.index > last_read_index), None)
        next_not_available = "`Wait for updates!`" if bookmark.manga.completed else "`None, manga is finished!`"

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
        self.bot.logger.error(
            tb.print_exception(type(error), error, error.__traceback__)
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"An error occurred: ```py\n{str(error)[-1800:]}```", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"An error occurred: ```py\n{str(error)[-1800:]}```", ephemeral=True
            )


class DeleteBookmarkView(BaseView):
    def __init__(self, bot: MangaClient, interaction: discord.Interaction, manga_id: str):
        super().__init__(bot, interaction=interaction)
        self.manga_id: str = manga_id

    @discord.ui.button(label="Delete 'hidden bookmark'", style=discord.ButtonStyle.red)
    async def delete_last_read(self, interaction: discord.Interaction, btn: Button):
        btn.disabled = True
        await interaction.response.edit_message(view=self)

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
        await self.bot.db.delete_bookmark(interaction.user.id, self.manga_id)
        await confirm_view.message.edit(
            embed=discord.Embed(
                title="Deleted",
                description=f"Successfully deleted the 'hidden bookmark' for this manga.",
                color=discord.Color.green(),
            ),
            view=None
        )
        self.stop()
