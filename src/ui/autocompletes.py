from __future__ import annotations

import inspect
import logging
import traceback as tb
from functools import partial, wraps
from types import SimpleNamespace
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core import MangaClient

import discord
from discord import app_commands

from src.core.scanlators import scanlators
from src.static import Constants

logger = logging.getLogger("autocompletes")

completed_db_set = ", ".join(map(lambda x: f"'{x.lower()}'", Constants.completed_status_set))


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
               app_commands.Choice(name=_scanlator.name.title(), value=_scanlator.name) for _scanlator in
               scanlators.values()
               if current == "" or _scanlator.name.lower().startswith(current.lower()) and hasattr(_scanlator, "search")
           ][:25]


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
async def user_bookmarks(
        interaction: discord.Interaction, current: str
) -> list[discord.app_commands.Choice]:
    scanlator_name, current = get_scanlator_from_current_str(current)
    default_query = f"""
                    SELECT 
                        '('||scanlator||') '||title AS name,
                        id||'|'||scanlator AS value
                    FROM series
                    WHERE (id, scanlator) IN (
                        SELECT series_id, scanlator FROM bookmarks
                        WHERE user_id = $1
                    )
                    """
    default_params = (interaction.user.id,)
    if scanlator_name:
        default_query += f" AND scanlator = ${len(default_params) + 1}"
        default_params += (scanlator_name,)
    if current:
        default_query += f" ORDER BY levenshtein(title, ${len(default_params) + 1}) DESC"
        default_params += (current,)

    results = await interaction.client.db.execute(default_query, *default_params, levenshtein=True)
    if not results:
        return []
    choices = [SimpleNamespace(name=x[0] if len(x[0]) < 100 else x[0][:97] + "...", value=x[1]) for x in results][:25]
    return [discord.app_commands.Choice(name=x.name, value=x.value) for x in choices]


@try_except
async def chapters(
        interaction: discord.Interaction, current: str
) -> list[discord.app_commands.Choice]:
    series_id: str = interaction.namespace["manga"]
    if series_id is None:
        return []
    try:
        series_id, scanlator_name = series_id.split("|")
    except ValueError:  # some weirdo is not using the autocomplete for the manga parameter. 💀
        return []
    _chapters = await interaction.client.db.get_series_chapters(series_id, scanlator_name, current)
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
        _: discord.Interaction, current: str
) -> list[discord.app_commands.Choice]:
    if not Constants.google_translate_langs:
        return []
    return [
               app_commands.Choice(name=lang["language"], value=lang["code"]) for lang in
               Constants.google_translate_langs if
               current.lower() in lang["language"].lower()
           ][:25]


@try_except
async def tracked_manga(interaction: discord.Interaction, current: str) -> list[discord.app_commands.Choice]:
    scanlator_name, current = get_scanlator_from_current_str(current)

    default_query = f"""
                SELECT 
                    '('||scanlator||') '||title AS name,
                    id||'|'||scanlator AS value
                FROM series
                WHERE (id, scanlator) IN (
                    SELECT series_id, scanlator FROM tracked_guild_series
                    WHERE guild_id = $1
                )
                """
    default_params = (
        interaction.guild_id or interaction.user.id,
    )

    if scanlator_name:
        default_query += f" AND scanlator = ${len(default_params) + 1}"
        default_params += (scanlator_name,)
    if current:
        default_query += f" ORDER BY levenshtein(title, ${len(default_params) + 1}) DESC"
        default_params += (current,)

    results = await interaction.client.db.execute(default_query, *default_params, levenshtein=True)
    if not results:
        return []
    choices = [SimpleNamespace(name=x[0] if len(x[0]) < 100 else x[0][:97] + "...", value=x[1]) for x in results][:25]
    return [discord.app_commands.Choice(name=x.name, value=x.value) for x in choices]


@try_except
async def subscribe_new_cmd(
        interaction: discord.Interaction, current: str | None = None) -> list[discord.app_commands.Choice]:
    scanlator_name, current = get_scanlator_from_current_str(current)
    bot: MangaClient = interaction.client
    first_opt_names = ["(!) All tracked series in this server", "All tracked series in this server"]
    default_query = f"""
        SELECT  '('||scanlator||') '||title AS name, id||'|'||scanlator AS value FROM series
        WHERE (id, scanlator) IN (SELECT series_id, scanlator FROM tracked_guild_series WHERE guild_id = $1)
        AND (id, scanlator) NOT IN (SELECT series_id, scanlator FROM user_subs WHERE guild_id = $1 AND id = $2)
        """
    default_params = (
        interaction.guild_id or interaction.user.id,
        interaction.user.id
    )

    if scanlator_name:
        default_query += f" AND scanlator = ${len(default_params) + 1}"
        default_params += (scanlator_name,)
    if current:
        default_query += f" ORDER BY levenshtein(title, ${len(default_params) + 1}) DESC"
        default_params += (current,)

    results = await interaction.client.db.execute(default_query, *default_params, levenshtein=True)
    first_option = discord.app_commands.Choice(
        name=first_opt_names[0],
        value=f"{interaction.guild_id or interaction.user.id}-all"
    )
    if not results:
        if interaction.guild_id is None or (
                guild_config := await bot.db.get_guild_config(interaction.guild_id)) is None:
            return []
        if (guild_config.default_ping_role and guild_config.default_ping_role.is_assignable() and
                guild_config.default_ping_role not in interaction.user.roles):
            return [first_option]
        return []

    choices = [SimpleNamespace(name=x[0] if len(x[0]) < 100 else x[0][:97] + "...", value=x[1]) for x in results][:25]
    normal_options = [discord.app_commands.Choice(name=x.name, value=x.value) for x in choices]
    if not current or current == "":
        return [first_option] + normal_options[:24]
    else:
        for opt in first_opt_names:
            if opt.lower().startswith(current.lower()):
                return [first_option] + normal_options[:24]
        return normal_options


