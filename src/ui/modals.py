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
from src.enums import BookmarkViewType


class SearchModal(discord.ui.Modal, title='Search Bookmark'):
    query = discord.ui.TextInput(
        label='Query',
        placeholder='Enter the manga name here...',
    )

    def __init__(self, logger: Logger, view: BookmarkView):
        super().__init__()
        self.logger: Logger = logger
        self.view = view
        self.bookmarks: list[Bookmark] = self.view.bookmarks

    async def on_submit(self, interaction: discord.Interaction):
        bookmark = next(
            (x for x in self.bookmarks if x.manga.human_name.lower().startswith(self.query.value.lower())), None
        )
        if not bookmark:
            bookmark = min(
                self.bookmarks,
                key=lambda x: _levenshtein_distance(x.manga.human_name.lower(), self.query.value.lower())
            )
        self.view.visual_item_index = self.bookmarks.index(bookmark)
        self.view.change_view_type(BookmarkViewType.VISUAL)
        self.view.load_components()
        await self.view.update(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        # Make sure we know what the error actually is
        self.logger.error(traceback.print_exception(type(error), error, error.__traceback__))
        if interaction.response.is_done():
            await interaction.followup.send(
                'Oops! Something went wrong.', ephemeral=True
            )
        else:
            await interaction.response.send_message('Oops! Something went wrong.', ephemeral=True)
