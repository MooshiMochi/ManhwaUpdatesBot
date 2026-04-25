"""GrantsService — DB-backed manual premium grants with periodic expiry sweep."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from ..db.premium_grants import PremiumGrantStore

_log = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^(?P<n>\d+)(?P<unit>mo|d|h|m|s)$", re.IGNORECASE)
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_SWEEP_INTERVAL_SECONDS = 60.0


def parse_duration(text: str) -> str | None:
    """Parse a duration string into a UTC SQLite timestamp, or None for permanent.

    Accepts ``"permanent"``, shorthand (``7d``, ``48h``, ``1mo``, ``30m``, ``45s``),
    or an explicit ISO-8601 timestamp. Returns the format expected by the
    ``premium_grants.expires_at`` column (``%Y-%m-%d %H:%M:%S`` UTC).
    """
    s = text.strip()
    if not s:
        raise ValueError("duration is empty")
    if s.lower() == "permanent":
        return None

    match = _DURATION_RE.match(s)
    if match:
        n = int(match.group("n"))
        unit = match.group("unit").lower()
        if unit == "s":
            delta = timedelta(seconds=n)
        elif unit == "m":
            delta = timedelta(minutes=n)
        elif unit == "h":
            delta = timedelta(hours=n)
        elif unit == "d":
            delta = timedelta(days=n)
        elif unit == "mo":
            delta = timedelta(days=30 * n)
        else:  # pragma: no cover — regex constrains units
            raise ValueError(f"unknown duration unit: {unit}")
        return (datetime.now(tz=UTC) + delta).strftime(_TIMESTAMP_FORMAT)

    try:
        parsed = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"unrecognized duration: {text!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


class GrantsService:
    """Thin wrapper over ``PremiumGrantStore`` plus a background expiry sweep."""

    def __init__(self, store: PremiumGrantStore, sweep_interval: float = _SWEEP_INTERVAL_SECONDS):
        self._store = store
        self._sweep_interval = sweep_interval
        self._task: asyncio.Task[None] | None = None

    @property
    def store(self) -> PremiumGrantStore:
        return self._store

    async def is_active(self, scope: str, target_id: int) -> bool:
        return (await self._store.find_active(scope, target_id)) is not None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._sweep_loop(), name="premium-grants-sweep")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError, Exception:
            pass

    async def _sweep_loop(self) -> None:
        while True:
            try:
                revoked = await self._store.sweep_expired()
                if revoked:
                    _log.info("Swept %d expired premium grants", revoked)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception("Premium grants sweep failed")
            try:
                await asyncio.sleep(self._sweep_interval)
            except asyncio.CancelledError:
                raise