@try_except
async def subscribe_delete_command(
        interaction: discord.Interaction, current: str | None = None) -> list[discord.app_commands.Choice]:
    """Autocomplete for the subscribe_delete command"""
    scanlator_name, current = get_scanlator_from_current_str(current)
    bot: MangaClient = interaction.client
    first_opt_names = ["(!) All subbed series in this server", "All subbed series in this server"]
    default_query = f"""
        SELECT  '('||scanlator||') '||title AS name, id||'|'||scanlator AS value FROM series
        WHERE (id, scanlator) IN (SELECT series_id, scanlator FROM user_subs WHERE guild_id = $1 AND id = $2)
        OR (id, scanlator) IN (SELECT series_id, scanlator FROM tracked_guild_series WHERE guild_id = $1 AND 
            role_id IS NOT NULL AND role_id IN ({','.join(map(lambda x: str(x.id), interaction.user.roles))})
            )
        """
    default_params = (
        interaction.guild_id or interaction.user.id,
        interaction.user.id
    )

    if scanlator_name:
        default_query += " AND scanlator = $2"
        default_params += (scanlator_name,)

    if current:
        default_query += f" ORDER BY levenshtein(title, ${len(default_params) + 1}) DESC"
        default_params += (current,)

    results = await interaction.client.db.execute(default_query, *default_params, levenshtein=True)
    first_option = discord.app_commands.Choice(
        name=first_opt_names[0],
        value=f"{interaction.guild_id or interaction.user.id}-all"
    )
    if not results:
        if interaction.guild_id is None or (
                guild_config := await bot.db.get_guild_config(interaction.guild_id)) is None:
            return []
        if guild_config.default_ping_role and guild_config.default_ping_role in interaction.user.roles:
            return [first_option]
        return []

    choices = [SimpleNamespace(name=x[0] if len(x[0]) < 100 else x[0][:97] + "...", value=x[1]) for x in results][:25]
    normal_options = [discord.app_commands.Choice(name=x.name, value=x.value) for x in choices]
    if not current or current == "":
        return [first_option] + normal_options[:24]
    else:
        for opt in first_opt_names:
            if opt.lower().startswith(current.lower()):
                return [first_option] + normal_options[:24]
        return normal_options


@try_except
async def track_new_cmd(
        interaction: discord.Interaction, current: str | None = None) -> list[discord.app_commands.Choice]:
    """Autocomplete for the track_new command"""
    scanlator_name, current = get_scanlator_from_current_str(current)

    default_query = f"""
        SELECT 
            '('||scanlator||') '||title AS name,
            id||'|'||scanlator AS value
        FROM series
        WHERE (id, scanlator) NOT IN (
            SELECT series_id, scanlator FROM tracked_guild_series
            WHERE guild_id = $1
        ) AND lower(status) NOT IN ({completed_db_set})
        """
    default_params = (
        interaction.guild_id or interaction.user.id,
    )

    if scanlator_name:
        default_query += " AND scanlator = $2"
        default_params += (scanlator_name,)

    if current:
        default_query += f" ORDER BY levenshtein(title, ${len(default_params) + 1}) DESC"
        default_params += (current,)

    results = await interaction.client.db.execute(default_query, *default_params, levenshtein=True)
    if not results:
        return []
    choices = [SimpleNamespace(name=x[0] if len(x[0]) < 100 else x[0][:97] + "...", value=x[1]) for x in results][:25]
    return [discord.app_commands.Choice(name=x.name, value=x.value) for x in choices]


@try_except
async def chapters_cmd(
        interaction: discord.Interaction, current: str | None = None
) -> list[discord.app_commands.Choice]:
    scanlator_name, current = get_scanlator_from_current_str(current)
    default_query = f"""
                SELECT 
                    '('||scanlator||') '||title AS name,
                    id||'|'||scanlator AS value
                FROM series
                """
    default_params = tuple()
    if scanlator_name:
        default_query += f"WHERE scanlator = ${len(default_params) + 1}"
        default_params += (scanlator_name,)
    if current:
        default_query += f" ORDER BY levenshtein(title, ${len(default_params) + 1}) DESC"
        default_params += (current,)
    results = await interaction.client.db.execute(default_query, *default_params, levenshtein=True)
    if not results:
        return []
    choices = [SimpleNamespace(name=x[0] if len(x[0]) < 100 else x[0][:97] + "...", value=x[1]) for x in results][:25]
    return [discord.app_commands.Choice(name=x.name, value=x.value) for x in choices]


# ALIASES
info_cmd = chapters_cmd
bookmarks_new_cmd = info_cmd
