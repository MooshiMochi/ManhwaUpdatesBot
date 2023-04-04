from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.core import MangaClient
    from src.core.objects import Bookmark
    from . import BookmarkView


import discord

from .modals import SearchModal
from .selects import ChapterSelect


class CustomButtonCallbacks:
    def __init__(self, bot: MangaClient, view: BookmarkView):
        self.bot: MangaClient = bot
        self.view: BookmarkView = view

    async def search_button_callback(self, interaction: discord.Interaction):
        modal: SearchModal = SearchModal(
            self.bot.logger,
            self.view,
        )
        await interaction.response.send_modal(modal)

    async def delete_button_callback(self, interaction: discord.Interaction):
        bookmark: Bookmark = self.view.bookmarks[self.view.visual_item_index]
        # noinspection PyProtectedMember
        bookmark_embed = self.view._get_display_embed()
        await bookmark.delete(self.view.bot)
        self.view.bookmarks = [x for x in self.view.bookmarks if x.manga.id != bookmark.manga.id]
        # noinspection PyProtectedMember
        self.view._increment_index(-1)

        await self.view.update(interaction)

        await interaction.followup.send(
            f"Bookmark [{bookmark.manga.human_name}]({bookmark.manga.url}) deleted successfully.",
            embed=bookmark_embed,
            ephemeral=True
        )

    async def update_button_callback(self, interaction: discord.Interaction):
        curr_bookmark: Bookmark = self.view.bookmarks[self.view.visual_item_index]

        self.view.clear_components()

        self.view.toggle_nav_buttons(False)

        self.view.add_item(
            ChapterSelect(curr_bookmark)
        )
        return await interaction.response.edit_message(view=self.view)
