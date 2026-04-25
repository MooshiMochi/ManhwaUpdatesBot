"""TtlCache — hit / miss / expiry behaviour."""

from __future__ import annotations

import asyncio
import time

from manhwa_bot.cache import TtlCache


def test_first_call_hits_loader() -> None:
    async def _run() -> None:
        call_count = 0

        async def loader() -> list[str]:
            nonlocal call_count
            call_count += 1
            return ["asura", "reaper"]

        cache: TtlCache[list[str]] = TtlCache()
        result = await cache.get_or_set("sites", loader, ttl_seconds=60)
        assert result == ["asura", "reaper"]
        assert call_count == 1

    asyncio.run(_run())


def test_second_call_within_ttl_uses_cache() -> None:
    async def _run() -> None:
        call_count = 0

        async def loader() -> list[str]:
            nonlocal call_count
            call_count += 1
            return ["asura"]

        cache: TtlCache[list[str]] = TtlCache()
        await cache.get_or_set("sites", loader, ttl_seconds=60)
        await cache.get_or_set("sites", loader, ttl_seconds=60)
        assert call_count == 1, "second call within TTL should not invoke the loader"

    asyncio.run(_run())


def test_call_after_ttl_re_invokes_loader() -> None:
    async def _run() -> None:
        call_count = 0

        async def loader() -> list[str]:
            nonlocal call_count
            call_count += 1
            return ["asura"]

        cache: TtlCache[list[str]] = TtlCache()
        await cache.get_or_set("sites", loader, ttl_seconds=60)
        # Artificially expire the entry.
        cache._store["sites"] = (cache._store["sites"][0], time.monotonic() - 1)
        await cache.get_or_set("sites", loader, ttl_seconds=60)
        assert call_count == 2, "expired entry should cause loader to be called again"

    asyncio.run(_run())


def test_invalidate_forces_reload() -> None:
    async def _run() -> None:
        call_count = 0

        async def loader() -> list[str]:
            nonlocal call_count
            call_count += 1
            return ["flame"]

        cache: TtlCache[list[str]] = TtlCache()
        await cache.get_or_set("sites", loader, ttl_seconds=60)
        cache.invalidate("sites")
        await cache.get_or_set("sites", loader, ttl_seconds=60)
        assert call_count == 2, "invalidate should evict the entry"

    asyncio.run(_run())


def test_separate_keys_are_independent() -> None:
    async def _run() -> None:
        a_count = 0
        b_count = 0

        async def loader_a() -> str:
            nonlocal a_count
            a_count += 1
            return "a"

        async def loader_b() -> str:
            nonlocal b_count
            b_count += 1
            return "b"

        cache: TtlCache[str] = TtlCache()
        await cache.get_or_set("a", loader_a, ttl_seconds=60)
        await cache.get_or_set("b", loader_b, ttl_seconds=60)
        cache.invalidate("a")
        await cache.get_or_set("a", loader_a, ttl_seconds=60)
        await cache.get_or_set("b", loader_b, ttl_seconds=60)

        assert a_count == 2
        assert b_count == 1, "invalidating 'a' should not affect 'b'"

    asyncio.run(_run())
