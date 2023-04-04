from __future__ import annotations
from typing import TYPE_CHECKING, Literal, Self

if TYPE_CHECKING:
    from src.core import MangaClient

import traceback as tb
from discord.ext.commands import Context
from discord.ui import View, Button
import discord
from discord import ButtonStyle
from src.utils import create_bookmark_embed, sort_bookmarks, group_items_by, get_manga_scanlator_class
from src.core.objects import Bookmark
from .selects import SortTypeSelect, ViewTypeSelect
from src.core.scanners import SCANLATORS
from functools import partial
from .buttons import CustomButtonCallbacks
from src.enums import BookmarkSortType, BookmarkViewType


class BaseView(View):
    def __init__(
            self, bot: MangaClient,
            interaction: discord.Interaction | Context = None,
    ):
        super().__init__()
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
    def __init__(self, bot: MangaClient, interaction: discord.Interaction, bookmarks: list[Bookmark]):
        super().__init__(bot, interaction)
        self.bot: MangaClient = bot
        self.message: discord.Message | None = None
        self.bookmarks: list[Bookmark] = sort_bookmarks(bookmarks, BookmarkSortType.LAST_UPDATED_TIMESTAMP.value)

        self.page: int = 0
        self.view_type: Literal["visual", "text"] = BookmarkViewType.TEXT.value
        self.sort_type: Literal["a-z", "last_updated"] = BookmarkSortType.ALPHABETICAL.value

        self.external_components: dict[str, ...] = {}

        self.items: list[discord.Embed] = []

        self._btn_callbacks = CustomButtonCallbacks(self.bot, self, self.bookmarks)
        self.init_external_components()
        self.update_view_components()

        # free rows: 3, 4, 5

    def init_external_components(self):
        self.external_components["select"] = [
            [
                SortTypeSelect(row=1), True
            ],
            [
                ViewTypeSelect(
                    partial(create_bookmark_embed, self.bot),
                    partial(get_manga_scanlator_class, SCANLATORS),
                    row=2
                ), True
            ]
        ]
        self.external_components["button"] = [
            [self.make_empty_button(), True],
            [self.make_empty_button(), True],
            [Button(label="Search", style=ButtonStyle.blurple, row=3, custom_id="btn_search"), True],
            [self.make_empty_button(), True],
            [self.make_empty_button(), True],
        ]
        self.external_components["button"][2][0].callback = self._btn_callbacks.search_button_callback

    def update_view_components(self) -> "BookmarkView":
        for item in self.children:
            if item.row is not None and item.row > 0:
                self.remove_item(item)

        for key, components in self.external_components.items():
            for component, show in components:
                if not show or not component:
                    continue
                self.add_item(component)

        return self

    @staticmethod
    def make_empty_button() -> discord.Button:
        return Button(label="\u200b", style=ButtonStyle.grey, disabled=True, row=3)

    def to_visual_view(self) -> "BookmarkView":
        # if self.view_type == "visual":
        #     return self

        # items required:
        #   + [0] --> nav buttons (reserved)
        #   - [1] --> /sort_type select (hidden)/
        #   + [2] --> view_type select
        #   + [3] --> <empty>, <update>, <search>, <delete>, <empty> buttons
        #   - [4] --> /-----------------------/
        #   - [5] --> /-----------------------/

        self.view_type = BookmarkViewType.VISUAL.value

        self.external_components["button"][1] = [
            Button(
                label="Update", style=ButtonStyle.blurple, row=3, custom_id="btn_update"
                ), True
        ]
        self.external_components["button"][1][0].callback = self._btn_callbacks.update_button_callback

        self.external_components["button"][3] = [
            Button(
                label="Delete", style=ButtonStyle.blurple, row=3, custom_id="btn_delete"
            ), True
        ]
        self.external_components["button"][3][0].callback = self._btn_callbacks.delete_button_callback

        self.external_components["select"][0][1] = False
        self.sort_type = BookmarkSortType.LAST_UPDATED_TIMESTAMP.value
        self.bookmarks = sort_bookmarks(self.bookmarks, self.sort_type)

        return self.update_view_components()

    def to_text_view(self) -> "BookmarkView":
        # if self.view_type == "text":
        #     return self

        # items required:
        #   + [0] --> nav buttons (reserved)
        #   + [1] --> sort_type select
        #   + [2] --> view_type select
        #   + [3] --> <empty>, <empty>, <search>, <empty>, <empty> buttons
        #   - [4] --> /-----------------------/
        #   - [5] --> /-----------------------/

        self.view_type = BookmarkViewType.TEXT.value

        self.external_components["button"][1] = [
            self.make_empty_button(), True
        ]
        self.external_components["button"][3] = [
            self.make_empty_button(), True
        ]

        self.external_components["select"][0][1] = True
        return self.update_view_components()

    async def update_current_text_embed(self, interaction: discord.Interaction, view: Self | None = None):
        if self.view_type != BookmarkViewType.TEXT.value:
            return

        self.items = self.bookmarks_to_text_embeds()
        await interaction.response.edit_message(embed=self.items[self.page], view=self if view is None else view)

    async def update_current_visual_embed(self, interaction: discord.Interaction, view: Self | None = None):
        if self.view_type != BookmarkViewType.VISUAL.value:
            return

        self._handle_page_change()
        scanlator = get_manga_scanlator_class(SCANLATORS, key=self.bookmarks[self.page].manga.scanlator)
        em = create_bookmark_embed(self.bot, self.bookmarks[self.page], scanlator.icon_url)
        await interaction.response.edit_message(embed=em, view=self if view is None else view)

    def bookmarks_to_text_embeds(self) -> list[discord.Embed]:
        _sorted = sort_bookmarks(self.bookmarks, self.sort_type)
        grouped = group_items_by(_sorted, ["manga.scanlator"])
        embeds: list[discord.Embed] = []

        em = discord.Embed(title="Bookmarks", color=discord.Color.blurple())

        for bookmark_group in grouped:
            scanlator_title_added = False
            for index in range(0, len(bookmark_group), 10):
                bookmark = bookmark_group[index]
                field_text = "\n".join(
                    f"**{i + (index * 10) + 1}.** [{bookmark.manga.human_name}]({bookmark.manga.manga_url})"
                    f" - {bookmark.last_read_chapter}"
                    for i, bookmark in enumerate(bookmark_group[index:index + 10])
                )
                if not scanlator_title_added:
                    field_name = bookmark.manga.scanlator.title()
                    scanlator_title_added = True
                else:
                    field_name = "\u200b"
                em.add_field(name=field_name, value=field_text, inline=False)

                if len(em.fields) == 25:
                    embeds.append(em)
                    em = discord.Embed(title="Bookmarks", color=discord.Color.blurple())
                    scanlator_title_added = False
        if em.fields:
            embeds.append(em)
        self.items = embeds
        return embeds

    def _get_display_embed(self) -> discord.Embed:
        if self.view_type == "text":
            return self.items[self.page]
        else:
            scanlator = get_manga_scanlator_class(SCANLATORS, key=self.bookmarks[self.page].manga.scanlator)
            return create_bookmark_embed(self.bot, self.bookmarks[self.page], scanlator.icon_url)

    def _handle_page_change(self):
        if self.view_type == "text":
            if self.page > len(self.items) - 1:
                self.page = 0
            elif self.page < 0:
                self.page = len(self.items) - 1
        else:
            if self.page > len(self.bookmarks) - 1:
                self.page = 0
            elif self.page < 0:
                self.page = len(self.bookmarks) - 1

    @discord.ui.button(label=f"⏮️", style=discord.ButtonStyle.blurple, row=0)
    async def _first_page(
            self, interaction: discord.Interaction, _
    ):
        self.page = 0
        await interaction.response.edit_message(embed=self._get_display_embed())

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple, row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._handle_page_change()
        await interaction.response.edit_message(embed=self._get_display_embed())

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red, row=0)
    async def _stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple, row=0)
    async def forward(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._handle_page_change()
        await interaction.response.edit_message(embed=self._get_display_embed())

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple, row=0)
    async def _last_page(
            self, interaction: discord.Interaction, _
    ):
        if self.view_type == "text":
            self.page = len(self.items) - 1
        else:
            self.page = len(self.bookmarks) - 1
        self._handle_page_change()
        await interaction.response.edit_message(embed=self._get_display_embed())
