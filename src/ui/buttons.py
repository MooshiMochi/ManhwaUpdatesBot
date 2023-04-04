from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.core import MangaClient
    from src.core.objects import Bookmark
    from . import BookmarkView

from src.core.scanners import SCANLATORS
from src.utils import create_bookmark_embed, get_manga_scanlator_class

import discord

from .modals import SearchModal
from .selects import ChapterSelect


class CustomButtonCallbacks:
    def __init__(self, bot: MangaClient, view: BookmarkView, bookmarks: list[Bookmark]):
        self.bot: MangaClient = bot
        self.bookmarks: list[bookmarks] = bookmarks
        self.view: BookmarkView = view

    async def search_button_callback(self, interaction: discord.Interaction):
        modal: SearchModal = SearchModal(
            self.bot.logger,
            self.view,
            self.bookmarks,
        )
        await interaction.response.send_modal(modal)
        # await modal.wait()

    async def delete_button_callback(self, interaction: discord.Interaction):
        bookmark: Bookmark = self.view.bookmarks[self.view.page]
        await bookmark.delete(self.view.bot)
        self.view.bookmarks = [x for x in self.view.bookmarks if x.manga.id != bookmark.manga.id]
        self.view.page -= 1
        # noinspection PyProtectedMember
        self.view._handle_page_change()
        scanlator = get_manga_scanlator_class(SCANLATORS, key=bookmark.manga.scanlator)
        embed = create_bookmark_embed(
            self.bot, self.view.bookmarks[self.view.page], scanlator.icon_url
        )
        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.followup.send(
            f"Bookmark [{bookmark.manga.human_name}]({bookmark.manga.manga_url}) deleted successfully.",
            ephemeral=True
        )

    async def update_button_callback(self, interaction: discord.Interaction):
        curr_bookmark: Bookmark = self.view.bookmarks[self.view.page]
        for child in self.view.children:
            if child.row is not None and child.row == 4:
                self.view.remove_item(child)

        self.view.add_item(
            ChapterSelect(curr_bookmark)
        )
        return await interaction.response.edit_message(view=self.view)
