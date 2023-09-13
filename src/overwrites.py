# overwrite the default Emebed class to automatically set the footer author and image
from datetime import datetime
from typing import Any, Literal

import discord
from discord import Colour, Embed as _d_Embed
from discord.ext import commands


class Embed(_d_Embed):
    def __init__(self,
                 *,
                 colour: int | Colour | None = None,
                 color: int | Colour | None = None,
                 title: Any | None = None,
                 type: Literal['rich', 'image', 'video', 'gifv', 'article', 'link'] = 'rich',  # noqa
                 url: Any | None = None,
                 description: Any | None = None,
                 timestamp: datetime | None = None,
                 bot: commands.Bot | None = None,
                 ):
        super().__init__(
            colour=colour or color,
            title=title,
            type=type,
            url=url,
            description=description,
            timestamp=timestamp,
        )
        if bot is not None:
            self.set_footer(text=bot.user.display_name, icon_url=bot.user.display_avatar.url)


discord.Embed: Embed = Embed  # noqa
