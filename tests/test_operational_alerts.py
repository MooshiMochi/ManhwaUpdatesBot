from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from manhwa_bot.cogs.operational_alerts import OperationalAlertCog
from manhwa_bot.crawler.notifications import NotificationConsumer


def _record(*, event: str = "opened") -> dict:
    return {
        "id": 44,
        "website_key": "asura",
        "source": "main",
        "event": event,
        "issue_code": "selector_error",
        "fingerprint": "abc123",
        "payload": {
            "event": event,
            "website_key": "asura",
            "source": "main",
            "issue_code": "selector_error",
            "error_message": "front-page selector returned zero rows",
            "occurrence_count": 2,
            "duration_seconds": 75.0,
            "details": {
                "crawl_job_id": 88,
                "front_page_extraction": {"rows_seen": 0, "rows_emitted": 0},
            },
        },
        "created_at": "2026-07-22T12:00:00+00:00",
    }


def _bot(channel: discord.abc.Messageable | None) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            bot=SimpleNamespace(error_log_channel_id=123),
            crawler=SimpleNamespace(consumer_key="manhwa-bot"),
        ),
        db=object(),
        crawler=SimpleNamespace(),
        get_channel=MagicMock(return_value=channel),
        fetch_channel=AsyncMock(),
    )


def _messageable_channel() -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    return channel


def test_opened_alert_sends_only_to_private_error_log_channel() -> None:
    async def _run() -> None:
        channel = _messageable_channel()
        bot = _bot(channel)
        cog = OperationalAlertCog(bot)  # type: ignore[arg-type]

        await cog.dispatch(_record())

        bot.get_channel.assert_called_once_with(123)
        bot.fetch_channel.assert_not_awaited()
        assert channel.send.await_count == 1
        kwargs = channel.send.await_args.kwargs
        mentions = kwargs["allowed_mentions"]
        assert mentions.everyone is False
        assert mentions.users is False
        assert mentions.roles is False
        assert mentions.replied_user is False
        assert "opened" in kwargs["content"]
        assert "asura" in kwargs["content"]
        assert "crawl job: 88" in kwargs["content"]

    asyncio.run(_run())


def test_recovered_alert_includes_incident_duration() -> None:
    async def _run() -> None:
        channel = _messageable_channel()
        cog = OperationalAlertCog(_bot(channel))  # type: ignore[arg-type]

        await cog.dispatch(_record(event="recovered"))

        content = channel.send.await_args.kwargs["content"]
        assert "recovered" in content
        assert "75s" in content
        assert "observations: 2" in content

    asyncio.run(_run())


def test_delivery_failure_raises_so_alert_is_not_acknowledged() -> None:
    async def _run() -> None:
        channel = _messageable_channel()
        channel.send.side_effect = discord.HTTPException(MagicMock(status=500), "send failed")
        cog = OperationalAlertCog(_bot(channel))  # type: ignore[arg-type]

        with pytest.raises(discord.HTTPException):
            await cog.dispatch(_record())

    asyncio.run(_run())


def test_operational_consumer_registers_the_dedicated_stream_protocol() -> None:
    async def _run() -> None:
        client = SimpleNamespace(
            connected=False,
            on_push=MagicMock(),
            on_connect=MagicMock(),
        )
        store = SimpleNamespace(get_last_acked=AsyncMock(return_value=0))

        async def _dispatch(record: dict) -> None:
            del record

        consumer = NotificationConsumer(
            client=client,
            store=store,
            consumer_key="manhwa-bot:operational-alerts",
            dispatch=_dispatch,
            push_type="operational_alert_event",
            list_request_type="operational_alerts_list",
            ack_request_type="operational_alerts_ack",
            records_key="alerts",
            push_record_key="alert",
            last_id_key="last_alert_id",
        )
        await consumer.start()

        client.on_push.assert_called_once_with("operational_alert_event", consumer._on_push)
        client.on_connect.assert_called_once_with(consumer._on_connect)

    asyncio.run(_run())
