from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .rate_limiter import Limiter

from discord.app_commands.errors import CommandInvokeError

__all__ = (
    "GuildNotConfiguredError",
    "MangaNotFoundError",
    "MangaNotTrackedError",
    "MangaNotSubscribedError",
    "UnsupportedScanlatorURLFormatError",
    "URLAccessFailed",
    "BookmarkNotFoundError",
    "ChapterNotFoundError",
    "MangaCompletedOrDropped",
    "DatabaseError",
    "RateLimitExceeded",
    "WebhookNotFoundError",
    "MissingUserAgentError",
    "CustomError"
)


class BaseError(CommandInvokeError):
    """Base class for all errors in the library."""
    pass


class GuildNotConfiguredError(BaseError):
    """Raised when the guild is not configured."""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.error_msg = f"""
        The guild with ID `{self.guild_id}` is not configured.
        Consider using `/config guild` to configure the guild.
        """


class MangaNotFoundError(BaseError):
    """Raised when a manga is not found."""

    def __init__(self, manga_url: str):
        self.manga_url = manga_url
        self.error_msg = f"""
        The manga you entered was not found.
        ```diff\n- {self.manga_url}```
        """


class MangaNotTrackedError(BaseError):
    """Raised when a manga is not tracked."""

    def __init__(self, manga_url: str):
        self.manga_url = manga_url
        self.error_msg = f"""
        The manga you entered is not tracked.
        ```diff\n- {self.manga_url}```
        Use `/track new` to track the manga.
        """


class MangaNotSubscribedError(BaseError):
    """Raised when a manga is not subscribed."""

    def __init__(self, manga_url: str):
        self.manga_url = manga_url
        self.error_msg = f"""
        You are not subscribed to the manga you entered below.
        ```diff\n- {self.manga_url}```
        Use `/subscribe new` to subscribe to the manga.
        """


class UnsupportedScanlatorURLFormatError(BaseError):
    def __init__(self, url: str) -> None:
        self.url = url
        self.error_msg = f"""
        The URL you provided does not follow any of the known url formats.
        See `/supported_websites` for a list of supported websites and their url formats.
        ```diff\n- {self.url}```
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


class BookmarkNotFoundError(BaseError):
    """Raised when a manga is not found in the bookmark table."""

    def __init__(self, manga_url: str | None = None):
        self.manga_url = manga_url
        if manga_url is None:
            self.error_msg = "You have not bookmarked that manga."
        else:
            self.error_msg = f"You have not bookmarked [this manga]({self.manga_url})."


class ChapterNotFoundError(BaseError):
    """Raised when a chapter is not found in the bookmark table."""

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
        :param float period_remaining: The remaining time until the rate limit is reset.
        """
        super(RateLimitExceeded, self).__init__(f"{message}. Try again in {period_remaining} seconds.")
        self.limiter = limiter
        self.period_remaining = period_remaining
        self.message: str = message


class WebhookNotFoundError(BaseError):
    """Raised when the webhook is not found."""

    def __init__(self, webhook_url: str):
        self.webhook_id = re.search(
            r"https://discord\.com/api/webhooks/(?P<ID>\d+)/(:?.+)?",
            webhook_url
        ).groupdict().get("ID", "Not Found")
        self.error_msg = f"""
        The webhook with ID `{self.webhook_id}` is not found.
        Consider using `/config subscribe setup` to create a new one.
        """


class MissingUserAgentError(BaseError):
    def __init__(self, scanlator: str):
        self.scanlator = scanlator
        self.error_msg = f"""
        The user agent for `{self.scanlator}` is missing.
        Please contact the website owner to obtain one.
        """


class CustomError(BaseError):
    """Raised when a custom error is raised."""

    def __init__(self, error_msg: str, var: Any = None):
        self.error_msg = error_msg
        self.var = var
