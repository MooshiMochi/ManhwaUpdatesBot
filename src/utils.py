
from __future__ import annotations

import io
from typing import TYPE_CHECKING, Literal, Any

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


def ensure_configs(logger) -> Optional[dict]:
    required_keys = ["token"]

    if not os.path.exists("config.yml"):
        logger.critical(
            "   - config.yml file not found. Please follow the instructions listed in the README.md file."
        )
        exit_bot()

    with open("config.yml", "r") as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.critical(
                "   - config.yml file is not a valid YAML file. Please follow the instructions "
                "listed in the README.md file."
            )
            logger.critical("   - Error: " + str(e))
            exit_bot()
            return

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

    return config


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


def create_embeds(fmt_line: str, arguments: list[dict]) -> list[discord.Embed] | None:
    """
    Summary:
        Creates a list of embeds from a list of arguments.

    Parameters:
        fmt_line: The format line to use.
        arguments: The arguments to use.

    Returns:
        list[discord.Embed]: A list of embeds.

    Examples:
        >>> create_embeds("Hello {name}!", [{"name": "John"}, {"name": "Jane"}, ...])
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
        title=f"Bookmark: {bookmark.manga.human_name}", color=discord.Color.blurple(), url=bookmark.manga.manga_url
    )
    last_read_index = bookmark.last_read_chapter.index
    next_chapter = next((x for x in bookmark.available_chapters if x.index > last_read_index), None)

    em.description = (
        f"**Scanlator:** {bookmark.manga.scanlator.title()}\n"
        f"**Last Read Chapter:** [{bookmark.last_read_chapter.chapter_string}]({bookmark.last_read_chapter.url})\n"

        "**Next chapter:** "
        f"{f'[{next_chapter.chapter_string}]({next_chapter.url})' if next_chapter else '`Wait for updates`'}\n"

        "**Available Chapters:** Up to "
        f"[{bookmark.available_chapters[-1].chapter_string}]({bookmark.available_chapters[-1].url})\n"
    )
    em.set_footer(text="Manga Updates", icon_url=bot.user.avatar.url)
    em.set_author(
        name=f"Read on {bookmark.manga.scanlator.title()}", url=bookmark.manga.manga_url, icon_url=scanlator_icon_url
    )
    em.set_image(url=bookmark.series_cover_url)
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
