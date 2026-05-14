"""Components V2 replacement for ProgressEmbedState.

Renders crawler-backed command progress as a single LayoutView that the caller
edits in place. Severity drives the Container accent colour; events render as a
numbered TextDisplay with the same tail-follow logic as the legacy embed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import discord

from .. import emojis
from .base import BaseLayoutView, footer_section, severity_accent

ProgressSeverity = Literal["info", "warning", "error"]

_ACTIVE_SUFFIX = "..."
_MAX_TEXT_LENGTH = 3800
_MAX_MESSAGE_LENGTH = 240
_SENTENCE_PUNCTUATION = ".!?"


@dataclass(slots=True)
class _ProgressEvent:
    message: str
    severity: ProgressSeverity


@dataclass(slots=True)
class ProgressLayoutState:
    """Accumulates progress events and renders a LayoutView per snapshot."""

    command_name: str
    request_id: str
    max_visible_events: int = 10
    bot: discord.Client | None = None
    _events: list[_ProgressEvent] = field(default_factory=list, init=False, repr=False)

    def add(self, message: str, severity: ProgressSeverity = "info") -> None:
        self._events.append(
            _ProgressEvent(
                message=_normalize_message(message),
                severity=severity,
            )
        )

    def to_view(self, *, final_error: bool = False) -> discord.ui.LayoutView:
        visible_events = self._visible_events()
        latest_severity: ProgressSeverity = self._events[-1].severity if self._events else "info"
        accent_level = (
            "error"
            if final_error or latest_severity == "error"
            else ("warning" if latest_severity == "warning" else "info")
        )
        glyph = (
            emojis.ERROR
            if accent_level == "error"
            else emojis.WARNING
            if accent_level == "warning"
            else emojis.LOADING
        )
        body = self._body_text(visible_events, final_error=final_error)

        container = discord.ui.Container(
            discord.ui.TextDisplay(f"## {glyph}  Running `{self.command_name}`"),
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay(body),
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
            footer_section(self.bot, extra=f"req: {self.request_id}"),
            accent_colour=severity_accent(accent_level),  # type: ignore[arg-type]
        )

        view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
        view.add_item(container)
        return view

    def _visible_events(self) -> list[tuple[int | None, str]]:
        event_count = len(self._events)
        max_visible_events = max(1, self.max_visible_events)
        if event_count <= max_visible_events:
            return [(index, ev.message) for index, ev in enumerate(self._events, start=1)]

        tail_count = max(1, max_visible_events - 1)
        omitted_count = event_count - 1 - tail_count
        tail_start = event_count - tail_count + 1
        visible: list[tuple[int | None, str]] = [(1, self._events[0].message)]
        if omitted_count > 0:
            visible.append((None, f"… {omitted_count} earlier updates omitted."))
        visible.extend(
            (index, ev.message)
            for index, ev in enumerate(self._events[-tail_count:], start=tail_start)
        )
        return visible

    def _body_text(
        self,
        visible_events: list[tuple[int | None, str]],
        *,
        final_error: bool,
    ) -> str:
        lines: list[str] = []
        latest_number = len(self._events)
        for number, message in visible_events:
            if number is None:
                lines.append(f"*{message}*")
                continue

            rendered = message
            if not final_error and number == latest_number:
                rendered = _active_message(message)
            lines.append(f"**{number}.** {rendered}")
        return _bounded_text(lines)


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


def _bounded_text(lines: list[str]) -> str:
    text = "\n".join(lines)
    if len(text) <= _MAX_TEXT_LENGTH:
        return text

    marker = "*… earlier updates truncated.*"
    kept_tail: list[str] = []
    for line in reversed(lines[1:]):
        candidate = [lines[0], marker, line, *kept_tail]
        if len("\n".join(candidate)) > _MAX_TEXT_LENGTH:
            break
        kept_tail.insert(0, line)

    bounded = "\n".join([lines[0], marker, *kept_tail])
    if len(bounded) <= _MAX_TEXT_LENGTH:
        return bounded
    return bounded[: _MAX_TEXT_LENGTH - len(_ACTIVE_SUFFIX)].rstrip() + _ACTIVE_SUFFIX


def _severity_for_status(status: str | None) -> ProgressSeverity:
    if status == "failed":
        return "error"
    if status == "retrying":
        return "warning"
    return "info"


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
