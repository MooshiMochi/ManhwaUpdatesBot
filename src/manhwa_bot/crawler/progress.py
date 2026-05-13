"""Progress event parsing for crawler WebSocket requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CrawlerProgressEvent:
    """Progress update emitted by the crawler for an in-flight request."""

    request_id: str
    event: str
    sequence: int
    title: str
    status: str
    detail: str | None = None
    retry_attempt: int | None = None
    max_retries: int | None = None
    error_code: str | None = None
    elapsed_ms: int | None = None


def parse_progress_event(payload: Mapping[str, Any]) -> CrawlerProgressEvent:
    """Parse a crawler ``request_progress`` payload.

    Missing required fields raise ``ValueError``. Optional fields are accepted
    only when they have the expected lightweight shape; unknown fields are
    ignored so backend additions do not break the bot.
    """
    request_id = _required_str(payload, "request_id")
    event = _required_str(payload, "event")
    sequence = _required_int(payload, "sequence")
    title = _required_str(payload, "title")
    status = _required_str(payload, "status")
    return CrawlerProgressEvent(
        request_id=request_id,
        event=event,
        sequence=sequence,
        title=title,
        detail=_optional_str(payload, "detail"),
        status=status,
        retry_attempt=_optional_int(payload, "retry_attempt"),
        max_retries=_optional_int(payload, "max_retries"),
        error_code=_optional_str(payload, "error_code"),
        elapsed_ms=_optional_int(payload, "elapsed_ms"),
    )


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"progress event missing required string field {key!r}")
    return value


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"progress event missing required integer field {key!r}")
    return value


def _optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _optional_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) else None
