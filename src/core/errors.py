from discord.app_commands.errors import CommandInvokeError


class BaseError(CommandInvokeError):
    """Base class for all errors in the library."""
    pass


class MangaNotFound(BaseError):
    """Raised when a manga is not found."""
    def __init__(self, manga_url: str):
        self.manga_url = manga_url
        self.error_msg = f"""
        The manga you entered was not found.
        ```diff\n- {self.manga_url}```
        """


class BookmarkNotFound(BaseError):
    """Raised when a manga is not found in the bookmarks table."""
    def __init__(self, manga_url: str | None = None):
        self.manga_url = manga_url
        if manga_url is None:
            self.error_msg = "You have not bookmarked that manga."
        else:
            self.error_msg = f"You have not bookmarked [this manga]({self.manga_url})."


class ChapterNotFound(BaseError):
    """Raised when a chapter is not found in the bookmarks table."""
    def __init__(self, chapter_url: str | None = None):
        self.chapter_url = chapter_url
        if chapter_url is None:
            self.error_msg = "You have not bookmarked that chapter."
        else:
            self.error_msg = f"You have not bookmarked [this chapter]({self.chapter_url})."