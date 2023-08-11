from __future__ import annotations

import inspect
from functools import partial
from typing import Callable

import discord
from discord import app_commands

from src.core.objects import Manga
from src.core.scanners import SCANLATORS
from src.static import Constants


def bind_autocomplete(callback: Callable, bind_to_object: object) -> Callable:
    """Bind a function to an object.

    Args:
        callback (Callable): The function to bind.
        bind_to_object (object): The object to bind the function to.

    Returns:
        Callable: The bound function.
    """

    if inspect.isfunction(callback):
        params = inspect.signature(callback).parameters
        if params and list(params)[0] == "self":
            return partial(callback, self=bind_to_object)
        else:
            return callback
    else:
        raise TypeError("Callback must be a callable.")


async def scanlator(_, current: str) -> list[discord.app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=_scanlator.name.title(), value=_scanlator.name) for _scanlator in SCANLATORS.values()
        if _scanlator.name.lower().startswith(current.lower()) and hasattr(_scanlator, "search")
    ]


async def manga(
        interaction: discord.Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for the /latest command"""
    # noinspection PyProtectedMember
    subs: list[Manga] = await interaction.client.db.get_all_series(current, autocomplete=True)
    return [
               discord.app_commands.Choice(
                   name=(
                       x.human_name[:97] + "..."
                       if len(x.human_name) > 100
                       else x.human_name
                   ),
                   value=x.id,
               )
               for x in subs
           ][:25]


async def user_bookmarks(
        interaction: discord.Interaction, argument: str
) -> list[discord.app_commands.Choice]:
    bookmarks = await interaction.client.db.get_user_bookmarks_autocomplete(interaction.user.id, argument)
    if not bookmarks:
        return []
    return [
               discord.app_commands.Choice(
                   name=x[1][:97] + "..." if len(x[1]) > 100 else x[1],
                   value=x[0]
               ) for x in bookmarks
           ][:25]


async def user_subbed_manga(
        interaction: discord.Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for the /unsubscribe command."""
    subs: list[Manga] = await interaction.client.db.get_user_subs(
        interaction.user.id, current
    )

    return [
               discord.app_commands.Choice(
                   name=(
                       x.human_name[:97] + "..."
                       if len(x.human_name) > 100
                       else x.human_name
                   ),
                   value=x.id,
               )
               for x in subs
           ][:25]


async def chapters(
        interaction: discord.Interaction, argument: str
) -> list[discord.app_commands.Choice]:
    series_id = interaction.namespace["manga"]
    if series_id is None:
        return []
    _chapters = await interaction.client.db.get_series_chapters(series_id, argument)
    if not _chapters:
        return []

    return [
               discord.app_commands.Choice(
                   name=chp.name[:97] + ("..." if len(chp.name) > 100 else ''),
                   value=str(chp.index)
               ) for chp in _chapters
           ][:25]


async def google_language(
        _: discord.Interaction, argument: str
) -> list[discord.app_commands.Choice]:
    return [
               app_commands.Choice(name=lang["language"], value=lang["code"]) for lang in
               Constants.google_translate_langs if
               argument.lower() in lang["language"].lower()
           ][:25]
