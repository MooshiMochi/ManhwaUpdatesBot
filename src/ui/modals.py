from __future__ import annotations

from typing import TYPE_CHECKING

from ..static import Constants

if TYPE_CHECKING:
    from src.core.objects import Bookmark
    from . import BookmarkView

import traceback
import discord
from logging import Logger
# noinspection PyProtectedMember
from src.core.database import _levenshtein_distance
from src.enums import BookmarkViewType
import logging


class BaseModal(discord.ui.Modal):
    logger = logging.getLogger("modal")

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        # Make sure we know what the error actually is
        self.logger.error(traceback.print_exception(type(error), error, error.__traceback__))
        if interaction.response.is_done():  # noqa
            await interaction.followup.send(
                'Oops! Something went wrong.', ephemeral=True
            )
        else:
            await interaction.response.send_message('Oops! Something went wrong.', ephemeral=True)  # noqa


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
            (x for x in self.bookmarks if x.manga.title.lower().startswith(self.query.value.lower())), None
        )
        if not bookmark:
            bookmark = min(
                self.bookmarks,
                key=lambda x: _levenshtein_distance(x.manga.title.lower(), self.query.value.lower())
            )
        self.view.visual_item_index = self.bookmarks.index(bookmark)
        self.view.folder = bookmark.folder
        self.view.change_view_type(BookmarkViewType.VISUAL)
        self.view.clear_components()
        self.view.load_components()

        self.view.viewable_bookmarks = self.view.get_bookmarks_from_folder()
        self.view._handle_index_change()  # noqa

        await self.view.update(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        # Make sure we know what the error actually is
        self.logger.error(traceback.print_exception(type(error), error, error.__traceback__))
        user_message = "Oops! Something went wrong.\nPlease notify the developer about the time and date of this error."
        if interaction.response.is_done():  # noqa
            await interaction.followup.send(
                user_message, ephemeral=True
            )
        else:
            await interaction.response.send_message(user_message, ephemeral=True)  # noqa


class InputModal(BaseModal, title="Language to translate to"):
    input_value = discord.ui.TextInput(
        label='Language Name',
        placeholder='Enter the language name...',
    )

    def __init__(self):
        super().__init__()
        self.language: dict[str, str] = {}

    async def on_submit(self, interaction: discord.Interaction, /) -> None:
        val = self.input_value.value.lower()

        # begin searching for the value
        for lang in Constants.google_translate_langs:
            if val in lang["language"].lower():
                self.language = lang
                break
        else:  # no break
            # try to search with levenshtein distance
            self.language = min(
                Constants.google_translate_langs,
                key=lambda x: _levenshtein_distance(x["language"].lower(), val)
            )
        if self.language is not None:
            await interaction.response.send_message(  # noqa
                f"Language set to {self.language['language']}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(  # noqa
                "Language not found.", ephemeral=True
            )
