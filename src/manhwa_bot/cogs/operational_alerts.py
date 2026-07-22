"""Private delivery of crawler operational alerts to the bot error log."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

from ..crawler.notifications import NotificationConsumer
from ..db.consumer_state import ConsumerStateStore

if TYPE_CHECKING:
    from ..bot import ManhwaBot


_log = logging.getLogger(__name__)


class OperationalAlertCog(commands.Cog, name="Operational Alerts"):
    """Replay and deliver crawler incidents to the single private ops channel."""

    def __init__(self, bot: ManhwaBot) -> None:
        self.bot = bot
        self._store = ConsumerStateStore(bot.db)
        self._consumer: NotificationConsumer | None = None

    async def cog_load(self) -> None:
        self._consumer = NotificationConsumer(
            client=self.bot.crawler,
            store=self._store,
            consumer_key=f"{self.bot.config.crawler.consumer_key}:operational-alerts",
            dispatch=self.dispatch,
            push_type="operational_alert_event",
            list_request_type="operational_alerts_list",
            ack_request_type="operational_alerts_ack",
            records_key="alerts",
            push_record_key="alert",
            last_id_key="last_alert_id",
        )
        await self._consumer.start()

    async def cog_unload(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None

    async def dispatch(self, record: dict[str, Any]) -> None:
        """Send a crawler alert, raising on failure so the stream is replayed."""
        channel_id = int(self.bot.config.bot.error_log_channel_id or 0)
        if channel_id <= 0:
            raise RuntimeError("bot.error_log_channel_id is required for operational alerts")

        channel = await _resolve_messageable_channel(self.bot, channel_id)
        if channel is None:
            raise RuntimeError(f"private error-log channel {channel_id} is unavailable")

        await channel.send(
            content=_format_operational_alert(record),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def _resolve_messageable_channel(
    bot: ManhwaBot,
    channel_id: int,
) -> discord.abc.Messageable | None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.Forbidden, discord.HTTPException, discord.NotFound:
            _log.exception("could not resolve private operational-alert channel %s", channel_id)
            return None
    return channel if isinstance(channel, discord.abc.Messageable) else None


def _format_operational_alert(record: Mapping[str, Any]) -> str:
    payload = record.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    details = payload.get("details")
    details = details if isinstance(details, Mapping) else {}

    event = str(record.get("event") or payload.get("event") or "opened").lower()
    status = "recovered" if event == "recovered" else "opened"
    website = str(record.get("website_key") or payload.get("website_key") or "unknown")
    source = str(record.get("source") or payload.get("source") or "unknown")
    issue_code = str(record.get("issue_code") or payload.get("issue_code") or "unknown")
    error = str(payload.get("error_message") or "No error message supplied")

    lines = [
        f"Crawler incident {status}",
        f"website: `{website}`",
        f"source: `{source}`",
        f"issue: `{issue_code}`",
        f"error: {error}",
    ]

    crawl_job_id = details.get("crawl_job_id")
    if crawl_job_id is not None:
        lines.append(f"crawl job: {crawl_job_id}")

    extraction = details.get("front_page_extraction")
    if isinstance(extraction, Mapping):
        rows_seen = extraction.get("rows_seen")
        rows_emitted = extraction.get("rows_emitted")
        if rows_seen is not None or rows_emitted is not None:
            lines.append(f"front page: rows_seen={rows_seen}, rows_emitted={rows_emitted}")

    if status == "recovered":
        duration = payload.get("duration_seconds")
        if duration is not None:
            try:
                lines.append(f"duration: {round(float(duration))}s")
            except TypeError, ValueError:
                pass

    occurrence_count = payload.get("occurrence_count")
    if occurrence_count is not None:
        lines.append(f"observations: {occurrence_count}")

    return "\n".join(lines)[:1900]


async def setup(bot: ManhwaBot) -> None:
    await bot.add_cog(OperationalAlertCog(bot))
