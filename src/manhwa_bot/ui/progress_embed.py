"""Reusable Discord embed state for crawler-backed command progress."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import discord

ProgressSeverity = Literal["info", "warning", "error"]

_ACTIVE_SUFFIX = "..."
_MAX_DESCRIPTION_LENGTH = 4096
_MAX_MESSAGE_LENGTH = 240
_SENTENCE_PUNCTUATION = ".!?"


@dataclass(slots=True)
class _ProgressEvent:
    message: str
    severity: ProgressSeverity


@dataclass(slots=True)
class ProgressEmbedState:
    """Accumulates progress events and renders a single Discord embed."""

    command_name: str
    request_id: str
    max_visible_events: int = 10
    _events: list[_ProgressEvent] = field(default_factory=list, init=False, repr=False)

    def add(self, message: str, severity: ProgressSeverity = "info") -> None:
        self._events.append(
            _ProgressEvent(
                message=_normalize_message(message),
                severity=severity,
            )
        )

    def to_embed(self, *, final_error: bool = False) -> discord.Embed:
        visible_events = self._visible_events()
        latest_severity = self._events[-1].severity if self._events else "info"
        embed = discord.Embed(
            title=f"Running {self.command_name}",
            description=self._description(visible_events, final_error=final_error),
            colour=_colour_for(latest_severity, final_error=final_error),
        )
        embed.set_footer(text=f"Request ID: {self.request_id}")
        return embed

    def _visible_events(self) -> list[tuple[int | None, str]]:
        event_count = len(self._events)
        max_visible_events = max(1, self.max_visible_events)
        if event_count <= max_visible_events:
            return [(index, event.message) for index, event in enumerate(self._events, start=1)]

        tail_count = max(1, max_visible_events - 1)
        omitted_count = event_count - 1 - tail_count
        tail_start = event_count - tail_count + 1
        visible: list[tuple[int | None, str]] = [(1, self._events[0].message)]
        if omitted_count > 0:
            visible.append((None, f"... {omitted_count} earlier updates omitted."))
        visible.extend(
            (index, event.message)
            for index, event in enumerate(self._events[-tail_count:], start=tail_start)
        )
        return visible

    def _description(
        self,
        visible_events: list[tuple[int | None, str]],
        *,
        final_error: bool,
    ) -> str:
        lines: list[str] = []
        latest_number = len(self._events)
        for number, message in visible_events:
            if number is None:
                lines.append(message)
                continue

            rendered_message = message
            if not final_error and number == latest_number:
                rendered_message = _active_message(message)
            lines.append(f"{number}. {rendered_message}")
        return _bounded_description(lines)


def progress_event_message(event: object) -> tuple[str, ProgressSeverity]:
    """Convert crawler progress event-like objects into display text and severity."""

    title = _event_value(event, "title")
    detail = _event_value(event, "detail")
    status = _event_value(event, "status")

    message = title or "Crawler progress update"
    if detail:
        message = f"{message}: {detail}"

    return _normalize_message(message), _severity_for_status(status)


def _event_value(event: object, key: str) -> str | None:
    value: Any
    if isinstance(event, Mapping):
        value = event.get(key)
    else:
        value = getattr(event, key, None)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _bounded_description(lines: list[str]) -> str:
    description = "\n".join(lines)
    if len(description) <= _MAX_DESCRIPTION_LENGTH:
        return description

    marker = "... earlier visible updates truncated."
    kept_tail: list[str] = []
    for line in reversed(lines[1:]):
        candidate = [lines[0], marker, line, *kept_tail]
        if len("\n".join(candidate)) > _MAX_DESCRIPTION_LENGTH:
            break
        kept_tail.insert(0, line)

    bounded = "\n".join([lines[0], marker, *kept_tail])
    if len(bounded) <= _MAX_DESCRIPTION_LENGTH:
        return bounded
    return bounded[: _MAX_DESCRIPTION_LENGTH - len(_ACTIVE_SUFFIX)].rstrip() + _ACTIVE_SUFFIX


def _severity_for_status(status: str | None) -> ProgressSeverity:
    if status == "failed":
        return "error"
    if status == "retrying":
        return "warning"
    return "info"


def _colour_for(severity: ProgressSeverity, *, final_error: bool) -> discord.Colour:
    if final_error or severity == "error":
        return discord.Colour.red()
    if severity == "warning":
        return discord.Colour.gold()
    return discord.Colour.blurple()


def _normalize_message(message: str) -> str:
    normalized = re.sub(r"\s+", " ", message).strip()
    if not normalized:
        normalized = "Crawler progress update"
    if len(normalized) > _MAX_MESSAGE_LENGTH:
        normalized = normalized[: _MAX_MESSAGE_LENGTH - len(_ACTIVE_SUFFIX)].rstrip()
        normalized = normalized.rstrip(_SENTENCE_PUNCTUATION) + _ACTIVE_SUFFIX
    if normalized[-1] not in _SENTENCE_PUNCTUATION:
        normalized += "."
    return normalized


def _active_message(message: str) -> str:
    return message.rstrip(_SENTENCE_PUNCTUATION) + _ACTIVE_SUFFIX
