"""Generic TTL cache used for infrequently-changing lookups (e.g. supported_websites)."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable


class TtlCache[V]:
    """In-memory key→value cache with per-entry expiry.

    Not thread-safe — only call from the asyncio event loop.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[V, float]] = {}

    async def get_or_set(
        self,
        key: str,
        loader: Callable[[], Awaitable[V]],
        ttl_seconds: float,
    ) -> V:
        """Return the cached value for *key*, or call *loader* and cache the result."""
        entry = self._store.get(key)
        if entry is not None:
            value, expires_at = entry
            if time.monotonic() < expires_at:
                return value
        value = await loader()
        self._store[key] = (value, time.monotonic() + ttl_seconds)
        return value

    def invalidate(self, key: str) -> None:
        """Remove *key* from the cache (next call will invoke the loader)."""
        self._store.pop(key, None)
