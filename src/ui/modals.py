from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.core.objects import Bookmark
    from . import BookmarkView

import traceback
import discord
from logging import Logger
# noinspection PyProtectedMember
from src.core.database import _levenshtein_distance


class SearchModal(discord.ui.Modal, title='Search Bookmark'):
    query = discord.ui.TextInput(
        label='Query',
        placeholder='Enter the query here...',
    )

    def __init__(self, logger: Logger, view: BookmarkView, bookmarks: list[Bookmark]):
        super().__init__()
        self.logger: Logger = logger
        self.view = view
        self.bookmarks: list[Bookmark] = bookmarks

    async def on_submit(self, interaction: discord.Interaction):
        print("Works!")
        bookmark = next(
            (x for x in self.bookmarks if x.manga.human_name.lower().startswith(self.query.value.lower())), None
        )
        if not bookmark:
            bookmark = min(
                self.bookmarks,
                key=lambda x: _levenshtein_distance(x.manga.human_name.lower(), self.query.value.lower())
            )
        self.view.page = self.bookmarks.index(bookmark)
        new_view = self.view.to_visual_view()
        await self.view.update_current_visual_embed(interaction, new_view)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        # Make sure we know what the error actually is
        self.logger.error(traceback.print_exception(type(error), error, error.__traceback__))
        await interaction.response.send_message('Oops! Something went wrong.', ephemeral=True)
