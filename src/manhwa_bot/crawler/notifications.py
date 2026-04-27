"""Notification consumer — catch-up replay + live push handoff.

Owns the WS-level state machine that turns the crawler's `notification_event`
push and `notifications_list` replay into an in-order stream of records
delivered to a single ``dispatch`` callback. Persists the last-acked
notification id locally so reconnects only replay genuinely missed events.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from ..db.consumer_state import ConsumerStateStore
from .client import CrawlerClient
from .errors import CrawlerError, Disconnected, RequestTimeout

_log = logging.getLogger(__name__)

DispatchFn = Callable[[dict[str, Any]], Awaitable[None]]


class NotificationConsumer:
    """Catch-up replay + live-push handoff for crawler notification_event.

    Designed to be created once per bot lifetime. ``start()`` is idempotent.
    The single ``dispatch`` callback is responsible for any per-target
    error isolation; if it raises, the consumer treats the record as failed
    and refrains from advancing the offset.
    """

    def __init__(
        self,
        *,
        client: CrawlerClient,
        store: ConsumerStateStore,
        consumer_key: str,
        dispatch: DispatchFn,
        catchup_page_size: int = 200,
    ) -> None:
        self._client = client
        self._store = store
        self._consumer_key = consumer_key
        self._dispatch = dispatch
        self._catchup_page_size = max(1, min(int(catchup_page_size), 500))
        self._lock = asyncio.Lock()
        self._pending_live: deque[dict[str, Any]] = deque()
        self._catching_up = False
        self._last_acked = 0
        self._started = False
        self._initial_task: asyncio.Task[None] | None = None

    @property
    def last_acked(self) -> int:
        return self._last_acked

    @property
    def catching_up(self) -> bool:
        return self._catching_up

    async def start(self) -> None:
        """Register handlers and trigger first-run catch-up if already connected."""
        if self._started:
            return
        self._started = True
        self._last_acked = await self._store.get_last_acked(self._consumer_key)
        _log.info(
            "notification consumer starting (consumer_key=%s, last_acked=%d)",
            self._consumer_key,
            self._last_acked,
        )
        self._client.on_push("notification_event", self._on_push)
        self._client.on_connect(self._on_connect)
        if self._client.connected:
            self._initial_task = asyncio.create_task(
                self._on_connect(),
                name="notif-consumer-initial-catchup",
            )

    async def stop(self) -> None:
        """Mark stopped. Pending live records are dropped (replayed on next start)."""
        self._started = False
        self._pending_live.clear()

    async def _on_connect(self) -> None:
        async with self._lock:
            self._catching_up = True
            try:
                await self._run_catchup()
            except Exception:
                _log.exception("notification catch-up failed; will retry on next reconnect")
            finally:
                await self._drain_queued_live()
                self._catching_up = False

    async def _run_catchup(self) -> None:
        while True:
            try:
                data = await self._client.request(
                    "notifications_list",
                    consumer_key=self._consumer_key,
                    since_id=self._last_acked,
                    limit=self._catchup_page_size,
                )
            except (Disconnected, RequestTimeout, CrawlerError) as exc:
                _log.warning("notifications_list failed: %s", exc)
                return
            records = data.get("notifications") or []
            if not records:
                _log.info("catch-up complete, last_acked=%d", self._last_acked)
                return
            page_advanced = False
            halt = False
            for record in records:
                rid = _record_id(record)
                if rid is None or rid <= self._last_acked:
                    continue
                try:
                    await self._dispatch(record)
                except Exception:
                    _log.exception("dispatch raised for notification id=%s; halting catch-up", rid)
                    halt = True
                    break
                self._last_acked = rid
                page_advanced = True
            if page_advanced:
                await self._persist_and_ack()
            if halt:
                return
            if len(records) < self._catchup_page_size:
                _log.info("catch-up complete, last_acked=%d", self._last_acked)
                return

    async def _drain_queued_live(self) -> None:
        while self._pending_live:
            record = self._pending_live.popleft()
            rid = _record_id(record)
            if rid is None or rid <= self._last_acked:
                continue
            try:
                await self._dispatch(record)
            except Exception:
                _log.exception(
                    "dispatch raised for queued live notification id=%s; "
                    "halting drain (will replay on next reconnect)",
                    rid,
                )
                return
            self._last_acked = rid
            await self._persist_and_ack()

    async def _on_push(self, envelope: dict[str, Any]) -> None:
        data = envelope.get("data") or {}
        record = data.get("notification")
        if not isinstance(record, dict):
            _log.debug("notification_event with no record payload; ignoring")
            return
        # Fast queue path: don't take the lock if we know we're catching up.
        if self._catching_up:
            self._pending_live.append(record)
            return
        async with self._lock:
            if self._catching_up:
                self._pending_live.append(record)
                return
            rid = _record_id(record)
            if rid is None or rid <= self._last_acked:
                return
            try:
                await self._dispatch(record)
            except Exception:
                _log.exception(
                    "dispatch raised for live notification id=%s; "
                    "skipping ack (will replay on next reconnect)",
                    rid,
                )
                return
            self._last_acked = rid
            await self._persist_and_ack()

    async def _persist_and_ack(self) -> None:
        if self._last_acked <= 0:
            return
        try:
            await self._store.set_last_acked(self._consumer_key, self._last_acked)
        except Exception:
            _log.exception("failed to persist last_acked=%d locally", self._last_acked)
        try:
            await self._client.request(
                "notifications_ack",
                consumer_key=self._consumer_key,
                last_notification_id=self._last_acked,
            )
        except (Disconnected, RequestTimeout, CrawlerError) as exc:
            _log.warning(
                "notifications_ack(%d) failed: %s; offset stored locally, will retry on reconnect",
                self._last_acked,
                exc,
            )


def _record_id(record: dict[str, Any]) -> int | None:
    raw = record.get("id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
