from __future__ import annotations

import inspect
import io
import logging
from datetime import datetime, timedelta
from functools import partial
from itertools import islice
from typing import Any, Coroutine, List, Optional, TYPE_CHECKING

import aiohttp
import bs4
import discord

if TYPE_CHECKING:
    from src.core import MangaClient
    from src.core.objects import Bookmark
    from src.core.scanners import ABCScan
    from src.core import CachedClientSession

import os
import re
import sys
import tldextract
from discord.utils import MISSING

import yaml

# noinspection PyPackages
from .core.errors import RateLimitExceeded
# noinspection PyPackages
from .static import RegExpressions, ScanlatorsRequiringUserAgent
# noinspection PyPackages
from .enums import BookmarkSortType


def exit_bot() -> None:
    input("Press enter to continue...")
    exit(1)


class _StdOutFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filters the logging levels that should be written to STDOUT.
        Anything smaller than warning goes to STDOUT, anything else goes to STDERR.
        """
        return record.levelno < logging.ERROR


def setup_logging(
        *,
        level: int = MISSING,
) -> None:
    """
    Sets up logging for the bot.
    This function must only be called once!

    Parameters:
        level: The logging level to use. Defaults to INFO.

    Returns:
        None
    """
    if level is MISSING:
        level = logging.INFO

    # noinspection PyProtectedMember
    from discord.utils import _ColourFormatter as ColourFormatter, stream_supports_colour

    OUT = logging.StreamHandler(stream=sys.stdout)
    ERR = logging.StreamHandler(stream=sys.stderr)

    if os.name == "nt" and 'PYCHARM_HOSTED' in os.environ:  # this patch is only required for pycharm
        # apply patch for isatty in pycharm being broken
        OUT.stream.isatty = lambda: True
        ERR.stream.isatty = lambda: True

    if isinstance(OUT, logging.StreamHandler) and stream_supports_colour(OUT.stream):
        formatter = ColourFormatter()
    else:
        dt_fmt = '%Y-%m-%d %H:%M:%S'
        formatter = logging.Formatter('[{asctime}] [{levelname:<8}] {name}: {message}', dt_fmt, style='{')

    OUT.setFormatter(formatter)
    ERR.setFormatter(formatter)

    OUT.setLevel(level)
    ERR.setLevel(logging.ERROR)

    OUT.addFilter(_StdOutFilter())  # anything error or above goes to stderr

    root = logging.getLogger()
    root.setLevel(level)

    # clear out any existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    root.addHandler(OUT)
    root.addHandler(ERR)


def test_logger(logger: logging.Logger) -> None:
    logger.debug("Testing debug logging")
    logger.info("Testing info logging")
    logger.warning("Testing warning logging")
    logger.error("Testing error logging")
    logger.critical("Testing critical logging")


async def ensure_proxy(config, logger) -> None:
    async with aiohttp.ClientSession() as session:
        proxy_ip = config["proxy"]["ip"]
        proxy_port = config["proxy"]["port"]
        proxy_user = config["proxy"]["username"]
        proxy_password = config["proxy"]["password"]
        proxy_enabled: bool = config["proxy"]["enabled"]

        if proxy_enabled:
            if not proxy_ip or not proxy_port:
                logger.critical(
                    "- Proxy is enabled but IP or PORT is not specified. Please provide both the PORT and IP of the "
                    "proxy or disable the proxy."
                )
                exit_bot()
                return
            else:
                try:
                    int(proxy_port)
                except ValueError:
                    logger.critical(
                        "   - Proxy PORT is not a valid integer. Please provide a valid proxy PORT."
                    )
                    exit_bot()
                    return

                try:
                    if proxy_user and proxy_password:
                        proxy_url = f"http://{proxy_user}:{proxy_password}@{proxy_ip}:{proxy_port}"
                    else:
                        proxy_url = f"http://{proxy_ip}:{proxy_port}"
                    proxy_str = proxy_url.replace(
                        proxy_user, '[PROXY USER]').replace(proxy_password, '[PROXY PASSWORD]')
                    logger.info(f"   - Testing proxy {proxy_str}...")
                    async with session.get("https://www.youtube.com", proxy=proxy_url, ssl=False) as r:
                        if r.status == 200:
                            logger.info(
                                f"   - Proxy is working..."
                            )
                        else:
                            logger.critical(
                                "   - Proxy is not valid. Please use a different proxy and try again!"
                            )
                            exit_bot()
                            return
                except aiohttp.ClientConnectorError:
                    logger.critical(
                        "   - Proxy is not valid. Please use a different proxy and try again!"
                    )
                    exit_bot()
                    return
        else:
            if proxy_ip or proxy_port:
                logger.warning(
                    "   - Proxy is DISABLED but IP or port is specified."
                )


async def ensure_environment(bot, logger) -> None:
    if not os.path.isdir(".git"):
        logger.critical(
            "Bot wasn't installed using Git. Please re-install using the command below:"
        )
        logger.critical(
            "       git clone https://github.com/MooshiMochi/ManhwaUpdatesBot"
        )
        await bot.close()
        exit_bot()


def load_config(logger: logging.Logger, *, auto_exit: bool = True, filepath: str = "config.yml") -> Optional[dict]:
    if not os.path.exists(filepath):
        logger.critical(
            "   - config.yml file not found. Please follow the instructions listed in the README.md file."
        )
        if auto_exit:
            return exit_bot()

        logger.critical(
            "   - Creating a new config.yml file..."
        )
        with open(filepath, "w"):
            pass

    with open(filepath, "r") as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.critical(
                "   - config.yml file is not a valid YAML file. Please follow the instructions "
                "listed in the README.md file."
            )
            logger.critical("   - Error: " + str(e))
            if auto_exit:
                exit_bot()
            return {}


def ensure_configs(logger, config: dict, scanlators: dict[str, ABCScan], *, auto_exit: bool = True) -> Optional[dict]:
    required_keys = ["token"]
    if not config:
        logger.critical(
            "   - config.yml file is empty. Please follow the instructions listed in the README.md file."
        )
        if auto_exit:
            exit_bot()
            return {}

    if not all(key in config for key in required_keys):
        missing_required_keys = [key for key in required_keys if key not in config]
        missing_required_keys_str = (
            (
                    "'"
                    + "', '".join([key for key in required_keys if key not in config])
                    + "'"
            )
            if len(missing_required_keys) > 1
            else "'" + missing_required_keys[0] + "'"
        )
        if os.name == "nt":
            setup_file = "setup.bat"
        else:
            setup_file = "setup.sh"
        logger.critical(
            f"   - config.yml file is missing following required key(s): "
            f"{missing_required_keys_str}. Please run the {setup_file} file."
        )
        if auto_exit:
            exit_bot()
            return {}

    default_config = {
        "debug": False,
        "privileged-intents": {
            "members": False,
            "presences": False,
            "message_content": False,
        },
        "extensions": ["src.ext.config", "src.ext.commands", "src.ext.dev", "src.ext.bookmark", "src.ext.update_check"],
        "prefix": "m!",
        "constants": {
            "first_bot_startup": True,
            "autosync": True,
            "log-channel-id": 0,
            "command-log-channel-id": 0,
            "owner-ids": [0],
            "test-guild-id": 0,
            "cache-retention-seconds": 300,
            "time-for-manga-to-be-considered-stale": 7776000,
        },
        "proxy": {
            "enabled": True,
            "ip": "2.56.119.93",  # user webshare.io proxy (I recommend)
            "port": 5074,
            "username": "difemjzc",  # noqa
            "password": "em03wrup0hod",  # noqa
        },
        "user-agents": {
            "aquamanga": None,
            "anigliscans": None,
            "toonily": None,
        },
    }

    config_edited: bool = False
    for key, value in default_config.items():
        if key not in config:
            logger.warning(
                "    - config.yml file is missing optional key: '"
                + key
                + "'."
                + " Using default configs."
            )
            config[key] = value
            config_edited = True

        if isinstance(value, dict):
            for k, v in value.items():
                if k not in config[key]:
                    logger.warning(
                        "    - config.yml file is missing optional key: '"
                        + k
                        + "'."
                        + " Using default configs."
                    )
                    config[key][k] = v
                    config_edited = True

    if config_edited:
        logger.warning(
            "    - Using default config values may cause the bot to not function as expected."
        )
        with open("config.yml", "w") as f:
            yaml.safe_dump(config, f)
        logger.warning("    - config.yml file has been updated with default configs.")

    del_unavailable_scanlators(config, logger, scanlators)

    return config


def del_unavailable_scanlators(config: dict, logger: logging.Logger, scanlators: dict[str, ABCScan]):
    for scanlator in ScanlatorsRequiringUserAgent.scanlators:
        if config.get('user-agents', {}).get(scanlator) is None:
            logger.warning(
                f"- {scanlator} WILL NOT WORK without a valid user-agent. Removing ...\nPlease contact the website "
                f"owner to get a valid user-agent."
            )
            scanlators.pop(scanlator, None)


def silence_debug_loggers(main_logger: logging.Logger, logger_names: list) -> None:
    for logger_name in logger_names:
        logging.getLogger(logger_name).setLevel(logging.CRITICAL)
        main_logger.warning(f"Silenced debug logger: {logger_name}")


def get_manga_scanlator_class(scanlators: dict[str, ABCScan], url: str = None, key: str = None) -> Optional[ABCScan]:
    d: dict[str, ABCScan] = scanlators

    if key is not None:
        if existing_class := d.get(key):
            return existing_class
        return None

    elif url is not None:
        for name, obj in RegExpressions.__dict__.items():
            if isinstance(obj, re.Pattern) and name.count("_") == 1 and name.split("_")[1] == "url":
                if obj.search(url):
                    return d.get(name.split("_")[0])
        return None

    raise ValueError("Either URL or key must be provided.")


def write_to_discord_file(filename: str, content: str) -> discord.File:
    stream = io.BytesIO()
    stream.write(content.encode())
    stream.seek(0)
    return discord.File(stream, filename=filename)


def create_embeds(fmt_line: str, arguments: list[dict], per_page: Optional[int] = None) -> list[discord.Embed] | None:
    """
    Summary:
        Creates a list of embeds from a list of arguments.

    Parameters:
        fmt_line: The format line to use.
        arguments: The arguments to use.
        per_page: The number of arguments to put in each embed.

    Returns:
        list[discord.Embed]: A list of embeds.

    Examples:
        >>> create_embeds("Hello {name}!", [{"name": "John"}, {"name": "Jane"}, ...], per_page=10)
        [<discord.embeds.Embed object at 0x000001F5B1B5B4C0>, ...]
    """
    if not arguments:
        return None

    embeds = []
    max_desc_length = 4096
    append_last = False
    embed = discord.Embed(title="", description="", color=0x00FF00)
    for i, arg in enumerate(arguments):
        if len(embed.description) + len(fmt_line.format(**arg)) + 1 > max_desc_length:
            embeds.append(embed)
            embed = discord.Embed(title="", description="", color=0x00FF00)

        elif per_page is not None and i > 0 and i % per_page == 0:
            embeds.append(embed)
            embed = discord.Embed(title="", description="", color=0x00FF00)

        embed.description += fmt_line.format(**arg) + "\n"
        if i == len(arguments) - 1:
            append_last = True

    if append_last:
        embeds.append(embed)

    return embeds


def modify_embeds(
        embeds: list[discord.Embed],
        title_kwargs: dict = None,
        author_kwargs: dict = None,
        footer_kwargs: dict = None,
        thumbnail_image_url: str | list[str] = None,
        image_url: str | list[str] = None,
        show_page_number: bool = False,
        # append_mode: bool = False,  # TODO: Implement this ig?
) -> list[discord.Embed]:
    """
    Summary:
        Modifies a list of embeds.

    Parameters:
        embeds: The embeds to modify.
        title_kwargs: The title kwargs to use.
        author_kwargs: The author kwargs to use.
        footer_kwargs: The footer kwargs to use.
        thumbnail_image_url: The thumbnail image URL to use.
        image_url: The image URL to use.
        show_page_number: Whether to show the page number.
        # append_mode: Whether to append to the value if it exists or overwrite the current value.

    Returns:
        list[discord.Embed]: The modified embeds.

    Examples:
        >>> modify_embeds(
                embeds,
                title_kwargs={"name": "MangaDex"},
                author_kwargs={"name": "John Doe", "scanlator_icon_url": "https://example.com/icon.png"},
                footer_kwargs={"text": "MangaDex"},
                thumbnail_image_url="https://example.com/thumbnail.png",
                image_url="https://example.com/image.png",
                show_page_number=True,
                append_mode=True,
            )
        [<discord.embeds.Embed object at 0x000001F5B1B5B4C0>, ...]
    """

    for i, em in enumerate(embeds):
        if title_kwargs:
            em.title = title_kwargs.get("title")
            em.colour = title_kwargs.get("color")
            em.url = title_kwargs.get("url")
        if author_kwargs:
            em.set_author(**author_kwargs)
        if footer_kwargs:
            em.set_footer(**footer_kwargs)
        if show_page_number:
            if em.footer.text:
                em.set_footer(text=f"{em.footer.text} | Page {i + 1}/{len(embeds)}")
            else:
                em.set_footer(text=f"Page {i + 1}/{len(embeds)}")
        if thumbnail_image_url:
            if isinstance(thumbnail_image_url, list):
                em.set_thumbnail(url=thumbnail_image_url[i])
            else:
                em.set_thumbnail(url=thumbnail_image_url)
        if image_url:
            if isinstance(image_url, list):
                em.set_image(url=image_url[i])
            else:
                em.set_image(url=image_url)

    return embeds


def create_bookmark_embed(bot: MangaClient, bookmark: Bookmark, scanlator_icon_url: str) -> discord.Embed:
    em = discord.Embed(
        title=f"Bookmark: {bookmark.manga.human_name}", color=discord.Color.blurple(), url=bookmark.manga.url
    )
    last_read_index = bookmark.last_read_chapter.index
    next_chapter = next((x for x in bookmark.manga.available_chapters if x.index > last_read_index), None)
    if bookmark.manga.available_chapters:
        available_chapters_str = f"{bookmark.manga.available_chapters[-1]} ({len(bookmark.manga.available_chapters)})\n"
    else:
        available_chapters_str = "`Wait for updates`\n"

    em.description = (
        f"**Scanlator:** {bookmark.manga.scanlator.title()}\n"
        f"**Last Read Chapter:** {bookmark.last_read_chapter}\n"

        "**Next chapter:** "
        f"{next_chapter if next_chapter else '`Wait for updates`'}\n"

        f"**Available Chapters:** Up to {available_chapters_str}"

        f"**Completed:** `{bool(bookmark.manga.completed)}`\n"
    )
    em.set_footer(text=bot.user.display_name, icon_url=bot.user.display_avatar.url)
    em.set_author(
        name=f"Read on {bookmark.manga.scanlator.title()}", url=bookmark.manga.url, icon_url=scanlator_icon_url
    )
    em.set_image(url=bookmark.manga.cover_url)
    return em


def sort_bookmarks(bookmarks: list[Bookmark], sort_type: BookmarkSortType) -> list[Bookmark]:
    """
    Summary:
        Sorts a list of bookmarks by a sort type.

    Parameters:
        bookmarks: The bookmarks to sort.
        sort_type: The sort type to use.

    Returns:
        list[Bookmark]: The sorted bookmarks.
    """
    ctype = type(bookmarks)
    # sort alphabetically first, then sort by whatever the sort type is.
    bookmarks = sorted(bookmarks, key=lambda b: b.manga.human_name.lower())
    if sort_type == BookmarkSortType.ALPHABETICAL:
        return ctype(sorted(bookmarks, key=lambda b: b.manga.human_name.lower()))
    elif sort_type == BookmarkSortType.LAST_UPDATED_TIMESTAMP:
        return ctype(sorted(bookmarks, key=lambda b: b.last_updated_ts, reverse=True))
    else:
        raise ValueError(f"Invalid sort type: {sort_type.value}")


def group_items_by(
        items: list[Any], key_path: list[str], as_dict: bool = False
) -> dict[str, list[Any]] | list[list[Any]]:
    """
    Groups items by a key path.

    Parameters:
        items (List): The items to group.
        key_path (List[str]): The key path to use, where each element is an attribute name.
        as_dict (bool): Whether to return the groups as a dictionary.

    Returns:
        List[List[Any]]: The grouped items.
                    Or
        Dict[Any, List[Any]]: The grouped items.

    Examples:
        >>> from enum import Enum
        >>> class Color(Enum):
        ...     RED = 1
        ...     GREEN = 2
        ...     BLUE = 3
        ...
        >>> # noinspection PyShadowingNames
        >>> items = [Color.RED, Color.GREEN, Color.BLUE, Color.RED]
        >>> group_items_by(items, ["value"])
        [[<Color.RED: 1>, <Color.RED: 1>], [<Color.GREEN: 2>], [<Color.BLUE: 3>]]
    """
    if not key_path:
        return [items] if not as_dict else items

        # Define a helper function to get the value of an attribute path in an object

    def get_attr(obj, path):
        for attr in path:
            obj = getattr(obj, attr)
        return obj

        # Group the items by the first key in the key path

    key = key_path[0]
    groups = {}
    for item in items:
        value = get_attr(item, key.split("."))
        if value not in groups:
            groups[value] = []
        groups[value].append(item)

    # Recursively group the items by the remaining keys in the key path
    sub_key_path = key_path[1:]
    if as_dict:
        for group_key, group in groups.items():
            groups[group_key] = group_items_by(group, sub_key_path, as_dict=True)
        return groups
    else:
        sub_groups = []
        for group in groups.values():
            sub_groups.extend(group_items_by(group, sub_key_path, as_dict=False))
        return sub_groups


def relative_time_to_seconds(time_string) -> Optional[int]:
    time_regex = r'(?P<value>\d+|an?)(?:\sfew)?\s+(?P<unit>[a-z]+)\s+ago'  # noqa
    match = re.match(time_regex, time_string.strip(), re.I)
    if not match:
        raise ValueError(f'Invalid time string: {time_string}')
    value, unit = match.groups()
    value = int(value) if value not in ["a", "an"] else 1
    unit = unit.lower()
    unit_timedelta = {
        'sec': timedelta(seconds=1),
        'min': timedelta(minutes=1),
        'second': timedelta(seconds=1),
        'minute': timedelta(minutes=1),
        'hour': timedelta(hours=1),
        'day': timedelta(days=1),
        'week': timedelta(weeks=1),
        'month': timedelta(days=30),
        'year': timedelta(days=365)
    }.get(unit[:-1] if unit.endswith("s") else unit, None)
    if not unit_timedelta:
        raise ValueError(f'Invalid time unit: {unit}')
    return int((datetime.now() - (value * unit_timedelta)).timestamp())


def time_string_to_seconds(time_str: str, formats: list[str] = None) -> int:
    """Convert a time string to seconds since the epoch"""
    try:
        return relative_time_to_seconds(time_str)
    except ValueError as e:  # noqa
        # print(e)
        pass

    if not formats:
        formats = ["%b %d, %Y", "%B %d, %Y", "%d/%m/%Y", "%d-%m-%Y"]

    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            return int(dt.timestamp())
        except ValueError:
            continue
    raise ValueError(f"Invalid time string: {time_str}")


def take(n, iterable):
    """Return first *n* items of the iterable as a list.

        >>> take(3, range(10))
        [0, 1, 2]

    If there are fewer than *n* items in the iterable, all of them are
    returned.

        >>> take(10, range(3))
        [0, 1, 2]

    """
    return list(islice(iterable, n))


def chunked(iterable, n, strict=False):
    """Break *iterable* into lists of length *n*:

        >>> list(chunked([1, 2, 3, 4, 5, 6], 3))
        [[1, 2, 3], [4, 5, 6]]

    By default, the last yielded list will have fewer than *n* elements
    if the length of *iterable* is not divisible by *n*:

        >>> list(chunked([1, 2, 3, 4, 5, 6, 7, 8], 3))
        [[1, 2, 3], [4, 5, 6], [7, 8]]

    To use a fill-in value instead, see the :func:`grouper` recipe.

    If the length of *iterable* is not divisible by *n* and *strict* is
    `True`, then `ValueError` will be raised before the last
    list is yielded.

    """
    iterator = iter(partial(take, n, iter(iterable)), [])
    if strict:
        if n is None:
            raise ValueError('n must not be None when using strict mode.')

        def ret():
            for chunk in iterator:
                if len(chunk) != n:
                    raise ValueError('iterable is not divisible by n.')
                yield chunk

        return iter(ret())
    else:
        return iterator


def replace_tag_with(
        soup: bs4.BeautifulSoup | bs4.Tag, tag_name: str, replace_with: str, *, closing: bool = False
) -> bs4.BeautifulSoup:
    """Replace tags with specified replace string"""

    for _tag in soup.find_all(tag_name):
        if closing:
            _tag.replace_with(replace_with + _tag.text + replace_with)
        else:
            _tag.replace_with(replace_with + _tag.text)

    return soup


def get_url_hostname(url: str) -> str:
    """Get the hostname of an url"""
    return tldextract.extract(url).domain


def is_from_stack_origin(*, class_name: str = None, function_name: str = None, file_name: str = None) -> bool:
    if not any([class_name, function_name, file_name]):
        raise ValueError("At least one of class_name, function_name or file_name must be provided")
    call_stack = inspect.stack()

    given_params: dict[str, bool | None] = {
        "class_name": None,
        "function_name": None,
        "file_name": None
    }

    for record in call_stack:
        frame = record[0]
        info = inspect.getframeinfo(frame)

        if class_name is not None:
            # Get the class of the method from the frame
            method_class = getattr(inspect.getmodule(frame), class_name, None)
            if method_class is not None and method_class.__name__ == class_name:
                given_params["class_name"] = True
                # return True

        if function_name is not None and info.function == function_name:
            given_params["function_name"] = True
            # return True

        if file_name is not None and os.path.basename(info.filename) == file_name:
            given_params["file_name"] = True
            # return True

    to_eval = [x for x in given_params.values() if x is not None]
    if len(to_eval) == 0:
        return False
    return all(to_eval)


async def respond_if_limit_reached(coro: Coroutine, interaction: discord.Interaction) -> Any | str:
    if not interaction.response.is_done():  # noqa
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
    try:
        return await coro
    except RateLimitExceeded as e:
        next_try_ts = datetime.now().timestamp() + e.period_remaining
        em = discord.Embed(title="Rate Limit Exceeded", color=discord.Color.red())
        em.description = (
            f"Rate limit exceeded for this website.\n"
            f"Please try again in <t:{int(next_try_ts)}:R>."
        )
        em.set_footer(text=interaction.client.user.display_name, icon_url=interaction.client.user.display_avatar.url)
        await interaction.followup.send(
            embed=em
        )
        return "LIMIT_REACHED"


def dict_remove_keys(d: dict, keys: list[str]) -> dict:
    """
    Remove keys from a dict.
    NOTE: Does not modify the original dict
    """
    return {k: v for k, v in d.items() if k not in keys}


async def translate(session: CachedClientSession, text: str, from_: str, to_: str) -> tuple[str, str]:
    """
    Summary:
        Translate text from one language to another.
        NOTE
        :extra: This api is not guaranteed to work.
        Set up https://libretranslate.com/?source=ja&target=en&q=Hello as a fallback


    Args:
        session: CachedClientSession - the session to use to make the request
        text: Text to translate
        from_: Language to translate from
        to_: Language to translate to

    Returns:
        tuple[str, str]: Translated text and language from
    """
    async with session.get(
            f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={from_}&tl={to_}&dt=t&q={text}",
            cache_time=24 * 60 * 60  # 1 day caching
    ) as r:
        if r.status == 200:
            resp = await r.json()
            return (
                " ".join([str(i[0]).strip() for i in resp[0] if i[0]]),
                resp[-6] or resp[-7],
            )
        else:
            raise Exception("Error while translating", r)


def create_dynamic_grouped_embeds(
        data_dicts: list[dict], fmt_line: str, group_key: str, indexed: bool = True, per_page: Optional[int] = None
) -> list[discord.Embed]:
    """
    Summary:
        Generates a list of embeds from provided data dictionaries, grouped by a specified key.
        The data within each group is formatted using the provided format line.
        An index can be added to each entry for easy referencing.

    Parameters:
        data_dicts (List[dict]): A list of dictionaries containing data to be grouped and formatted.
        fmt_line (str): The format string to use for each entry.
            Can contain placeholders referring to keys in the data dictionaries.
        group_key (str): The key in the dictionaries by which the data should be grouped.
        indexed (bool, optional): Whether to prepend an index to each entry. Defaults to True.
        per_page (Optional[int], optional): The maximum number of entries in each embed. If None, no limit is applied.
            Defaults to None.

    Returns:
        List[Embed]: A list of embeds with the grouped and formatted data.

    Raises:
        ValueError: If the provided group_key is not found in any of the data dictionaries.

    Examples:
        >>> data = [{"scanlator": "GroupA", "name": "Manga1", "chapter": "Ch1"}, {"scanlator": "GroupB", "name": "Manga2", "chapter": "Ch2"}]  # noqa
        >>> create_dynamic_grouped_embeds_v3(data, "{index}. {name} - {chapter}", group_key="scanlator", indexed=True, per_page=1)  # noqa
        [<Embed object with description "GroupA\n1. Manga1 - Ch1">, <Embed object with description "GroupB\n2. Manga2 - Ch2">] # noqa
    """
    grouped = {}
    for data in data_dicts:
        if group_key not in data:
            raise ValueError(f"The group key '{group_key}' was not found in the data dictionary.")

        group_value = data[group_key]
        if group_value not in grouped:
            grouped[group_value] = []
        grouped[group_value].append(data)

    # Creating embeds
    embeds = []
    max_desc_length = 4096
    append_last = False
    embed = discord.Embed(title="", description="", color=discord.Color.blurple())
    line_index = 0

    for group_value, data_list in grouped.items():
        embed.description += f"\n**{group_value}**\n"
        for data in data_list:
            line_index += 1
            formatted_data = fmt_line.format(index=(line_index if indexed else ""), **data)

            if len(embed.description) + len(formatted_data) + len(group_value) + 5 > max_desc_length:
                embeds.append(embed)
                embed = discord.Embed(title="", description="", color=discord.Color.blurple())

            elif per_page is not None and line_index > 0 and line_index % per_page == 0:
                embeds.append(embed)
                embed = discord.Embed(title="", description="", color=discord.Color.blurple())

            # Append group_value name only if it's a new group
            if formatted_data == data_list[0]:
                embed.description += f"\n**{group_value}**\n"
            embed.description += formatted_data + "\n"

            if data == data_list[-1] and data == data_dicts[-1]:
                append_last = True

    if append_last:
        embeds.append(embed)

    return embeds
