"""Errors raised by the crawler client."""

from __future__ import annotations


class CrawlerError(Exception):
    """An error returned by the crawler in a response envelope.

    Attributes:
        code: stable machine-readable code (e.g. ``rate_limited``, ``unknown_type``)
        message: human-readable description from the server
        request_id: correlation id from the failing request
    """

    def __init__(self, code: str, message: str, *, request_id: str | None = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.request_id = request_id


class RequestTimeout(CrawlerError):
    """The request was sent but the server did not respond within the timeout."""

    def __init__(self, *, request_id: str | None = None) -> None:
        super().__init__(
            "request_timeout",
            "crawler did not respond in time",
            request_id=request_id,
        )


class Disconnected(CrawlerError):
    """Connection was closed before the response arrived."""

    def __init__(self, *, request_id: str | None = None) -> None:
        super().__init__(
            "disconnected",
            "crawler connection closed before response",
            request_id=request_id,
        )
