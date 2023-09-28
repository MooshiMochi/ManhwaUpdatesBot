from __future__ import annotations

import inspect
import logging
import traceback as tb
from functools import partial, wraps
from typing import Callable

import discord
from discord import app_commands

from src.core.objects import Manga
from src.core.scanlators import scanlators
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
        app_commands.Choice(name=_scanlator.name.title(), value=_scanlator.name) for _scanlator in scanlators.values()
        if _scanlator.name.lower().startswith(current.lower()) and hasattr(_scanlator, "search")
    ]


def get_scanlator_from_current_str(current: str) -> tuple[str | None, str | None]:
    """
    Gets the scanlator name and removes it from the current string.
    Args:
        current: str - The current user input string for the autocomplete

    Returns:
        tuple[str | None, str | None] - (scanlator_name, parsed_current_str)
    """
    original_current: str = current
    scanlator_str = None
    if current and current.startswith("("):
        scanlator_str = (current.split(" ") or [""])[0]

        curr_idx = current.index(scanlator_str)
        current = current[curr_idx + len(scanlator_str):]

        scanlator_str = scanlator_str.strip("( )").lower()
        if scanlator_str == "": scanlator_str = None  # noqa: Allow this inline operation
    scanlator_names = sorted([x for x in scanlators.keys()], key=len)
    if scanlator_str is not None:
        for scan_name in scanlator_names:
            if scan_name.startswith(scanlator_str):
                scanlator_str = scan_name
                break
        else:
            scanlator_str = None
            current = original_current
    else:
        current = original_current
    return scanlator_str, current


@try_except
async def manga(
        interaction: discord.Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for the /latest command"""
    # noinspection PyProtectedMember
    scanlator_name, current = get_scanlator_from_current_str(current)
    mangas: list[Manga] = await interaction.client.db.get_all_series(
        current, autocomplete=True, scanlator=scanlator_name
    )
    if not mangas:
        return []

    name_val_pairs = [
        (f"({m.scanlator}) " + m.title, f"{m.id}|{m.scanlator}") for m in mangas
    ]
    return [
               discord.app_commands.Choice(name=x[0][:97] + ("..." if len(x[0]) > 100 else ''), value=x[1])
               for x in name_val_pairs
           ][:25]


@try_except
async def user_bookmarks(
        interaction: discord.Interaction, argument: str
) -> list[discord.app_commands.Choice]:
    scanlator_name, argument = get_scanlator_from_current_str(argument)
    bookmarks: list[tuple[str, str, str]] = await interaction.client.db.get_user_bookmarks_autocomplete(
        interaction.user.id, argument, autocomplete=True, scanlator=scanlator_name
    )
    if not bookmarks:
        return []
    name_val_pairs = [
        (f"({b[2]}) " + b[1], f"{b[0]}|{b[2]}") for b in bookmarks
    ]
    return [
               discord.app_commands.Choice(name=x[0][:97] + ("..." if len(x[0]) > 100 else ''), value=x[1])
               for x in name_val_pairs
           ][:25]


@try_except
async def user_subbed_manga(
        interaction: discord.Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for the /unsubscribe command."""

    scanlator_name, current = get_scanlator_from_current_str(current)

    subs: list[Manga] = await interaction.client.db.get_user_guild_subs(
        interaction.guild_id, interaction.user.id, current, autocomplete=True, scanlator=scanlator_name
    )
    if not subs: return []  # noqa

    name_val_pairs = [
        (f"({m.scanlator}) " + m.title, f"{m.id}|{m.scanlator}") for m in subs
    ]
    return [
               discord.app_commands.Choice(name=(x[0][:97] + "...") if len(x[0]) > 100 else x[0], value=x[1])
               for x in name_val_pairs
           ][:25]


@try_except
async def chapters(
        interaction: discord.Interaction, argument: str
) -> list[discord.app_commands.Choice]:
    series_id: str = interaction.namespace["manga"]
    if series_id is None:
        return []
    try:
        series_id, scanlator_name = series_id.split("|")
    except ValueError:  # some weirdo is not using the autocomplete for the manga parameter. 💀
        return []
    _chapters = await interaction.client.db.get_series_chapters(series_id, scanlator_name, argument)
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
    scanlator_name, argument = get_scanlator_from_current_str(argument)
    guild_tracked_manga = await interaction.client.db.get_all_guild_tracked_manga(
        interaction.guild_id,
        current=argument,
        autocomplete=True,
        scanlator=scanlator_name
    )
    if not guild_tracked_manga:
        return []

    name_val_pairs = [
        (f"({m.scanlator}) " + m.title, f"{m.id}|{m.scanlator}") for m in guild_tracked_manga
    ]
    return [
               discord.app_commands.Choice(name=(x[0][:97] + "...") if len(x[0]) > 100 else x[0], value=x[1])
               for x in name_val_pairs
           ][:25]
