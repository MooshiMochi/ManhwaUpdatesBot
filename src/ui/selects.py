from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core import MangaClient

import discord

from src.core.objects import Chapter, Bookmark
from discord.ui import Select
from src.enums import BookmarkFolderType, BookmarkSortType, BookmarkViewType
from src.core.errors import ChapterNotFoundError


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
            await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
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
            await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
            return

        else:
            self.view._bookmarks_to_text_embeds()  # noqa
            await self.view.update(interaction)


class ChapterSelect(Select):
    def __init__(self, bookmark: Bookmark, row: int = 3):

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
            raise ChapterNotFoundError()

        self.bookmark.last_read_chapter = new_last_read_chapter

        await self.bookmark.update_last_read_chapter(self.view.bot, new_last_read_chapter)

        # If last_read_chapter == last_chapter and manga not completed, subscribe user
        bot: MangaClient = self.view.bot
        user_subscribed: bool = False
        should_track: bool = False
        if self.bookmark.last_read_chapter == self.bookmark.manga.available_chapters[
            -1
        ] and not self.bookmark.manga.completed:
            # check if the user is subscribed to the manga with manga.id
            # if not, subscribe user
            user_subscribed = True
            is_tracked: bool = await bot.db.is_manga_tracked(
                self.bookmark.manga.id, self.bookmark.manga.scanlator, interaction.guild_id
            )
            if not await bot.db.is_user_subscribed(
                    interaction.user.id, self.bookmark.manga.id, self.bookmark.manga.scanlator) and is_tracked:
                await bot.db.subscribe_user(
                    interaction.user.id, self.bookmark.guild_id, self.bookmark.manga.id, self.bookmark.manga.scanlator
                )
            elif not is_tracked:
                should_track = True
        # -----

        self.view.clear_components()
        self.view.load_components()
        self.view.toggle_nav_buttons(True)

        await self.view.update(interaction)

        success_em = discord.Embed(
            title="Bookmark Updated",
            description=f"Successfully updated bookmark to {self.bookmark.last_read_chapter}",
            color=discord.Color.green(),
        )
        if should_track:
            success_em.description += "\n\n*You should consider tracking and subscribing to this manga to get updates.*"
            if interaction.response.is_done():  # noqa
                await interaction.followup.send(embed=success_em, ephemeral=True)
            else:
                await interaction.response.send_message(embed=success_em, ephemeral=True)  # noqa

        elif user_subscribed:
            success_em.description += f" and subscribed you to updates for {self.bookmark.manga.title}"
            if interaction.response.is_done():  # noqa
                await interaction.followup.send(embed=success_em, ephemeral=True)
            else:
                await interaction.response.send_message(embed=success_em, ephemeral=True)  # noqa


class BookmarkFolderSelect(Select):
    def __init__(
            self,
            row: int = 3,
            folders: list[BookmarkFolderType] | set[BookmarkFolderType] = None,
            current_folder: BookmarkFolderType = BookmarkFolderType.Reading
    ):
        if not folders:
            folders = [x for x in BookmarkFolderType]
        if BookmarkFolderType.All not in folders:
            folders = folders | {BookmarkFolderType.All}

        options = [
            discord.SelectOption(
                label=f"Folder: {folder.value.title()}",
                value=folder.value,
                default=True if current_folder == folder else False
            )
            for folder in folders
        ]

        super().__init__(
            placeholder=f"Current folder: {current_folder.value.title()}",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="bookmark_folder_select",
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        new_folder = BookmarkFolderType(self.values[0])
        changed: bool = self.view.folder != new_folder

        if not changed:
            await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
            return
        else:
            self.view.folder = new_folder
            self.view.viewable_bookmarks = self.view.get_bookmarks_from_folder()
            self.view.visual_item_index = 0  # reset it to 0
            if self.view.view_type == BookmarkViewType.TEXT:
                self.view._bookmarks_to_text_embeds()  # noqa
            await self.view.update(interaction)


class MoveToFolderSelect(Select):
    def __init__(self, bookmark: Bookmark, row: int = 4):

        self.bookmark: Bookmark = bookmark
        options: list[discord.SelectOption] = [
            discord.SelectOption(
                label=folder.value.title(),
                value=folder.value
            ) for folder in BookmarkFolderType if folder != self.bookmark.folder and folder != BookmarkFolderType.All
        ]

        super().__init__(
            placeholder=f"Move to a folder ...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="bookmark_move_folder_select",
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        new_folder = self.values[0]
        if new_folder == self.bookmark.folder.value:  # This is not possible, but doesn't hurt to handle it in case
            return await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
        else:
            self.bookmark.folder = BookmarkFolderType(new_folder)
        await self.view.bot.db.update_bookmark_folder(self.bookmark)

        # check if there are any bookmarks left in the current folder.
        folder_bookmarks_remaining = [x for x in self.view.bookmarks if x.folder == self.view.folder]
        if not folder_bookmarks_remaining:
            # Try to default to the reading folder if the current one is not the reading folder.
            if self.view.folder != BookmarkFolderType.Reading:
                self.view.folder = BookmarkFolderType.Reading
            else:
                self.view.folder = BookmarkFolderType.All

        self.view.viewable_bookmarks = self.view.get_bookmarks_from_folder()
        self.view._handle_index_change()  # noqa
        self.view.toggle_nav_buttons(True)
        await self.view.update(interaction)

        success_em = discord.Embed(
            title="Bookmark Updated",
            description=f"Bookmark has been moved to the {self.bookmark.folder.value.title()} folder.",
            color=discord.Color.green(),
        )
        if interaction.response.is_done():  # noqa
            await interaction.followup.send(embed=success_em, ephemeral=True)
        else:
            await interaction.response.send_message(embed=success_em, ephemeral=True)  # noqa
