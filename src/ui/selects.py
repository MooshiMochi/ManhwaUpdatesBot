from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core import MangaClient

import discord

from src.core.objects import Chapter, Bookmark
from discord.ui import Select
from src.enums import BookmarkSortType, BookmarkViewType
from src.core.errors import ChapterNotFound


class SortTypeSelect(Select):
    def __init__(self, current_sort_type: BookmarkSortType, row: int = 1):
        options = [
            discord.SelectOption(
                label=BookmarkSortType.ALPHABETICAL.name.title(),
                value=BookmarkSortType.ALPHABETICAL.value
            ),
            discord.SelectOption(
                label=BookmarkSortType.LAST_UPDATED_TIMESTAMP.name.title().replace('_', ' '),
                value=BookmarkSortType.LAST_UPDATED_TIMESTAMP.value
            ),
        ]

        super().__init__(
            placeholder=f"Sort by: {current_sort_type.name.replace('_', ' ').title()}",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="sort_type_select",
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        new_sort_type = BookmarkSortType(self.values[0])
        changed: bool = self.view.change_sort_type(new_sort_type)
        if not changed:
            await interaction.response.defer(ephemeral=True, thinking=False)
            return

        else:
            await self.view.update(interaction)


class ViewTypeSelect(Select):
    def __init__(
            self,
            current_view_type: BookmarkViewType,
            row: int = 2
    ):
        options = [
            discord.SelectOption(
                label=BookmarkViewType.VISUAL.name.title(),
                value=BookmarkViewType.VISUAL.value),
            discord.SelectOption(
                label=BookmarkViewType.TEXT.name.title(),
                value=BookmarkViewType.TEXT.value),
        ]

        super().__init__(
            placeholder=f"View Type: {current_view_type.name.title()}",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="view_type_select",
            row=row
        )

    async def callback(self, interaction: discord.Interaction):

        new_view_type = BookmarkViewType(self.values[0])
        changed: bool = self.view.change_view_type(new_view_type)
        if not changed:
            await interaction.response.defer(ephemeral=True, thinking=False)
            return

        else:
            await self.view.update(interaction)


class ChapterSelect(Select):
    def __init__(self, bookmark: Bookmark, row: int = 4):

        chapter_options = self.create_chapter_options(bookmark.last_read_chapter, bookmark.manga.available_chapters)
        options = [
            discord.SelectOption(label=chapter.name, value=str(chapter.index))
            for chapter in chapter_options
        ]

        self.bookmark: Bookmark = bookmark

        super().__init__(
            placeholder=self.create_placeholder(),
            min_values=1,
            max_values=1,
            options=options,
            custom_id="chapter_select",
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

        return [chapters[0], *chapters[start_index + 1:end_index], chapters[-1]]

    def create_placeholder(self):
        placeholder = f"Last read chapter: {self.bookmark.last_read_chapter.name}"[:100]
        if len(placeholder) == 100:
            placeholder = placeholder[:-3] + "..."
        return placeholder

    async def callback(self, interaction: discord.Interaction):
        try:
            chapter_index: int = int(self.values[0])
            new_last_read_chapter = self.bookmark.manga.available_chapters[chapter_index]
        except (IndexError, TypeError):
            raise ChapterNotFound()

        self.bookmark.last_read_chapter = new_last_read_chapter

        await self.bookmark.update_last_read_chapter(self.view.bot, new_last_read_chapter)

        # If last_read_chapter == last_chapter and manga not completed, subscribe user
        bot: MangaClient = self.view.bot
        user_subscribed: bool = False
        if self.bookmark.last_read_chapter == self.bookmark.manga.available_chapters[
            -1
        ] and not self.bookmark.manga.completed:
            # check if user is subscribed to the manga with manga.id
            # if not, subscribe user
            user_subscribed = True
            if not await bot.db.is_user_subscribed(interaction.user.id, self.bookmark.manga.id):
                await bot.db.subscribe_user(
                    interaction.user.id, self.bookmark.guild_id, self.bookmark.manga.id
                )
        # -----

        self.view.clear_components()
        self.view.load_components()
        self.view.toggle_nav_buttons(True)

        await self.view.update(interaction)

        if user_subscribed:
            if interaction.response.is_done():
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="Bookmark Updated",
                        description=f"Successfully updated bookmark to {self.bookmark.last_read_chapter} and "
                                    f"subscribed you to updates for {self.bookmark.manga.human_name}",
                        color=discord.Color.green(),
                    ),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Bookmark Updated",
                        description=f"Successfully updated bookmark to {self.bookmark.last_read_chapter} and "
                                    f"subscribed you to updates for {self.bookmark.manga.human_name}",
                        color=discord.Color.green(),
                    ),
                    ephemeral=True
                )
