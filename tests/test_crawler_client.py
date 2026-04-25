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
