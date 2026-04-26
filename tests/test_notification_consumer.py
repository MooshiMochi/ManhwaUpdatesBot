"""NotificationConsumer catch-up + live-push handoff + reconnect tests.

Uses a tiny in-process aiohttp WS server as a fake crawler — same pattern as
``test_crawler_client.py`` — paired with a real ``ConsumerStateStore`` against
a temp aiosqlite database.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from aiohttp import WSMsgType, web

from manhwa_bot.config import CrawlerConfig
from manhwa_bot.crawler.client import CrawlerClient
from manhwa_bot.crawler.notifications import NotificationConsumer
from manhwa_bot.db.consumer_state import ConsumerStateStore
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool


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


async def _open_db() -> tuple[DbPool, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "bot.db"
    pool = await DbPool.open(str(db_path))
    await apply_pending(pool)
    return pool, tmp


async def _start_server(handler) -> tuple[web.AppRunner, str]:
    app = web.Application()
    app.router.add_get("/ws", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    return runner, f"ws://127.0.0.1:{port}/ws"


def _record(rid: int, *, website_key: str = "comick", url_name: str = "demo") -> dict:
    return {
        "id": rid,
        "website_key": website_key,
        "url_name": url_name,
        "chapter_index": rid,
        "payload": {
            "event": "new_chapter",
            "website_key": website_key,
            "url_name": url_name,
            "series_title": f"Series {rid}",
            "series_url": f"https://example.com/{url_name}",
            "chapter": {
                "index": rid,
                "name": f"Chapter {rid}",
                "url": f"https://example.com/{url_name}/{rid}",
                "is_premium": False,
            },
        },
        "created_at": "2026-04-26T00:00:00+00:00",
    }


def _make_handler(scripted_pages: list[list[dict]], *, ack_log: list[int]):
    """Server that replies to each notifications_list with the next scripted page."""
    page_iter = iter(scripted_pages)

    async def handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            payload = json.loads(msg.data)
            mtype = payload.get("type")
            rid = payload["request_id"]
            if mtype == "notifications_list":
                try:
                    page = next(page_iter)
                except StopIteration:
                    page = []
                await ws.send_str(
                    json.dumps(
                        {
                            "request_id": rid,
                            "type": "notifications_list_result",
                            "ok": True,
                            "data": {
                                "notifications": page,
                                "last_notification_id": page[-1]["id"] if page else None,
                                "consumer_offset": None,
                            },
                        }
                    )
                )
            elif mtype == "notifications_ack":
                ack_log.append(int(payload["last_notification_id"]))
                await ws.send_str(
                    json.dumps(
                        {
                            "request_id": rid,
                            "type": "notifications_ack_result",
                            "ok": True,
                            "data": {"acknowledged_to": int(payload["last_notification_id"])},
                        }
                    )
                )
            else:
                await ws.send_str(
                    json.dumps(
                        {
                            "request_id": rid,
                            "type": f"{mtype}_result",
                            "ok": True,
                            "data": {},
                        }
                    )
                )
        return ws

    return handler


def test_catchup_replays_in_order_and_acks() -> None:
    async def _run() -> None:
        ack_log: list[int] = []
        handler = _make_handler([[_record(11), _record(12), _record(13)], []], ack_log=ack_log)
        runner, url = await _start_server(handler)
        pool, tmp = await _open_db()
        client = CrawlerClient(_config(url))
        dispatched: list[int] = []

        async def dispatch(record: dict) -> None:
            dispatched.append(int(record["id"]))

        consumer = NotificationConsumer(
            client=client,
            store=ConsumerStateStore(pool),
            consumer_key="test",
            dispatch=dispatch,
        )
        try:
            await client.start()
            await consumer.start()
            for _ in range(40):
                if dispatched and not consumer.catching_up:
                    break
                await asyncio.sleep(0.05)
            assert dispatched == [11, 12, 13]
            assert consumer.last_acked == 13
            assert ack_log[-1] == 13
            stored = await ConsumerStateStore(pool).get_last_acked("test")
            assert stored == 13
        finally:
            await consumer.stop()
            await client.stop()
            await pool.close()
            tmp.cleanup()
            await runner.cleanup()

    asyncio.run(_run())


def test_paginates_until_short_batch() -> None:
    async def _run() -> None:
        page1 = [_record(i) for i in range(1, 201)]  # 200 records
        page2 = [_record(i) for i in range(201, 251)]  # 50 records
        ack_log: list[int] = []
        handler = _make_handler([page1, page2, []], ack_log=ack_log)
        runner, url = await _start_server(handler)
        pool, tmp = await _open_db()
        client = CrawlerClient(_config(url))
        dispatched: list[int] = []

        async def dispatch(record: dict) -> None:
            dispatched.append(int(record["id"]))

        consumer = NotificationConsumer(
            client=client,
            store=ConsumerStateStore(pool),
            consumer_key="test",
            dispatch=dispatch,
        )
        try:
            await client.start()
            await consumer.start()
            for _ in range(80):
                if len(dispatched) >= 250 and not consumer.catching_up:
                    break
                await asyncio.sleep(0.05)
            assert dispatched == list(range(1, 251))
            assert consumer.last_acked == 250
            assert ack_log[-1] == 250
        finally:
            await consumer.stop()
            await client.stop()
            await pool.close()
            tmp.cleanup()
            await runner.cleanup()

    asyncio.run(_run())


def test_live_push_during_catchup_is_queued_then_drained() -> None:
    """A live push that arrives while catch-up is in flight must run AFTER catch-up."""

    async def _run() -> None:
        gate = asyncio.Event()
        ack_log: list[int] = []
        # Page sequence: stalled list_5, then empty.
        scripted = [[_record(5)], []]

        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            page_iter = iter(scripted)

            async def drive_push() -> None:
                # Wait for the first list to arrive, then push id=6 BEFORE replying.
                await gate.wait()
                await ws.send_str(
                    json.dumps(
                        {
                            "request_id": "push-6",
                            "type": "notification_event",
                            "ok": True,
                            "data": {"notification": _record(6)},
                        }
                    )
                )
                # Brief delay, then reply to the pending list with [5].
                await asyncio.sleep(0.05)
                pending_request_id = pending_holder["rid"]
                page = next(page_iter)
                await ws.send_str(
                    json.dumps(
                        {
                            "request_id": pending_request_id,
                            "type": "notifications_list_result",
                            "ok": True,
                            "data": {
                                "notifications": page,
                                "last_notification_id": page[-1]["id"] if page else None,
                                "consumer_offset": None,
                            },
                        }
                    )
                )

            pending_holder = {"rid": ""}
            push_task = asyncio.create_task(drive_push())
            try:
                async for msg in ws:
                    if msg.type != WSMsgType.TEXT:
                        continue
                    payload = json.loads(msg.data)
                    mtype = payload.get("type")
                    rid = payload["request_id"]
                    if mtype == "notifications_list":
                        if not gate.is_set():
                            pending_holder["rid"] = rid
                            gate.set()
                            continue
                        # Subsequent list calls reply immediately (empty page).
                        try:
                            page = next(page_iter)
                        except StopIteration:
                            page = []
                        await ws.send_str(
                            json.dumps(
                                {
                                    "request_id": rid,
                                    "type": "notifications_list_result",
                                    "ok": True,
                                    "data": {
                                        "notifications": page,
                                        "last_notification_id": page[-1]["id"] if page else None,
                                        "consumer_offset": None,
                                    },
                                }
                            )
                        )
                    elif mtype == "notifications_ack":
                        ack_log.append(int(payload["last_notification_id"]))
                        await ws.send_str(
                            json.dumps(
                                {
                                    "request_id": rid,
                                    "type": "notifications_ack_result",
                                    "ok": True,
                                    "data": {
                                        "acknowledged_to": int(payload["last_notification_id"])
                                    },
                                }
                            )
                        )
            finally:
                push_task.cancel()
            return ws

        runner, url = await _start_server(handler)
        pool, tmp = await _open_db()
        client = CrawlerClient(_config(url))
        dispatched: list[int] = []

        async def dispatch(record: dict) -> None:
            dispatched.append(int(record["id"]))

        consumer = NotificationConsumer(
            client=client,
            store=ConsumerStateStore(pool),
            consumer_key="test",
            dispatch=dispatch,
        )
        try:
            await client.start()
            await consumer.start()
            for _ in range(80):
                if len(dispatched) >= 2 and not consumer.catching_up:
                    break
                await asyncio.sleep(0.05)
            assert dispatched == [5, 6], f"order wrong: {dispatched}"
            assert consumer.last_acked == 6
        finally:
            await consumer.stop()
            await client.stop()
            await pool.close()
            tmp.cleanup()
            await runner.cleanup()

    asyncio.run(_run())


def test_live_push_with_id_already_acked_is_skipped() -> None:
    async def _run() -> None:
        ack_log: list[int] = []

        async def server(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            # First respond to list, then push an old id=10 record.
            push_sent = False
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                payload = json.loads(msg.data)
                rid = payload["request_id"]
                if payload["type"] == "notifications_list":
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": rid,
                                "type": "notifications_list_result",
                                "ok": True,
                                "data": {
                                    "notifications": [],
                                    "last_notification_id": None,
                                    "consumer_offset": 10,
                                },
                            }
                        )
                    )
                    if not push_sent:
                        push_sent = True
                        await ws.send_str(
                            json.dumps(
                                {
                                    "request_id": "push-10",
                                    "type": "notification_event",
                                    "ok": True,
                                    "data": {"notification": _record(10)},
                                }
                            )
                        )
                elif payload["type"] == "notifications_ack":
                    ack_log.append(int(payload["last_notification_id"]))
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": rid,
                                "type": "notifications_ack_result",
                                "ok": True,
                                "data": {"acknowledged_to": int(payload["last_notification_id"])},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(server)
        pool, tmp = await _open_db()
        # Pre-seed last_acked = 10.
        await ConsumerStateStore(pool).set_last_acked("test", 10)
        client = CrawlerClient(_config(url))
        dispatched: list[int] = []

        async def dispatch(record: dict) -> None:
            dispatched.append(int(record["id"]))

        consumer = NotificationConsumer(
            client=client,
            store=ConsumerStateStore(pool),
            consumer_key="test",
            dispatch=dispatch,
        )
        try:
            await client.start()
            await consumer.start()
            await asyncio.sleep(0.4)  # let push be received and (correctly) ignored
            assert dispatched == []
            assert ack_log == []
            assert consumer.last_acked == 10
        finally:
            await consumer.stop()
            await client.stop()
            await pool.close()
            tmp.cleanup()
            await runner.cleanup()

    asyncio.run(_run())


def test_dispatch_failure_does_not_advance_ack() -> None:
    async def _run() -> None:
        ack_log: list[int] = []
        handler = _make_handler([[_record(1), _record(2), _record(3)], []], ack_log=ack_log)
        runner, url = await _start_server(handler)
        pool, tmp = await _open_db()
        client = CrawlerClient(_config(url))
        dispatched: list[int] = []

        async def dispatch(record: dict) -> None:
            dispatched.append(int(record["id"]))
            if int(record["id"]) == 2:
                raise RuntimeError("boom")

        consumer = NotificationConsumer(
            client=client,
            store=ConsumerStateStore(pool),
            consumer_key="test",
            dispatch=dispatch,
        )
        try:
            await client.start()
            await consumer.start()
            await asyncio.sleep(0.5)
            assert dispatched == [1, 2]
            assert consumer.last_acked == 1
            stored = await ConsumerStateStore(pool).get_last_acked("test")
            assert stored == 1
            # Only id=1 was successfully dispatched, so ack_log holds at most [1].
            assert ack_log == [1]
        finally:
            await consumer.stop()
            await client.stop()
            await pool.close()
            tmp.cleanup()
            await runner.cleanup()

    asyncio.run(_run())


def test_reconnect_resumes_from_last_acked() -> None:
    async def _run() -> None:
        ack_log: list[int] = []
        connection_count = {"n": 0}

        async def handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            connection_count["n"] += 1
            this_conn = connection_count["n"]
            sent_first_page = False
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                payload = json.loads(msg.data)
                rid = payload["request_id"]
                if payload["type"] == "notifications_list":
                    if this_conn == 1:
                        if not sent_first_page:
                            sent_first_page = True
                            await ws.send_str(
                                json.dumps(
                                    {
                                        "request_id": rid,
                                        "type": "notifications_list_result",
                                        "ok": True,
                                        "data": {
                                            "notifications": [_record(1), _record(2)],
                                            "last_notification_id": 2,
                                            "consumer_offset": None,
                                        },
                                    }
                                )
                            )
                        else:
                            await ws.send_str(
                                json.dumps(
                                    {
                                        "request_id": rid,
                                        "type": "notifications_list_result",
                                        "ok": True,
                                        "data": {
                                            "notifications": [],
                                            "last_notification_id": None,
                                            "consumer_offset": None,
                                        },
                                    }
                                )
                            )
                    else:
                        # Second connection: assert client passed since_id=2.
                        assert int(payload.get("since_id") or 0) == 2
                        await ws.send_str(
                            json.dumps(
                                {
                                    "request_id": rid,
                                    "type": "notifications_list_result",
                                    "ok": True,
                                    "data": {
                                        "notifications": [_record(3)],
                                        "last_notification_id": 3,
                                        "consumer_offset": 2,
                                    },
                                }
                            )
                        )
                        # Drain by sending empty page on next call.
                elif payload["type"] == "notifications_ack":
                    ack_log.append(int(payload["last_notification_id"]))
                    await ws.send_str(
                        json.dumps(
                            {
                                "request_id": rid,
                                "type": "notifications_ack_result",
                                "ok": True,
                                "data": {"acknowledged_to": int(payload["last_notification_id"])},
                            }
                        )
                    )
            return ws

        runner, url = await _start_server(handler)
        pool, tmp = await _open_db()
        client = CrawlerClient(_config(url))
        dispatched: list[int] = []

        async def dispatch(record: dict) -> None:
            dispatched.append(int(record["id"]))

        consumer = NotificationConsumer(
            client=client,
            store=ConsumerStateStore(pool),
            consumer_key="test",
            dispatch=dispatch,
        )
        try:
            await client.start()
            await consumer.start()
            for _ in range(80):
                if len(dispatched) >= 2 and not consumer.catching_up:
                    break
                await asyncio.sleep(0.05)
            assert dispatched == [1, 2]
            assert consumer.last_acked == 2

            # Force a reconnect by closing the underlying WS.
            ws = client._ws  # type: ignore[attr-defined]
            assert ws is not None
            await ws.close()

            for _ in range(120):
                if 3 in dispatched and not consumer.catching_up:
                    break
                await asyncio.sleep(0.05)
            assert dispatched == [1, 2, 3]
            assert consumer.last_acked == 3
            assert ack_log[-1] == 3
        finally:
            await consumer.stop()
            await client.stop()
            await pool.close()
            tmp.cleanup()
            await runner.cleanup()

    asyncio.run(_run())
