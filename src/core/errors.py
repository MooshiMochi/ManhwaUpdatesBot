from discord.app_commands.errors import CommandInvokeError


class BaseError(CommandInvokeError):
    """Base class for all errors in the library."""

    pass


class MangaNotFoundError(BaseError):
    """Raised when a manga is not found in Manganato."""

    def __init__(
        self,
        manga_url: str,
    ):

        self.manga_url = manga_url

        self.error_msg = f"""
        The manga you entered was not found.
        ```diff\n- {self.manga_url}```
        """
