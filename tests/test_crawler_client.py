"""CrawlerClient request/response correlation, push routing, disconnect handling.

Uses a tiny in-process aiohttp WS server as a fake crawler.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import WSMsgType, web

from manhwa_bot.config import CrawlerConfig
from manhwa_bot.crawler.client import CrawlerClient
from manhwa_bot.crawler.errors import CrawlerError, RequestTimeout
from manhwa_bot.crawler.progress import CrawlerProgressEvent, parse_progress_event


def _config(ws_url: str, *, request_timeout: float = 5.0) -> CrawlerConfig:
    return CrawlerConfig(
        ws_url=ws_url,
        http_base_url="http://unused",
        request_timeout_seconds=request_timeout,
        reconnect_initial_delay_seconds=0.05,
        reconnect_max_delay_seconds=0.2,
        reconnect_jitter_seconds=0.0,
        consumer_key="test",
        api_key="test-key",
    )


def test_parse_progress_event_tolerates_missing_and_unknown_optional_fields() -> None:
    event = parse_progress_event(
        {
            "type": "request_progress",
            "request_id": "req-1",
            "event": "scrape_retry",
            "sequence": 2,
            "title": "Retrying scrape",
            "status": "retrying",
            "retry_attempt": 1,
            "unknown": {"ignored": True},
        }
    )

    assert event.request_id == "req-1"
    assert event.event == "scrape_retry"
    assert event.sequence == 2
    assert event.title == "Retrying scrape"
    assert event.status == "retrying"
    assert event.retry_attempt == 1
    assert event.detail is None


def test_parse_progress_event_rejects_missing_required_fields() -> None:
    base_payload = {
        "type": "request_progress",
        "request_id": "req-1",
        "event": "scrape_started",
        "sequence": 1,
        "title": "Starting scrape",
        "status": "running",
    }
    for key in ("request_id", "event", "sequence", "title", "status"):
        payload = dict(base_payload)
        payload.pop(key)
        with pytest.raises(ValueError):
            parse_progress_event(payload)


async def _start_server(handler) -> tuple[web.AppRunner, str]:
    app = web.Application()
    app.router.add_get("/ws", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    return runner, f"ws://127.0.0.1:{port}/ws"


def test_request_response_correlation() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": payload["request_id"],
                                "type": f"{payload['type']}_result",
                                "ok": True,
                                "data": {"echo": payload.get("query")},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url))
        try:
            await client.start()
            data = await client.request("search", query="demon slayer")
            assert data == {"echo": "demon slayer"}
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_error_envelope_raises_crawler_error() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": payload["request_id"],
                                "type": f"{payload['type']}_result",
                                "ok": False,
                                "error": {"code": "rate_limited", "message": "slow down"},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url))
        try:
            await client.start()
            with pytest.raises(CrawlerError) as exc_info:
                await client.request("search", query="x")
            assert exc_info.value.code == "rate_limited"
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_request_timeout() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for _ in ws:
                pass  # never reply
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url, request_timeout=0.2))
        try:
            await client.start()
            with pytest.raises(RequestTimeout):
                await client.request("search", query="x")
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_push_handler_routing() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_str(
                json.dumps(
                    {
                        "request_id": "push-1",
                        "type": "notification_event",
                        "ok": True,
                        "data": {"notification": {"id": 42}},
                    }
                )
            )
            async for _ in ws:
                pass
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url))
        received: list[dict] = []

        async def on_event(payload: dict) -> None:
            received.append(payload)

        client.on_push("notification_event", on_event)
        try:
            await client.start()
            for _ in range(20):
                if received:
                    break
                await asyncio.sleep(0.05)
            assert received, "expected a notification_event push"
            assert received[0]["data"]["notification"]["id"] == 42
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_request_with_progress_routes_events_before_final_result() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    assert "on_progress" not in payload
                    request_id = payload["request_id"]
                    for sequence, event in enumerate(
                        ("scrape_started", "scrape_succeeded"), start=1
                    ):
                        await ws.send_str(
                            json.dumps(
                                {
                                    "type": "request_progress",
                                    "request_id": request_id,
                                    "event": event,
                                    "sequence": sequence,
                                    "title": event.replace("_", " "),
                                    "status": "running" if sequence == 1 else "succeeded",
                                }
                            )
                        )
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": request_id,
                                "type": f"{payload['type']}_result",
                                "ok": True,
                                "data": {"series": payload.get("url_name")},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url))
        received: list[CrawlerProgressEvent] = []

        async def on_progress(event: CrawlerProgressEvent) -> None:
            received.append(event)

        try:
            await client.start()
            data = await client.request_with_progress(
                "scrape_series",
                url_name="solo-leveling",
                on_progress=on_progress,
            )
            assert [event.sequence for event in received] == [1, 2]
            assert [event.event for event in received] == ["scrape_started", "scrape_succeeded"]
            assert data == {"series": "solo-leveling"}
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_unrelated_progress_is_ignored_and_request_still_resolves() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    await ws.send_str(
                        json.dumps(
                            {
                                "type": "request_progress",
                                "request_id": "other-request",
                                "event": "scrape_started",
                                "sequence": 1,
                                "title": "Starting scrape",
                                "status": "running",
                            }
                        )
                    )
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": payload["request_id"],
                                "type": f"{payload['type']}_result",
                                "ok": True,
                                "data": {"ok": True},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url))
        received: list[CrawlerProgressEvent] = []

        try:
            await client.start()
            data = await client.request_with_progress(
                "scrape_series",
                progress_callback=received.append,
            )
            assert received == []
            assert data == {"ok": True}
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_slow_progress_callback_does_not_timeout_request() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    await ws.send_str(
                        json.dumps(
                            {
                                "type": "request_progress",
                                "request_id": payload["request_id"],
                                "event": "scrape_started",
                                "sequence": 1,
                                "title": "Starting scrape",
                                "status": "running",
                            }
                        )
                    )
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": payload["request_id"],
                                "type": f"{payload['type']}_result",
                                "ok": True,
                                "data": {"done": True},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url, request_timeout=0.1))
        callback_started = asyncio.Event()

        async def on_progress(_event: CrawlerProgressEvent) -> None:
            callback_started.set()
            await asyncio.sleep(0.3)

        try:
            await client.start()
            data = await client.request_with_progress("scrape_series", on_progress=on_progress)
            assert data == {"done": True}
            await asyncio.wait_for(callback_started.wait(), timeout=0.2)
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_progress_callbacks_complete_in_sequence_order() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    for sequence in (1, 2):
                        await ws.send_str(
                            json.dumps(
                                {
                                    "type": "request_progress",
                                    "request_id": payload["request_id"],
                                    "event": "scrape_started",
                                    "sequence": sequence,
                                    "title": f"Progress {sequence}",
                                    "status": "running",
                                }
                            )
                        )
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": payload["request_id"],
                                "type": f"{payload['type']}_result",
                                "ok": True,
                                "data": {"done": True},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url))
        completed: list[int] = []
        all_done = asyncio.Event()

        async def on_progress(event: CrawlerProgressEvent) -> None:
            if event.sequence == 1:
                await asyncio.sleep(0.1)
            completed.append(event.sequence)
            if len(completed) == 2:
                all_done.set()

        try:
            await client.start()
            data = await client.request_with_progress("scrape_series", on_progress=on_progress)
            assert data == {"done": True}
            await asyncio.wait_for(all_done.wait(), timeout=0.3)
            assert completed == [1, 2]
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_request_with_progress_waits_for_queued_progress_callbacks() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    await ws.send_str(
                        json.dumps(
                            {
                                "type": "request_progress",
                                "request_id": payload["request_id"],
                                "event": "scrape_started",
                                "sequence": 1,
                                "title": "Starting scrape",
                                "status": "running",
                            }
                        )
                    )
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": payload["request_id"],
                                "type": f"{payload['type']}_result",
                                "ok": True,
                                "data": {"done": True},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url, request_timeout=0.1))
        completed: list[int] = []

        async def on_progress(event: CrawlerProgressEvent) -> None:
            await asyncio.sleep(0.05)
            completed.append(event.sequence)

        try:
            await client.start()
            data = await client.request_with_progress("scrape_series", on_progress=on_progress)
            assert data == {"done": True}
            assert completed == [1]
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_cancelled_progress_callback_does_not_fail_request_or_disconnect() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    await ws.send_str(
                        json.dumps(
                            {
                                "type": "request_progress",
                                "request_id": payload["request_id"],
                                "event": "scrape_started",
                                "sequence": 1,
                                "title": "Starting scrape",
                                "status": "running",
                            }
                        )
                    )
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": payload["request_id"],
                                "type": f"{payload['type']}_result",
                                "ok": True,
                                "data": {"first": True},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url))
        callback_started = asyncio.Event()

        async def on_progress(_event: CrawlerProgressEvent) -> None:
            callback_started.set()
            raise asyncio.CancelledError

        try:
            await client.start()
            data = await client.request_with_progress("scrape_series", on_progress=on_progress)
            assert data == {"first": True}
            await asyncio.wait_for(callback_started.wait(), timeout=0.2)
            assert client.connected
            second = await client.request("search")
            assert second == {"first": True}
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_stop_cancels_and_drains_progress_callback_tasks() -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    await ws.send_str(
                        json.dumps(
                            {
                                "type": "request_progress",
                                "request_id": payload["request_id"],
                                "event": "scrape_started",
                                "sequence": 1,
                                "title": "Starting scrape",
                                "status": "running",
                            }
                        )
                    )
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": payload["request_id"],
                                "type": f"{payload['type']}_result",
                                "ok": True,
                                "data": {"done": True},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url))
        callback_started = asyncio.Event()
        callback_cancelled = asyncio.Event()
        callback_completed = asyncio.Event()
        stopped = False

        async def on_progress(_event: CrawlerProgressEvent) -> None:
            callback_started.set()
            try:
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                callback_cancelled.set()
                raise
            callback_completed.set()

        try:
            await client.start()
            request_task = asyncio.create_task(
                client.request_with_progress("scrape_series", on_progress=on_progress)
            )
            await asyncio.wait_for(callback_started.wait(), timeout=0.2)
            await client.stop()
            stopped = True
            await asyncio.gather(request_task, return_exceptions=True)
            assert callback_cancelled.is_set()
            await asyncio.sleep(0.25)
            assert not callback_completed.is_set()
        finally:
            if not stopped:
                await client.stop()
            await runner.cleanup()

    asyncio.run(_run())


def test_progress_callback_failure_is_logged_and_request_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _run() -> None:
        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    await ws.send_str(
                        json.dumps(
                            {
                                "type": "request_progress",
                                "request_id": payload["request_id"],
                                "event": "scrape_failed",
                                "sequence": 1,
                                "title": "Scrape failed",
                                "status": "failed",
                                "error_code": "boom",
                            }
                        )
                    )
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": payload["request_id"],
                                "type": f"{payload['type']}_result",
                                "ok": True,
                                "data": {"continued": True},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        client = CrawlerClient(_config(url))

        def on_progress(_event: CrawlerProgressEvent) -> None:
            raise RuntimeError("callback exploded")

        try:
            await client.start()
            data = await client.request_with_progress(
                "scrape_series",
                progress_callback=on_progress,
            )
            assert data == {"continued": True}
            assert "crawler progress callback failed" in caplog.text
        finally:
            await client.stop()
            await runner.cleanup()

    asyncio.run(_run())
