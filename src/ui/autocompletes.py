from __future__ import annotations

import asyncio
import inspect
import logging
import time
import traceback as tb
from functools import partial, wraps
from types import SimpleNamespace
from typing import Any, Callable, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core import MangaClient

import discord
from discord import app_commands

from src.core.scanlators import scanlators
from src.static import Constants

logger = logging.getLogger("autocompletes")

completed_db_set = ", ".join(map(lambda x: f"'{x.lower()}'", Constants.completed_status_set))

# Dictionary to store the last execution time of each autocomplete function
_last_execution_times: Dict[str, float] = {}
# Dictionary to store the pending tasks for each autocomplete function
_pending_tasks: Dict[str, asyncio.Task] = {}
# Dictionary to store cached results for each autocomplete function
_cached_results: Dict[str, Dict[str, Any]] = {}
# Cache expiration time in seconds (10 minutes)
_CACHE_EXPIRATION_TIME = 600
# Flag to track if the cache cleanup task is running
_cache_cleanup_task_running = False


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


async def _cleanup_cache():
    """
    Periodically cleans up the cache by removing old entries.
    """
    global _cache_cleanup_task_running

    try:
        _cache_cleanup_task_running = True
        logger.debug("Starting cache cleanup task")

        while True:
            await asyncio.sleep(_CACHE_EXPIRATION_TIME)
            current_time = time.time()

            # Clean up the cache
            keys_to_remove = []
            for key, value in _cached_results.items():
                if current_time - value['timestamp'] > _CACHE_EXPIRATION_TIME:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del _cached_results[key]

            if keys_to_remove:
                logger.debug(f"Removed {len(keys_to_remove)} expired cache entries")
    except asyncio.CancelledError:
        logger.debug("Cache cleanup task cancelled")
    except Exception as e:
        logger.error(f"Error in cache cleanup task: {e}")
    finally:
        _cache_cleanup_task_running = False


def debounce_autocomplete(delay: float = 0.5):
    """
    Decorator to debounce autocomplete functions.
    Only executes the function if it hasn't been called for at least `delay` seconds.
    Also implements caching for results when appropriate.

    Args:
        delay (float): The delay in seconds before executing the function.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, current: str, *args, **kwargs):
            # Start the cache cleanup task if it's not already running
            if not _cache_cleanup_task_running:
                asyncio.create_task(_cleanup_cache())

            func_key = f"{func.__name__}_{interaction.user.id}"
            current_time = time.time()

            # Check if we have a cached result for this query
            cache_key = f"{func_key}_{current}"
            if cache_key in _cached_results:
                logger.debug(f"Cache hit for {func.__name__} with query '{current}'")
                return _cached_results[cache_key]['result']

            # Cancel any pending task for this function
            if func_key in _pending_tasks and not _pending_tasks[func_key].done():
                _pending_tasks[func_key].cancel()

            # If the function was called recently, delay execution
            if func_key in _last_execution_times and current_time - _last_execution_times[func_key] < delay:
                # Create a task to execute the function after the delay
                async def delayed_execution():
                    await asyncio.sleep(delay)
                    _last_execution_times[func_key] = time.time()
                    result = await func(interaction, current, *args, **kwargs)

                    # Cache the result if appropriate
                    # Only cache if current is not empty (to avoid caching the initial empty query)
                    if current:
                        # Check if we're using Levenshtein distance in the query
                        # This is a heuristic - we assume if 'levenshtein' is in the function's code
                        # and the query contains 'ORDER BY levenshtein' in func_code, then we're using Levenshtein distance
                        func_code = inspect.getsource(func)
                        if 'levenshtein' in func_code.lower() and 'ORDER BY levenshtein' in func_code:
                            # We should only cache if the Levenshtein distance is > 0.8
                            # Since we don't have direct access to the Levenshtein distance value,
                            # we'll use the presence of results as a proxy
                            if result and len(result) > 0:
                                _cached_results[cache_key] = {
                                    'result': result,
                                    'timestamp': time.time()
                                }
                                logger.debug(f"Cached result for {func.__name__} with query '{current}'")

                    return result

                task = asyncio.create_task(delayed_execution())
                _pending_tasks[func_key] = task

                # Return empty results while waiting
                return []

            # Execute the function immediately
            _last_execution_times[func_key] = current_time
            result = await func(interaction, current, *args, **kwargs)

            # Cache the result if appropriate (same logic as above)
            if current:
                func_code = inspect.getsource(func)
                if 'levenshtein' in func_code.lower() and 'ORDER BY levenshtein' in func_code:
                    if result and len(result) > 0:
                        _cached_results[cache_key] = {
                            'result': result,
                            'timestamp': time.time()
                        }
                        logger.debug(f"Cached result for {func.__name__} with query '{current}'")

            return result

        return wrapper

    return decorator


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


@try_except
async def search(_, current: str) -> list[discord.app_commands.Choice[str]]:
    return [
               app_commands.Choice(name=_scanlator.name.title(), value=_scanlator.name) for _scanlator in
               scanlators.values()
               if current == "" or _scanlator.name.lower().startswith(current.lower()) and
                  _scanlator.json_tree.properties.supports_search
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
@debounce_autocomplete()
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

    results = await interaction.client.db.execute(default_query, *default_params)
    if not results:
        return []
    choices = [SimpleNamespace(name=x[0] if len(x[0]) < 100 else x[0][:97] + "...", value=x[1]) for x in results][:25]
    return [discord.app_commands.Choice(name=x.name, value=x.value) for x in choices]


@try_except
@debounce_autocomplete()
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
@debounce_autocomplete()
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

    results = await interaction.client.db.execute(default_query, *default_params)
    if not results:
        return []
    choices = [SimpleNamespace(name=x[0] if len(x[0]) < 100 else x[0][:97] + "...", value=x[1]) for x in results][:25]
    return [discord.app_commands.Choice(name=x.name, value=x.value) for x in choices]


@try_except
@debounce_autocomplete()
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

    results = await interaction.client.db.execute(default_query, *default_params)
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
@debounce_autocomplete()
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

    results = await interaction.client.db.execute(default_query, *default_params)
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
@debounce_autocomplete()
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

    results = await interaction.client.db.execute(default_query, *default_params)
    if not results:
        return []
    choices = [SimpleNamespace(name=x[0] if len(x[0]) < 100 else x[0][:97] + "...", value=x[1]) for x in results][:25]
    return [discord.app_commands.Choice(name=x.name, value=x.value) for x in choices]


@try_except
@debounce_autocomplete()
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
    results = await interaction.client.db.execute(default_query, *default_params)
    if not results:
        return []
    choices = [SimpleNamespace(name=x[0] if len(x[0]) < 100 else x[0][:97] + "...", value=x[1]) for x in results][:25]
    return [discord.app_commands.Choice(name=x.name, value=x.value) for x in choices]


# ALIASES
info_cmd = chapters_cmd
bookmarks_new_cmd = info_cmd
