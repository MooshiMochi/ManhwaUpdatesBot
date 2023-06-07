from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta
from functools import partial
from itertools import islice
from typing import Any, TYPE_CHECKING

import aiohttp
import discord

if TYPE_CHECKING:
    from src.core.scanners import ABCScan
    from src.core.objects import Bookmark
    from src.core import MangaClient

import os
import re
from typing import Optional

import yaml

# noinspection PyPackages
from .static import RegExpressions
# noinspection PyPackages
from .enums import BookmarkSortType


def exit_bot() -> None:
    input("Press enter to continue...")
    exit(1)


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
                    logger.info(f"   - Testing proxy {proxy_url}...")
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


def load_config(logger) -> Optional[dict]:
    if not os.path.exists("config.yml"):
        logger.critical(
            "   - config.yml file not found. Please follow the instructions listed in the README.md file."
        )
        exit_bot()

    with open("config.yml", "r") as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.critical(
                "   - config.yml file is not a valid YAML file. Please follow the instructions "
                "listed in the README.md file."
            )
            logger.critical("   - Error: " + str(e))
            exit_bot()
            return


def ensure_configs(logger, config) -> Optional[dict]:
    required_keys = ["token"]
    if not config:
        logger.critical(
            "   - config.yml file is empty. Please follow the instructions listed in the README.md file."
        )
        exit_bot()
        return

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
        exit_bot()
        return

    default_config = {
        "debug": False,
        "privileged-intents": {
            "members": False,
            "presences": False,
            "message_content": False,
        },
        "extensions": ["src.ext.config", "src.ext.commands", "src.ext.dev", "src.ext.bookmark"],
        "prefix": "m!",
        "constants": {
            "synced": False,
            "log-channel-id": 0,
            "owner-ids": [0],
            "test-guild-id": 0,
            "cache-retention-seconds": 300,
        },
        "proxy": {
            "enabled": True,
            "ip": "210.148.141.4",  # japanese proxy with HTTPS support
            "port": 8080,
        },
        "user-agents": {
            "aquamanga": None,
            "aniglisscans": None,
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

    del_unavailable_scanlators(config, logger)

    return config


def del_unavailable_scanlators(config, logger):
    for key, value in config["user-agents"].items():
        if value is None:
            logger.warning(
                f"- {str(key).capitalize()} WILL NOT WORK without a valid user-agent. Please contact the website "
                f"owner to get a valid user-agent."
            )


def silence_debug_loggers(main_logger, logger_names: list) -> None:
    for logger_name in logger_names:
        logging.getLogger(logger_name).setLevel(logging.CRITICAL)
        main_logger.warning(f"Silenced debug logger: {logger_name}")


def get_manga_scanlator_class(scanlators: dict[str, ABCScan], url: str = None, key: str = None) -> Optional[ABCScan]:
    if url is None and key is None:
        raise ValueError("Either URL or key must be provided.")

    d: dict[str, ABCScan] = scanlators

    if key is not None:
        if existing_class := d.get(key):
            return existing_class

    for name, obj in RegExpressions.__dict__.items():
        if isinstance(obj, re.Pattern) and name.count("_") == 1:
            if obj.search(url):
                return d[name.split("_")[0]]


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
        show_page_number: bool = False
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
                show_page_number=True
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
    em.set_footer(text="Manga Updates", icon_url=bot.user.avatar.url)
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


def group_items_by(items: list[Any], key_path: list[str]) -> list[list[Any]]:
    """
    Groups items by a key path.

    Parameters:
        items (List): The items to group.
        key_path (List[str]): The key path to use, where each element is an attribute name.

    Returns:
        List[List[Any]]: The grouped items.

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
        return [items]

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
    sub_groups = []
    for group in groups.values():
        sub_groups.extend(group_items_by(group, sub_key_path))

    return sub_groups


def relative_time_to_seconds(time_string) -> int:
    time_regex = r'(?P<value>\d+)\s+(?P<unit>[a-z]+)\s+ago'
    match = re.match(time_regex, time_string.strip(), re.I)
    if not match:
        raise ValueError('Invalid time string')
    value, unit = match.groups()
    value = int(value)
    unit = unit.lower()
    unit_timedelta = {
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


def time_string_to_seconds(time_str: str) -> int:
    """Convert a time string to seconds since the epoch"""
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

    By the default, the last yielded list will have fewer than *n* elements
    if the length of *iterable* is not divisible by *n*:

        >>> list(chunked([1, 2, 3, 4, 5, 6, 7, 8], 3))
        [[1, 2, 3], [4, 5, 6], [7, 8]]

    To use a fill-in value instead, see the :func:`grouper` recipe.

    If the length of *iterable* is not divisible by *n* and *strict* is
    ``True``, then ``ValueError`` will be raised before the last
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
