from asyncio import TimeoutError
from typing import Iterable, Union

import discord
from discord.ext.commands import Context
from discord.ext.commands import Paginator as CommandPaginator


class PaginatorView(discord.ui.View):
    def __init__(
        self,
        _iterable: list[Union[str, int, discord.Embed]] = None,
        interaction: Union[discord.Interaction, Context] = None,
        timeout: float = 60.0,
    ) -> None:
        self._iterable = _iterable
        self.interaction: discord.Interaction = interaction
        self.page: int = 0
        self.message: discord.Message = None

        if not self._iterable and not self.interaction:
            raise AttributeError(
                "A list of items of type 'Union[str, int, discord.Embed]' was not provided to iterate through as well as the interaction."
            )

        elif not _iterable:
            raise AttributeError(
                "A list of items of type 'Union[str, int, discord.Embed]' was not provided to iterate through."
            )

        elif not interaction:
            raise AttributeError("The command interaction was not provided.")

        if not isinstance(_iterable, Iterable):
            raise AttributeError(
                "An iterable containing items of type 'Union[str, int, discord.Embed]' classes is required."
            )

        elif False in [
            isinstance(item, (str, int, discord.Embed)) for item in _iterable
        ]:
            raise AttributeError(
                "All items within the iterable must be of type 'str', 'int' or 'discord.Embed'."
            )

        super().__init__(timeout=timeout)
        self._iterable = list(self._iterable)

    def __get_response_kwargs(self):
        if isinstance(self._iterable[self.page], discord.Embed):
            return {"embed": self._iterable[self.page]}
        else:
            return {"content": self._iterable[self.page]}

    @discord.ui.button(label=f"⏮️", style=discord.ButtonStyle.blurple)
    async def _first_page(
        self, interaction: discord.Interaction, btn: discord.ui.Button
    ):
        self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple)
    async def back(self, interaction: discord.Interaction, btn: discord.ui.Button):
        self.page -= 1
        if self.page == -1:
            self.page = len(self._iterable) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.red)
    async def _stop(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple)
    async def forward(self, interaction: discord.Interaction, btn: discord.ui.Button):
        self.page += 1
        if self.page == len(self._iterable):
            self.page = 0
        await interaction.response.edit_message(**self.__get_response_kwargs())

    @discord.ui.button(label=f"⏭️", style=discord.ButtonStyle.blurple)
    async def _last_page(
        self, interaction: discord.Interaction, btn: discord.ui.Button
    ):
        self.page = len(self._iterable) - 1
        await interaction.response.edit_message(**self.__get_response_kwargs())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        author = None
        if isinstance(self.interaction, discord.Interaction):
            author = self.interaction.user
        else:
            author = self.interaction.author

        if author.id == interaction.user.id:
            return True
        else:
            embed = discord.Embed(title=f"🚫 You cannot use this menu!", color=0xFF0000)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False

    async def on_timeout(self) -> None:
        await self.message.edit(view=None)
        self.stop()

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item
    ) -> None:
        if isinstance(error, TimeoutError):
            pass
        else:
            em = discord.Embed(
                title=f"🚫 An unknown error occurred!",
                description=f"{str(error)[-1500:]}",
                color=0xFF0000,
            )
            await interaction.response.send_message(embed=em, ephemeral=True)


class TextPageSource:
    """Get pages for text paginator"""

    def __init__(
        self,
        text,
        *,
        prefix="```",
        suffix="```",
        max_size=2000,
        code_block=False,
        block_prefix="py",
    ):
        self._max_size = max_size

        if code_block:
            prefix += (
                block_prefix + "\n" if not block_prefix.endswith("\n") else block_prefix
            )
        pages = CommandPaginator(prefix=prefix, suffix=suffix, max_size=max_size - 200)
        for line in text.split("\n"):
            try:
                pages.add_line(line)
            except RuntimeError:
                converted_lines = self.__convert_to_chunks(line)
                for line in converted_lines:
                    pages.add_line(line)
        self.pages = pages

    def getPages(self, *, page_number=True):
        """Gets the pages."""
        pages = []
        pagenum = 1
        for page in self.pages.pages:
            if page_number:
                page += f"\nPage {pagenum}/{len(self.pages.pages)}"
                pagenum += 1
            pages.append(page)
        return pages

    def __convert_to_chunks(self, text):
        """Convert the text to chunks of size max_size-300"""
        chunks = []
        for i in range(0, len(text), self._max_size - 300):
            chunks.append(text[i : i + self._max_size - 300])
        return chunks
