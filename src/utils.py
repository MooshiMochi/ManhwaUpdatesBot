from __future__ import annotations

import inspect
import io
import logging
from datetime import datetime, timedelta
from functools import partial
from itertools import islice
from typing import Any, Coroutine, List, Literal, Optional, overload, TYPE_CHECKING, TypeVar

import aiohttp
import bs4
import curl_cffi.requests
import discord

if TYPE_CHECKING:
    from src.core import CachedCurlCffiSession, errors, MangaClient
    from src.core.objects import Bookmark, Manga
    from src.core.scanlators.classes import AbstractScanlator

import os
import re
import sys
import tldextract
from discord.utils import MISSING

# noinspection PyPackages
from .core.errors import RateLimitExceeded
# noinspection PyPackages
from .enums import BookmarkSortType

T = TypeVar("T")
V = TypeVar("V")


def exit_bot() -> None:
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
    from logging.handlers import RotatingFileHandler

    OUT = logging.StreamHandler(stream=sys.stdout)
    ERR = logging.StreamHandler(stream=sys.stderr)

    # create a rotating file handler for logging that merges both streams in 1 file
    MERGED = RotatingFileHandler(filename="bot.log", mode="a", maxBytes=1024 * 1024 * 10, encoding="utf-8")  # 10mb size

    if os.name == "nt" and 'PYCHARM_HOSTED' in os.environ:  # this patch is only required for pycharm
        # apply patch for isatty in pycharm being broken
        OUT.stream.isatty = lambda: True
        ERR.stream.isatty = lambda: True

    dt_fmt = '%Y-%m-%d %H:%M:%S'
    default_formatter = logging.Formatter('[{asctime}] [{levelname:<8}] {name}: {message}', dt_fmt, style='{')
    MERGED.setFormatter(default_formatter)

    if isinstance(OUT, logging.StreamHandler) and stream_supports_colour(OUT.stream):
        default_formatter = ColourFormatter()

    OUT.setFormatter(default_formatter)
    ERR.setFormatter(default_formatter)

    OUT.setLevel(level)
    ERR.setLevel(logging.ERROR)
    MERGED.setLevel(logging.DEBUG)  # feel free to change this to WARNING or INFO

    OUT.addFilter(_StdOutFilter())  # anything error or above goes to stderr

    root = logging.getLogger()
    root.setLevel(level)

    # clear out any existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    root.addHandler(OUT)
    root.addHandler(ERR)
    root.addHandler(MERGED)


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
                        proxy_url = f"http://{proxy_user}:{proxy_password}@{proxy_ip}:{proxy_port}"  # noqa
                    else:
                        proxy_url = f"http://{proxy_ip}:{proxy_port}"  # noqa
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
                except aiohttp.ClientConnectorError as e:
                    if e.strerror == "getaddrinfo failed":
                        logger.critical("You are offline! Please connect to a network and try again!")
                    else:
                        logger.critical(
                            "   - Proxy is not valid. Please use a different proxy and try again!"
                        )
                    exit_bot()
                    return
        else:
            if proxy_ip or proxy_port:
                logger.warning(
                    "   - Proxy is DISABLED but IP or PORT is specified. Consider enabling the proxy!"
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


def silence_debug_loggers(main_logger: logging.Logger, logger_names: list) -> None:
    for logger_name in logger_names:
        logging.getLogger(logger_name).setLevel(logging.CRITICAL)
        main_logger.warning(f"Silenced debug logger: {logger_name}")


def get_manga_scanlator_class(
        scanlators: dict[str, AbstractScanlator], url: str = None, key: str = None) -> Optional[AbstractScanlator]:
    d: dict[str, AbstractScanlator] = scanlators

    if key is not None:
        if existing_class := d.get(key):
            return existing_class
        return None

    elif url is not None:
        for scan in scanlators.values():
            if scan.check_ownership(url):
                return scan
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
    if per_page is not None and per_page < 1:
        raise ValueError("per_page parameter must be greater than 0.")

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
        append_mode: bool = False,
) -> list[discord.Embed]:
    for i, em in enumerate(embeds):
        if title_kwargs:
            title = title_kwargs.get("title", "")
            color = title_kwargs.get("color", None)
            url = title_kwargs.get("url", None)

            if append_mode and em.title:
                em.title += f" {title}"
            else:
                em.title = title

            em.colour = color if color else em.colour
            em.url = url if url else em.url

        if author_kwargs:
            if append_mode and em.author:
                for key, value in author_kwargs.items():
                    if hasattr(em.author, key):
                        setattr(em.author, key, f"{getattr(em.author, key)} {value}")
            else:
                em.set_author(**author_kwargs)

        if footer_kwargs:
            if append_mode and em.footer.text:
                footer_text = f"{em.footer.text} {footer_kwargs.get('text', '')}"
            else:
                footer_text = footer_kwargs.get('text', '')

            if show_page_number:
                footer_text = f"{footer_text} | Page {i + 1}/{len(embeds)}"

            em.set_footer(text=footer_text, icon_url=footer_kwargs.get('icon_url', None))

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
        title=f"Bookmark: {bookmark.manga.title}", color=discord.Color.blurple(), url=bookmark.manga.url
    )
    last_read_index = bookmark.last_read_chapter.index
    next_chapter = next((x for x in bookmark.manga.chapters if x.index > last_read_index), None)
    if bookmark.manga.chapters:
        available_chapters_str = f"{bookmark.manga.chapters[-1]} ({len(bookmark.manga.chapters)})\n"
    else:
        available_chapters_str = "`Wait for updates`\n"

    next_chapter_text = next_chapter
    if not next_chapter:
        next_chapter_text = "`Wait for updates!`"
        if bookmark.manga.completed:
            next_chapter_text = f"`None, manhwa is {bookmark.manga.status.lower()}`"
    em.description = (
        f"**Scanlator:** {bookmark.manga.scanlator.title()}\n"
        f"**Last Read Chapter:** {bookmark.last_read_chapter}\n"

        "**Next chapter:** "
        f"{next_chapter_text}\n"

        f"**Folder Location:** {bookmark.folder.value.title()}\n"

        f"**Available Chapters:** Up to {available_chapters_str}"

        f"**Status:** `{bookmark.manga.status}`\n"
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
    bookmarks = sorted(bookmarks, key=lambda b: b.manga.title.lower())
    if sort_type == BookmarkSortType.ALPHABETICAL:
        return ctype(sorted(bookmarks, key=lambda b: b.manga.title.lower()))
    elif sort_type == BookmarkSortType.LAST_UPDATED_TIMESTAMP:
        return ctype(sorted(bookmarks, key=lambda b: b.last_updated_ts, reverse=True))
    else:
        raise ValueError(f"Invalid sort type: {sort_type.value}")


@overload
def group_items_by(items: list[T], key_path: list[str], as_dict: Literal[False]) -> list[list[T]]:
    ...


@overload
def group_items_by(items: list[T], key_path: list[str], as_dict: Literal[True]) -> dict[str, list[T]]:
    ...


@overload
def group_items_by(items: list[T], key_path: list[str], as_dict: bool = ...) -> list[list[T]]:
    ...


def group_items_by(items: list[T], key_path: list[str], as_dict: bool = False) -> list[list[T]] | dict[str, list[T]]:
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


async def translate(session: CachedCurlCffiSession, text: str, from_: str, to_: str) -> tuple[str, str]:
    """
    Summary:
        Translate text from one language to another.
        NOTE
        :extra: This api is not guaranteed to work.
        Set up https://libretranslate.com/?source=ja&target=en&q=Hello as a fallback


    Args:
        session: CachedCurlCffiSession - the session to use to make the request
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
            It can contain placeholders referring to keys in the data dictionaries.
        group_key (str): The key in the dictionaries by which the data should be grouped.
        indexed (bool): Whether to prepend an index to each entry. Defaults to True.
        per_page (Optional[int]): The maximum number of entries in each embed. If None, no limit is applied.
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
        if not data_list:
            continue
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


async def raise_and_report_for_status(
        bot: MangaClient, response_object: aiohttp.ClientResponse | curl_cffi.requests.Response
) -> None:
    try:
        response_object.raise_for_status()
    except Exception as e:
        if hasattr(response_object, "status") or isinstance(response_object, aiohttp.ClientResponse):
            response_object: aiohttp.ClientResponse
            request_url = response_object.request_info.url
            status_code = response_object.status
        else:
            response_object: curl_cffi.requests.Response
            request_url = response_object.request.url
            status_code = response_object.status_code
        await bot.log_to_discord(f"Error when fetching URL: {request_url}: Status: {status_code}")
        raise e


def check_missing_perms(current_perms: discord.Permissions, target_perms: discord.Permissions) -> List[str]:
    """
    Summary:
        Check for missing permissions in a channel.
        Returns a list of missing permissions.

    Parameters:
        current_perms (discord.Permissions): The current permissions.
        target_perms (discord.Permissions): The target permissions.

    Returns:
        List[str]: A list of missing permissions.

    Examples:
        >>> check_missing_perms(discord.Permissions(permissions=0), discord.Permissions(permissions=8))
        ['send_messages']
    """
    missing_perms = target_perms & ~current_perms
    return [perm for perm, value in dict(missing_perms).items() if value]


def flatten(nested_list: list[Any]) -> list[Any] | Any:
    """
    Recursively flattens a nested list.
    """
    flat = []
    for item in nested_list:
        if isinstance(item, list):
            flat.extend(flatten(item))
        else:
            flat.append(item)
    return flat


def find_values_by_key(data: dict | list, target_key):
    """
    Recursively traverse the dictionary (or list of dictionaries) 'data'
    and return a list of all values corresponding to 'target_key'.

    Parameters:
        data (dict or list): The data to search through.
        target_key (str): The key whose values are to be found.

    Returns:
        list: A list of values for each occurrence of the target key.
    """
    results = []

    if isinstance(data, dict):
        for key, value in data.items():  # noqa: Scope warning
            # Check if the current key matches target_key
            if key == target_key:
                results.append(value)
            # If the value is a dict or list, traverse it recursively.
            if isinstance(value, (dict, list)):
                results.extend(find_values_by_key(value, target_key))

    elif isinstance(data, list):
        for item in data:
            # Recursively search each item in the list.
            results.extend(find_values_by_key(item, target_key))
    final_result = flatten(results)
    return final_result


async def extract_manga_by_command_parameter(
        bot: MangaClient,
        command_parameter: str,
        scanlators: dict[str, AbstractScanlator],
        url_regex: re.Pattern[str],
        errors_module: "errors"
) -> Optional[Manga]:
    """
    Summary:
        Extracts the manga from the db based on the command parameter.
        The commands /info and /chapters implement this function.

    Parameters:
        bot (MangaClient): The MangaClient instance.
        command_parameter (str): The command parameter to extract from.
        scanlators (List[AbstractScanlator]): The list of scanlators to search through.
        url_regex (re.Pattern[str]): A regex pattern to match URLs.
        errors_module: The 'errors' module.
        This is used to access errors without causing a circular import.

    Returns:
        Optional[Manga]: The manga object if found in the database otherwise None.
    """
    # Extract the manga ID and scanlator from the command parameter
    if url_regex.search(command_parameter):
        scanlator = get_manga_scanlator_class(scanlators, command_parameter)
        if scanlator is None:
            raise errors_module.UnsupportedScanlatorURLFormatError(command_parameter)
        scanlator_name = scanlator.name
        manga_id = await scanlator.get_id(command_parameter)
    else:
        try:
            manga_id, scanlator_name = command_parameter.split("|")
        except ValueError:
            raise errors_module.MangaNotFoundError(command_parameter)
    return await bot.db.get_series(manga_id, scanlator_name)
