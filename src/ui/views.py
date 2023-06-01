from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from src.core import MangaClient

import traceback as tb
from discord.ext.commands import Context
from discord.ui import View, Button
import discord
from discord import ButtonStyle
from src.utils import create_bookmark_embed, sort_bookmarks, group_items_by, get_manga_scanlator_class
from src.core.objects import Bookmark, ABCScan, Manga
from .selects import SortTypeSelect, ViewTypeSelect
from src.core.scanners import SCANLATORS
from functools import partial
from .buttons import CustomButtonCallbacks
from src.enums import BookmarkSortType, BookmarkViewType
from src.core.errors import MangaCompletedOrDropped
from discord.ext import commands


class BaseView(View):
    def __init__(
            self, bot: MangaClient,
            interaction: discord.Interaction | Context = None,
            timeout: float = 60.0
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
            self, interaction: discord.Interaction, error: Exception, item: discord.ui.Button, /
    ) -> None:
        self.bot.logger.error(
            tb.print_exception(type(error), error, error.__traceback__)
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
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

        self.add_item(Button(style=ButtonStyle.grey, label="\u200b", disabled=True, row=3))
        update_btn = Button(style=ButtonStyle.blurple, label="Update", custom_id="update_btn", row=3)
        update_btn.callback = partial(self._btn_callbacks.update_button_callback)

        search_btn = Button(style=ButtonStyle.blurple, label="Search", custom_id="search_btn", row=3)
        search_btn.callback = partial(self._btn_callbacks.search_button_callback)

        delete_btn = Button(style=ButtonStyle.red, label="Delete", custom_id="delete_btn", row=3)
        delete_btn.callback = partial(self._btn_callbacks.delete_button_callback)

        self.add_item(update_btn)
        self.add_item(search_btn)
        self.add_item(delete_btn)

        self.add_item(Button(style=ButtonStyle.grey, label="\u200b", disabled=True, row=3))
        return self

    def _load_text_components_preset(self) -> Self:
        self.clear_components()
        self.add_item(SortTypeSelect(self.sort_type, row=1))
        self.add_item(ViewTypeSelect(self.view_type, row=2))

        def _add_blank_buttons():
            for _ in range(2):
                self.add_item(Button(style=ButtonStyle.grey, label="\u200b", disabled=True, row=3))

        _add_blank_buttons()
        search_btn = Button(style=ButtonStyle.blurple, label="Search", custom_id="search_btn", row=3)
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
            return discord.Embed(title=f"Bookmarks ({len(self.bookmarks)})", color=discord.Color.blurple(),
                                 description="")

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

        await interaction.response.edit_message(view=view, embed=self._get_display_embed())

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
            scanlator = get_manga_scanlator_class(SCANLATORS, key=self.bookmarks[idx].manga.scanlator)
            return create_bookmark_embed(self.bot, self.bookmarks[idx], scanlator.icon_url)

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
    async def _first_page(
            self, interaction: discord.Interaction, _
    ):
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
    async def forward(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._increment_index(1)
        await interaction.response.edit_message(embed=self._get_display_embed())

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple, row=0)
    async def _last_page(
            self, interaction: discord.Interaction, _
    ):
        self._increment_index(float("-inf"))  # this will set index to max internally
        await interaction.response.edit_message(embed=self._get_display_embed())


class SubscribeView(View):
    def __init__(
            self,
            bot: MangaClient,
    ):
        super().__init__(timeout=None)
        self.bot: MangaClient = bot

    @discord.ui.button(
        label="Subscribe",
        style=ButtonStyle.blurple,
        emoji="📚",
        custom_id="search_subscribe",
    )
    async def subscribe(self, interaction: discord.Interaction, _):

        message: discord.Message = interaction.message
        manga_home_url = message.embeds[0].fields[-1].value

        scanlator: ABCScan = get_manga_scanlator_class(SCANLATORS, manga_home_url)

        manga_url: str = manga_home_url
        series_id = await scanlator.get_manga_id(self.bot, manga_url)

        current_user_subs: list[Manga] = await self.bot.db.get_user_subs(
            interaction.user.id
        )
        for manga in current_user_subs:
            if manga.id == series_id:
                em = discord.Embed(
                    title="Already Subscribed", color=discord.Color.red()
                )
                em.description = "You are already subscribed to this series."
                em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
                return await interaction.response.send_message(embed=em, ephemeral=True)

        manga: Manga = await scanlator.make_manga_object(self.bot, series_id, manga_url)

        if manga.completed:
            raise MangaCompletedOrDropped(manga.url)

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

        await interaction.response.send_message(embed=embed, ephemeral=True)


class ConfirmView(BaseView):
    def __init__(self, bot: MangaClient, interaction_or_ctx: discord.Interaction | commands.Context):
        super().__init__(bot, interaction_or_ctx)
        self.value = None

    @discord.ui.button(label='Confirm', style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=False)
        self.value = True
        self.stop()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=False)
        self.value = False
        self.stop()
