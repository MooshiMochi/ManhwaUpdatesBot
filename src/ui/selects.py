from __future__ import annotations
from typing import TYPE_CHECKING, Literal
if TYPE_CHECKING:
    from . import BookmarkView

import discord

from src.utils import sort_bookmarks
from src.core.objects import Chapter, Bookmark
from discord.ui import Select
from src.enums import BookmarkSortType, BookmarkViewType


class SortTypeSelect(Select):
    def __init__(self, sort_type: Literal["a-z", "last_updated"] = BookmarkSortType.ALPHABETICAL.value, row: int = 1):
        options = [
            discord.SelectOption(label="A-Z", value=BookmarkSortType.ALPHABETICAL.value),
            discord.SelectOption(label="Last Updated", value=BookmarkSortType.LAST_UPDATED_TIMESTAMP.value),
        ]
        self.sort_type = sort_type

        placeholder = self.update_placeholder(options, sort_type)
        custom_id = "sort_type_select"
        super().__init__(
            placeholder=placeholder, min_values=1, max_values=1, options=options, custom_id=custom_id, row=row
        )

    @staticmethod
    def update_placeholder(options: list[discord.SelectOption], selected_value: str):
        text_sort_type = next((x.label for x in options if x.value == selected_value), "Error")
        placeholder = f"Sort By: {text_sort_type}"
        return placeholder

    async def callback(self, interaction: discord.Interaction):
        self.view.sort_type = self.values[0]
        self.view.bookmarks = sort_bookmarks(self.view.bookmarks, self.view.sort_type)

        self.view.items = self.view.bookmarks_to_text_embeds()

        self.placeholder = self.update_placeholder(self.options, self.values[0])

        await interaction.response.edit_message(embed=self.view.items[self.view.page], view=self.view)


class ViewTypeSelect(Select):
    def __init__(
            self,
            create_bookmark_embed_func: callable,
            get_scanlator_func: callable,
            row: int = 2
    ):
        options = [
            discord.SelectOption(label="Visual", value=BookmarkViewType.VISUAL.value),
            discord.SelectOption(label="Text", value=BookmarkViewType.TEXT.value),
        ]

        self.create_bookmark_embed_func = create_bookmark_embed_func
        self.get_scanlator_func = get_scanlator_func

        placeholder = self.update_placeholder(options, self.view.view_type)
        custom_id = "view_type_select"
        super().__init__(
            placeholder=placeholder, min_values=1, max_values=1, options=options, custom_id=custom_id, row=row
        )

    @staticmethod
    def update_placeholder(options: list[discord.SelectOption], selected_value: str):
        text_view_type = next((x.label for x in options if x.value == selected_value), "Error")
        placeholder = f"View Type: {text_view_type}"
        return placeholder

    async def callback(self, interaction: discord.Interaction):
        if self.view.view_type == self.values[0]:
            await interaction.response.defer(ephemeral=True, thinking=False)
            return

        self.view.view_type = self.values[0]
        self.placeholder = self.update_placeholder(self.options, self.values[0])
        self.view.page = 0

        if self.view.view_type == "text":  # visual to text
            self.view.items = self.view.bookmarks_to_text_embeds()
            new_view = self.view.to_text_view()
            await interaction.response.edit_message(embed=self.view.items[self.view.page], view=new_view)
        else:  # text to visual
            bookmark = self.view.bookmarks[self.view.page]
            scanner = self.get_scanlator_func(key=bookmark.manga.scanlator)
            em = self.create_bookmark_embed_func(bookmark=bookmark, scanlator_icon_url=scanner.icon_url)
            new_view = self.view.to_visual_view()
            await interaction.response.edit_message(embed=em, view=new_view)


class ChapterSelect(Select):
    def __init__(self, bookmark: Bookmark, row: int = 4):

        chapter_options = self.create_chapter_options(bookmark.last_read_chapter, bookmark.available_chapters)
        print(len(chapter_options))
        options = [
            discord.SelectOption(label=chapter.chapter_string, value=str(chapter.index))
            for chapter in chapter_options
        ]

        custom_id = "chapter_select"

        self.bookmark: Bookmark = bookmark

        super().__init__(
            placeholder=self.update_placeholder(),
            min_values=1,
            max_values=1,
            options=options,
            custom_id=custom_id,
            row=row
        )

    @staticmethod
    def create_chapter_options(selected_chapter: Chapter, chapters: list[Chapter]) -> list[Chapter]:
        selected_index = selected_chapter.index
        chapter_count = len(chapters)

        start_index = max(selected_index - 12, 0)
        end_index = min(selected_index + 12, chapter_count - 1)

        if start_index == 0:
            end_index = min(24, chapter_count - 1)
        elif end_index == chapter_count - 1:
            start_index = max(chapter_count - 25, 0)

        return chapters[start_index:end_index + 1]

    def update_placeholder(self):
        placeholder = f"Last read chapter: {self.bookmark.last_read_chapter.chapter_string}"[:100]
        if len(placeholder) == 100:
            placeholder = placeholder[:-3] + "..."
        return placeholder

    async def callback(self, interaction: discord.Interaction):
        chapter_index: int = int(self.values[0])
        new_last_read_chapter = self.bookmark.available_chapters[chapter_index]
        self.bookmark.last_read_chapter = new_last_read_chapter
        self.placeholder = self.update_placeholder()
        await self.bookmark.update_last_read_chapter(self.view.bot, new_last_read_chapter)

        for child in self.view.children:
            if child.row is not None and child.row == self.row:
                self.view.remove_item(child)
        await self.view.update_current_visual_embed(interaction)
        # await interaction.response.edit_message(view=self.view)