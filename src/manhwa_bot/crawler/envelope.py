"""TypedDicts for crawler WS envelopes — useful for type checking and docs."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class ErrorPayload(TypedDict):
    code: str
    message: str


class ResponseEnvelope(TypedDict):
    """Server → client correlated response."""

    request_id: str
    type: str
    ok: bool
    data: NotRequired[dict[str, Any]]
    error: NotRequired[ErrorPayload]


class PushEnvelope(TypedDict):
    """Server → client unsolicited event (e.g. ``notification_event``)."""

    request_id: str
    type: str
    ok: bool
    data: dict[str, Any]


class NotificationPayload(TypedDict, total=False):
    event: str
    website_key: str
    url_name: str
    series_title: str
    series_url: str
    chapter: dict[str, Any]


class NotificationRecord(TypedDict, total=False):
    id: int
    website_key: str
    url_name: str
    chapter_index: int
    payload: NotificationPayload
    created_at: str
