from __future__ import annotations

import inspect
import logging
import traceback as tb
from functools import partial, wraps
from typing import Callable

import discord
from discord import app_commands

from src.core.objects import Manga
from src.core.scanners import SCANLATORS
from src.static import Constants

logger = logging.getLogger("autocompletes")


def try_except(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            if inspect.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)
        except Exception as e:
            traceback = "".join(
                tb.format_exception(type(e), e, e.__traceback__)
            )
            logger.error(f"Error in {func.__name__}: {traceback}")
            raise e

    return wrapper


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


@try_except
async def scanlator(_, current: str) -> list[discord.app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=_scanlator.name.title(), value=_scanlator.name) for _scanlator in SCANLATORS.values()
        if _scanlator.name.lower().startswith(current.lower()) and hasattr(_scanlator, "search")
    ]


@try_except
async def manga(
        interaction: discord.Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for the /latest command"""
    # noinspection PyProtectedMember
    mangas: list[Manga] = await interaction.client.db.get_all_series(current, autocomplete=True)
    if not mangas:
        return []

    name_val_pairs = [
        (f"({m.scanlator}) " + m.human_name, m.id) for m in mangas
    ]
    return [
               discord.app_commands.Choice(name=x[0][:97] + ("..." if len(x[0]) > 100 else ''), value=x[1])
               for x in name_val_pairs
           ][:25]


@try_except
async def user_bookmarks(
        interaction: discord.Interaction, argument: str
) -> list[discord.app_commands.Choice]:
    bookmarks: list[tuple[str, str]] = await interaction.client.db.get_user_bookmarks_autocomplete(
        interaction.user.id, argument
    )
    if not bookmarks:
        return []
    return [
               discord.app_commands.Choice(
                   name=(x[1][:97] + "...") if len(x[1]) > 100 else x[1],
                   value=x[0]
               ) for x in bookmarks
           ][:25]


@try_except
async def user_subbed_manga(
        interaction: discord.Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for the /unsubscribe command."""
    subs: list[Manga] = await interaction.client.db.get_user_guild_subs(
        interaction.guild_id, interaction.user.id, current
    )
    if not subs: return []  # noqa

    name_val_pairs = [
        (f"({m.scanlator}) " + m.human_name, m.id) for m in subs
    ]
    return [
               discord.app_commands.Choice(name=(x[0][:97] + "...") if len(x[0]) > 100 else x[0], value=x[1])
               for x in name_val_pairs
           ][:25]


@try_except
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
                   name=(chp.name[:97] + "...") if len(chp.name) > 100 else chp.name,
                   value=str(chp.index)
               ) for chp in _chapters
           ][:25]


@try_except
async def google_language(
        _: discord.Interaction, argument: str
) -> list[discord.app_commands.Choice]:
    if not Constants.google_translate_langs:
        return []
    return [
               app_commands.Choice(name=lang["language"], value=lang["code"]) for lang in
               Constants.google_translate_langs if
               argument.lower() in lang["language"].lower()
           ][:25]


@try_except
async def tracked_manga(interaction: discord.Interaction, argument: str) -> list[discord.app_commands.Choice]:
    guild_tracked_manga = await interaction.client.db.get_all_guild_tracked_manga(interaction.guild_id,
                                                                                  current=argument)
    if not guild_tracked_manga:
        return []

    name_val_pairs = [
        (f"({m.scanlator}) " + m.human_name, m.id) for m in guild_tracked_manga
    ]
    return [
               discord.app_commands.Choice(name=(x[0][:97] + "...") if len(x[0]) > 100 else x[0], value=x[1])
               for x in name_val_pairs
           ][:25]
