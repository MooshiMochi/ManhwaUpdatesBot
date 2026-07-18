"""Mirror WARNING+ log records to a Discord channel.

A :class:`DiscordLogHandler` buffers formatted records; an async pump task
started at bot setup drains the buffer and posts to the configured channel as
codeblocks. Records that fit go out verbatim (batched); oversize records are
summarised (header + traceback tail) with the full text attached as a file.

Feedback-loop safety: records from ``discord.*`` loggers and from this module
are never mirrored — an HTTP hiccup while posting a log message must not
generate more log messages to post. Those records still reach the rotating
``logs/error.log`` file handler.
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections import deque
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from .bot import ManhwaBot

_log = logging.getLogger(__name__)

_MESSAGE_LIMIT = 2000
_FENCE = "```"
# Room for the two fences + newlines inside the 2000-char message limit.
_BODY_LIMIT = _MESSAGE_LIMIT - (len(_FENCE) * 2 + 2)
_ATTACHMENT_NAME = "error-full.txt"
_EXCLUDED_LOGGER_PREFIXES = ("discord", __name__)


def _escape_fences(text: str) -> str:
    """Keep user/log content from closing our codeblock early."""
    return text.replace("```", "`​``")


def format_channel_payload(text: str) -> tuple[str, str | None]:
    """Render a log record for a Discord message.

    Returns ``(content, attachment_text)``. ``attachment_text`` is ``None``
    when the whole record fits in one codeblock; otherwise ``content`` holds
    the most important bit (header line + traceback tail) and the full record
    ships as a file attachment.
    """
    body = _escape_fences(text.strip("\n"))
    if len(body) <= _BODY_LIMIT:
        return f"{_FENCE}\n{body}\n{_FENCE}", None

    lines = [line for line in body.splitlines() if line.strip()]
    header = lines[0] if lines else body[:200]
    tail = lines[-1] if len(lines) > 1 else ""
    note = f"(full error attached as {_ATTACHMENT_NAME})"
    # Header first, then the final line (for tracebacks that's the actual
    # exception), each clamped so the summary always fits.
    budget = _BODY_LIMIT - len(note) - len("\n…\n\n") - len(tail[:400])
    summary = header[: max(200, budget)]
    parts = [summary, "…"]
    if tail and tail != header:
        parts.append(tail[:400])
    parts.append(note)
    content = f"{_FENCE}\n" + "\n".join(parts) + f"\n{_FENCE}"
    if len(content) > _MESSAGE_LIMIT:
        content = f"{_FENCE}\n{header[: _BODY_LIMIT - len(note) - 1]}\n{note}{_FENCE}"
    return content, text


class DiscordLogHandler(logging.Handler):
    """Buffers WARNING+ records for the async channel pump."""

    def __init__(self, *, maxlen: int = 500) -> None:
        super().__init__(level=logging.WARNING)
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")
        )
        self.buffer: deque[str] = deque(maxlen=maxlen)
        self._wakeup: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> asyncio.Event:
        self._loop = loop
        self._wakeup = asyncio.Event()
        return self._wakeup

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_EXCLUDED_LOGGER_PREFIXES):
            return
        try:
            self.buffer.append(self.format(record))
        except Exception:
            self.handleError(record)
            return
        loop, wakeup = self._loop, self._wakeup
        if loop is not None and wakeup is not None:
            try:
                loop.call_soon_threadsafe(wakeup.set)
            except RuntimeError:
                pass  # loop already closed; the buffer still holds the record


async def _resolve_channel(bot: ManhwaBot, channel_id: int) -> discord.abc.Messageable | None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.HTTPException:
            return None
    return channel if isinstance(channel, discord.abc.Messageable) else None


async def _pump(bot: ManhwaBot, handler: DiscordLogHandler, channel_id: int) -> None:
    await bot.wait_until_ready()
    wakeup = handler.bind(asyncio.get_running_loop())
    if handler.buffer:
        # Flush records buffered during startup, before the event existed.
        wakeup.set()
    channel = await _resolve_channel(bot, channel_id)
    if channel is None:
        _log.warning("error-log channel %s not found; Discord log mirror disabled", channel_id)
        return
    _log.info("mirroring WARNING+ logs to channel %s", channel_id)
    while True:
        await wakeup.wait()
        wakeup.clear()
        while handler.buffer:
            # Batch consecutive small records into one message.
            batch: list[str] = [handler.buffer.popleft()]
            while (
                handler.buffer
                and len(batch[0]) <= _BODY_LIMIT
                and len("\n".join([*batch, handler.buffer[0]])) <= _BODY_LIMIT
            ):
                batch.append(handler.buffer.popleft())
            content, attachment_text = format_channel_payload("\n".join(batch))
            kwargs: dict = {
                "content": content,
                "allowed_mentions": discord.AllowedMentions.none(),
            }
            if attachment_text is not None:
                kwargs["file"] = discord.File(
                    io.BytesIO(attachment_text.encode("utf-8")), filename=_ATTACHMENT_NAME
                )
            try:
                await channel.send(**kwargs)
            except discord.HTTPException as exc:
                # Log to file only (this module is excluded from the mirror).
                _log.warning("failed to mirror log record to channel: %s", exc)
            await asyncio.sleep(1.0)


def setup_discord_logging(bot: ManhwaBot) -> DiscordLogHandler | None:
    """Attach the mirror handler and start its pump. No-op when unconfigured."""
    channel_id = int(getattr(bot.config.bot, "error_log_channel_id", 0) or 0)
    if channel_id <= 0:
        return None
    handler = DiscordLogHandler()
    logging.getLogger().addHandler(handler)
    task = asyncio.get_running_loop().create_task(
        _pump(bot, handler, channel_id), name="discord-log-pump"
    )
    bot.discord_log_task = task
    return handler
