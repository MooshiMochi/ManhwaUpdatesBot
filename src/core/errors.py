from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rate_limiter import Limiter

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


class URLAccessFailed(BaseError):
    """Raised when a URL cannot be accessed."""

    def __init__(self, manga_url: str, status_code: int = 0, error_msg: str = None):
        self.manga_url = manga_url
        self.status_code: int = status_code
        self.error_msg = (
            f"There was an error{' (' + str(status_code) + ') ' if status_code != 0 else ''}"
            f"while trying to access [this website]({self.manga_url}) you entered."
        )
        self.arg_error_msg = error_msg


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


class MangaCompletedOrDropped(BaseError):
    """Raised when a manga is completed or dropped."""

    def __init__(self, manga_url: str):
        self.manga_url = manga_url
        self.error_msg = f"""
        [This manga]({self.manga_url}) has already been completed or dropped.
        Consider using `/bookmark new` to bookmark the manga instead.
        """


class DatabaseError(BaseError):
    """Raised when there is an error with the database."""

    def __init__(self, error_msg: str):
        self.error_msg = error_msg


class RateLimitExceeded(Exception):
    def __init__(self, limiter: Limiter, message: str, period_remaining: float):
        """
        Custom exception raise when the number of function invocations exceeds
        that imposed by a rate limit. Additionally, the exception is aware of
        the remaining time period after which the rate limit is reset.

        :param Limiter limiter: The rate limiter that raised the exception.
        :param string message: Custom exception message.
        :param float period_remaining: The time remaining until the rate limit is reset.
        """
        super(RateLimitExceeded, self).__init__(f"{message}. Try again in {period_remaining} seconds.")
        self.limiter = limiter
        self.period_remaining = period_remaining
        self.message: str = message
