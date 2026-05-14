"""Progress event parsing for crawler WebSocket requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_TOP_LEVEL_PROGRESS_KEYS = frozenset(
    {
        "event",
        "sequence",
        "title",
        "detail",
        "status",
        "retry_attempt",
        "max_retries",
        "error_code",
        "elapsed_ms",
    }
)

_CRAWLER_DATA_PROGRESS_KEYS = frozenset({"stage", "message", "severity"})


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
    data = payload.get("data")
    if (
        not _has_top_level_progress_keys(payload)
        and isinstance(data, Mapping)
        and _has_crawler_data_progress_keys(data)
    ):
        return _parse_crawler_data_progress_event(request_id, payload, data)

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


def _has_top_level_progress_keys(payload: Mapping[str, Any]) -> bool:
    return any(key in payload for key in _TOP_LEVEL_PROGRESS_KEYS)


def _has_crawler_data_progress_keys(data: Mapping[str, Any]) -> bool:
    return any(key in data for key in _CRAWLER_DATA_PROGRESS_KEYS)


def _parse_crawler_data_progress_event(
    request_id: str,
    payload: Mapping[str, Any],
    data: Mapping[str, Any],
) -> CrawlerProgressEvent:
    event = _required_str(data, "stage")
    title = _optional_str(data, "message") or event
    return CrawlerProgressEvent(
        request_id=request_id,
        event=event,
        sequence=_optional_int(payload, "sequence") or _optional_int(data, "sequence") or 0,
        title=title,
        detail=_crawler_data_detail(data),
        status=_crawler_data_status(event, _optional_str(data, "severity")),
        retry_attempt=_optional_int(data, "attempt"),
        max_retries=_optional_int(data, "max_attempts"),
        error_code=_optional_str(data, "error_code"),
        elapsed_ms=_optional_int(data, "elapsed_ms"),
    )


def _crawler_data_status(stage: str, severity: str | None) -> str:
    if severity == "error":
        return "failed"
    if severity == "warning" or stage == "retrying":
        return "retrying"
    return "running"


def _crawler_data_detail(data: Mapping[str, Any]) -> str | None:
    parts: list[str] = []
    attempt = _optional_int(data, "attempt")
    max_attempts = _optional_int(data, "max_attempts")
    if attempt is not None and max_attempts is not None:
        parts.append(f"Attempt {attempt}/{max_attempts}")
    elif attempt is not None:
        parts.append(f"Attempt {attempt}")

    website_key = _optional_str(data, "website_key")
    if website_key is not None:
        parts.append(website_key)

    return " - ".join(parts) if parts else None


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
