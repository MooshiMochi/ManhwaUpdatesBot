"""Discord log mirror: message formatting and feedback-loop safety."""

from __future__ import annotations

import logging

from manhwa_bot.discord_log import (
    _ATTACHMENT_NAME,
    _MESSAGE_LIMIT,
    DiscordLogHandler,
    format_channel_payload,
)


def _record(name: str, msg: str, level: int = logging.WARNING) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 0, msg, None, None)


def test_short_record_fits_in_one_codeblock() -> None:
    content, attachment = format_channel_payload("boom: something broke")
    assert attachment is None
    assert content.startswith("```\n")
    assert content.endswith("\n```")
    assert "boom: something broke" in content
    assert len(content) <= _MESSAGE_LIMIT


def test_oversize_record_summarised_with_attachment() -> None:
    header = "2026-07-18 [ERROR] manhwa_bot.cogs.updates: dispatch blew up"
    traceback_body = "\n".join(f'  File "x.py", line {i}, in f{i}' for i in range(200))
    tail = "discord.errors.HTTPException: 400 Bad Request (error code: 50035)"
    full = f"{header}\n{traceback_body}\n{tail}"

    content, attachment = format_channel_payload(full)

    assert attachment == full
    assert len(content) <= _MESSAGE_LIMIT
    # The "most important bit": the header and the actual exception line.
    assert header[:100] in content
    assert tail in content
    assert _ATTACHMENT_NAME in content


def test_fences_inside_records_cannot_break_the_codeblock() -> None:
    content, _ = format_channel_payload("evil ``` payload ``` here")
    # The interior of the message must not contain a bare closing fence.
    interior = content.removeprefix("```\n").removesuffix("\n```")
    assert "```" not in interior


def test_every_summary_stays_under_the_limit() -> None:
    for size in (1990, 1993, 2500, 5000, 100_000):
        content, _ = format_channel_payload("x" * size)
        assert len(content) <= _MESSAGE_LIMIT, f"size={size} produced {len(content)}"


def test_handler_buffers_warnings_and_skips_discord_loggers() -> None:
    handler = DiscordLogHandler()
    handler.emit(_record("manhwa_bot.cogs.updates", "guild send failed"))
    handler.emit(_record("discord.http", "429 slow down"))
    handler.emit(_record("manhwa_bot.discord_log", "failed to mirror"))
    assert len(handler.buffer) == 1
    assert "guild send failed" in handler.buffer[0]
