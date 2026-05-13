"""Long-lived WebSocket client to the crawler service.

Single connection, request/response correlation by ``request_id``, plus a
push-handler registry for unsolicited events like ``notification_event``.
Reconnects with exponential backoff; in-flight requests fail fast on
disconnect so callers can retry.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from ..config import CrawlerConfig
from ..log import get
from .errors import CrawlerError, Disconnected, RequestTimeout
from .progress import CrawlerProgressEvent, parse_progress_event
from .retry import Backoff

PushHandler = Callable[[dict[str, Any]], Awaitable[None]]
ProgressCallback = Callable[[CrawlerProgressEvent], Awaitable[None] | None]


_log = get(__name__)


class CrawlerClient:
    """Single-connection crawler WS client with request/response correlation."""

    def __init__(self, config: CrawlerConfig) -> None:
        self._config = config
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._connect_task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._progress_callbacks: dict[str, ProgressCallback] = {}
        self._progress_tasks_by_request: dict[str, asyncio.Task[None]] = {}
        self._push_handlers: dict[str, list[PushHandler]] = {}
        self._connected_event = asyncio.Event()
        self._stopping = False
        self._on_connect: list[Callable[[], Awaitable[None]]] = []
        self._background_tasks: set[asyncio.Task[None]] = set()

    # -- public api -----------------------------------------------------

    async def start(self) -> None:
        """Open the WS and start the reader. Returns once the first connection lands."""
        if self._connect_task is not None:
            return
        self._stopping = False
        self._session = aiohttp.ClientSession()
        self._connect_task = asyncio.create_task(self._connect_loop(), name="crawler-connect")
        await self._connected_event.wait()

    async def stop(self) -> None:
        """Close the WS and cancel background tasks. Idempotent."""
        self._stopping = True
        self._connected_event.clear()
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(Disconnected())
        self._pending.clear()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError, Exception:
                pass
            self._reader_task = None
        if self._connect_task is not None:
            self._connect_task.cancel()
            try:
                await self._connect_task
            except asyncio.CancelledError, Exception:
                pass
            self._connect_task = None
        background_tasks = [
            task for task in self._background_tasks if task is not asyncio.current_task()
        ]
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
            self._background_tasks.difference_update(background_tasks)
        self._progress_tasks_by_request.clear()
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def request(
        self,
        type_: str,
        *,
        timeout: float | None = None,
        request_id: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Send a correlated request and await the response.

        Returns the ``data`` payload on success. Raises :class:`CrawlerError`
        with the server-provided ``code``/``message`` on failure, or
        :class:`RequestTimeout` if no response arrives in time.
        """
        return await self._request(
            type_,
            timeout=timeout,
            request_id=request_id,
            progress_callback=None,
            **fields,
        )

    async def request_with_progress(
        self,
        type_: str,
        *,
        timeout: float | None = None,
        request_id: str | None = None,
        on_progress: ProgressCallback | None = None,
        progress_callback: ProgressCallback | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Send a correlated request and route progress updates to a callback."""
        return await self._request(
            type_,
            timeout=timeout,
            request_id=request_id,
            progress_callback=on_progress or progress_callback,
            **fields,
        )

    async def _request(
        self,
        type_: str,
        *,
        timeout: float | None,
        request_id: str | None,
        progress_callback: ProgressCallback | None,
        **fields: Any,
    ) -> dict[str, Any]:
        if self._ws is None or self._ws.closed:
            raise Disconnected()
        rid = request_id or uuid.uuid4().hex
        timeout_s = timeout if timeout is not None else self._config.request_timeout_seconds
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[rid] = fut
        if progress_callback is not None:
            self._progress_callbacks[rid] = progress_callback
        envelope = {"type": type_, "request_id": rid, **fields}
        response_received = False
        try:
            async with self._send_lock:
                if self._ws is None or self._ws.closed:
                    raise Disconnected(request_id=rid)
                await self._ws.send_str(json.dumps(envelope))
            try:
                response = await asyncio.wait_for(fut, timeout=timeout_s)
                response_received = True
            except TimeoutError as exc:
                raise RequestTimeout(request_id=rid) from exc
            progress_task = self._progress_tasks_by_request.pop(rid, None)
            if progress_task is not None:
                await self._drain_progress_task(progress_task)
        finally:
            self._pending.pop(rid, None)
            self._progress_callbacks.pop(rid, None)
            if not response_received:
                progress_task = self._progress_tasks_by_request.pop(rid, None)
                if progress_task is not None:
                    progress_task.cancel()
                    await self._drain_progress_task(progress_task)
        if not response.get("ok", False):
            err = response.get("error") or {}
            raise CrawlerError(
                code=str(err.get("code") or "unknown_error"),
                message=str(err.get("message") or "no message"),
                request_id=rid,
            )
        data = response.get("data")
        return data if isinstance(data, dict) else {}

    def on_push(self, type_: str, handler: PushHandler) -> None:
        """Register a handler for unsolicited messages of the given ``type``."""
        self._push_handlers.setdefault(type_, []).append(handler)

    def on_connect(self, handler: Callable[[], Awaitable[None]]) -> None:
        """Register a callback invoked each time the WS (re)connects."""
        self._on_connect.append(handler)

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    # -- internals ------------------------------------------------------

    async def _connect_loop(self) -> None:
        backoff = Backoff(
            initial=self._config.reconnect_initial_delay_seconds,
            maximum=self._config.reconnect_max_delay_seconds,
            jitter=self._config.reconnect_jitter_seconds,
        )
        while not self._stopping:
            try:
                await self._connect_once()
                backoff.reset()
                # Block until reader exits (disconnect or error).
                if self._reader_task is not None:
                    await self._reader_task
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.warning("crawler connect/read failed: %s", exc)
            finally:
                # Fail in-flight requests so callers retry.
                for fut in list(self._pending.values()):
                    if not fut.done():
                        fut.set_exception(Disconnected())
                self._pending.clear()
                self._connected_event.clear()
                self._ws = None
            if self._stopping:
                return
            delay = backoff.next_delay()
            _log.info("reconnecting to crawler in %.1fs", delay)
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise

    async def _connect_once(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        _log.info("connecting to crawler at %s", self._config.ws_url)
        self._ws = await self._session.ws_connect(
            self._config.ws_url, headers=headers, heartbeat=30.0
        )
        self._connected_event.set()
        self._reader_task = asyncio.create_task(self._reader_loop(), name="crawler-reader")
        for callback in list(self._on_connect):
            try:
                await callback()
            except Exception:
                _log.exception("crawler on_connect callback failed")

    async def _reader_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    _log.warning("crawler sent non-JSON frame; ignoring")
                    continue
                if not isinstance(payload, dict):
                    continue
                await self._dispatch(payload)
            elif msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
            ):
                break
            elif msg.type == aiohttp.WSMsgType.ERROR:
                _log.warning("crawler WS error: %s", ws.exception())
                break

    async def _dispatch(self, payload: dict[str, Any]) -> None:
        rid = payload.get("request_id")
        type_ = str(payload.get("type") or "")
        if type_ == "request_progress":
            await self._dispatch_progress(payload, rid)
            return
        # Correlated response.
        if isinstance(rid, str) and rid in self._pending:
            fut = self._pending.get(rid)
            if fut is not None and not fut.done():
                fut.set_result(payload)
            return
        # Otherwise, treat as a push.
        handlers = self._push_handlers.get(type_, [])
        if not handlers:
            _log.debug("ignoring unsolicited crawler message of type %r", type_)
            return
        for handler in handlers:
            task = asyncio.create_task(self._safe_push(handler, payload), name=f"push-{type_}")
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _dispatch_progress(self, payload: dict[str, Any], rid: object) -> None:
        if not isinstance(rid, str):
            return
        callback = self._progress_callbacks.get(rid)
        if callback is None:
            return
        try:
            event = parse_progress_event(payload)
        except ValueError:
            _log.exception("crawler sent invalid progress event; ignoring")
            return
        previous = self._progress_tasks_by_request.get(rid)
        task = asyncio.create_task(
            self._run_progress_chain(previous, callback, event),
            name=f"progress-{rid}",
        )
        self._progress_tasks_by_request[rid] = task
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_progress_chain(
        self,
        previous: asyncio.Task[None] | None,
        callback: ProgressCallback,
        event: CrawlerProgressEvent,
    ) -> None:
        if previous is not None:
            await asyncio.gather(previous, return_exceptions=True)
        await self._safe_progress_callback(callback, event)

    async def _drain_progress_task(self, task: asyncio.Task[None]) -> None:
        await asyncio.gather(task, return_exceptions=True)

    async def _safe_progress_callback(
        self,
        callback: ProgressCallback,
        event: CrawlerProgressEvent,
    ) -> None:
        try:
            result = callback(event)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("crawler progress callback failed; continuing")

    async def _safe_push(self, handler: PushHandler, payload: dict[str, Any]) -> None:
        try:
            await handler(payload)
        except Exception:
            _log.exception("push handler raised; continuing")
