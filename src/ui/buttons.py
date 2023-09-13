from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core import MangaClient
    from src.core.objects import Bookmark
    from . import BookmarkView
    from .views import ConfirmView

import discord

from .modals import SearchModal
from .selects import ChapterSelect
from src.overwrites import Embed


class CustomButtonCallbacks:
    def __init__(self, bot: MangaClient, view: BookmarkView):
        self.bot: MangaClient = bot
        self.view: BookmarkView = view

    async def search_button_callback(self, interaction: discord.Interaction):
        modal: SearchModal = SearchModal(
            self.bot.logger,
            self.view,
        )
        await interaction.response.send_modal(modal)  # noqa

    async def delete_button_callback(self, interaction: discord.Interaction, confirm_view_cls: type[ConfirmView]):
        _conf_view = confirm_view_cls(self.bot, interaction)
        await self.view.update(interaction)
        # await interaction.response.defer(ephemeral=True, thinking=False)  # noqa
        msg = await interaction.followup.send(  # noqa
            embed=Embed(
                bot=interaction.client,
                title="Are you sure?",
                description="Are you sure you want to delete this bookmark?",
                color=discord.Color.red()
            ),
            view=_conf_view,
            ephemeral=True,
            wait=True
        )
        await _conf_view.wait()
        if _conf_view.value is None:
            _conf_view.stop()
            return await msg.edit(
                embed=Embed(
                    bot=interaction.client,
                    title="Bookmark Deletion Cancelled",
                    description="Bookmark deletion cancelled.",
                    color=discord.Color.red()
                ), view=None
            )
        elif _conf_view.value is False:
            _conf_view.stop()
            return await msg.edit(
                embed=Embed(
                    bot=interaction.client,
                    title="Bookmark Deletion Cancelled",
                    description="Bookmark deletion cancelled.",
                    color=discord.Color.red()
                ), view=None
            )

        bookmark: Bookmark = self.view.bookmarks[self.view.visual_item_index]
        # noinspection PyProtectedMember
        bookmark_embed = self.view._get_display_embed()
        await bookmark.delete(self.view.bot)
        self.view.bookmarks = [x for x in self.view.bookmarks if x.manga.id != bookmark.manga.id]
        await self.view.update(interaction)

        await msg.edit(
            content=f"Bookmark [{bookmark.manga.human_name}]({bookmark.manga.url}) deleted successfully.",
            embed=bookmark_embed,
            view=None
        )

    async def update_button_callback(self, interaction: discord.Interaction):
        curr_bookmark: Bookmark = self.view.bookmarks[self.view.visual_item_index]

        self.view.clear_components()

        self.view.toggle_nav_buttons(False)

        self.view.add_item(
            ChapterSelect(curr_bookmark)
        )
        return await interaction.response.edit_message(view=self.view)  # noqa
