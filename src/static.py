import re

import discord


class Emotes:
    warning = "⚠️"


class ID(discord.Object):
    """
    This is a simple class to represent a discord ID.
    """

    def __init__(self, id: int) -> None:
        super().__init__(id)


class RegExpressions:
    chapter_num_from_url = re.compile(r"(\d+([.]\d+)?)/?$")
    toonily_url = re.compile(
        r"(https?://)?(www\.)?toonily.com/webtoon/([a-zA-Z0-9-]+)(/.*)?"
    )
    manganato_url = re.compile(
        r"(https?://)?(www\.)?(chap)?manganato.com/manga-([a-zA-Z0-9-]+)(/.*)?"
    )
    tritinia_url = re.compile(
        r"(https?://)?(www\.)?tritinia.org/manga/([a-zA-Z0-9-]+)(/.*)?"
    )
    mangadex_url = re.compile(
        r"(https?://)?(www\.)?mangadex.org/title/([a-zA-Z0-9-]+)(/.*)?"
    )
