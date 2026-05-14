"""Tests for PremiumGrantStore lifecycle."""

import asyncio
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.premium_grants import PremiumGrantStore


async def _make_store(tmp: str) -> tuple[DbPool, PremiumGrantStore]:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    return pool, PremiumGrantStore(pool)


def _future_ts(days: int = 7) -> str:
    return (datetime.now(tz=UTC) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _past_ts(days: int = 1) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def test_grant_and_find_active() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.grant("user", 1001, 9999, "free trial", _future_ts(7))
                grant = await store.find_active("user", 1001)
                assert grant is not None
                assert grant.scope == "user"
                assert grant.target_id == 1001
            finally:
                await pool.close()

    asyncio.run(_run())


def test_expired_grant_not_active() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.grant("user", 1002, 9999, "expired", _past_ts(1))
                grant = await store.find_active("user", 1002)
                assert grant is None, "expired grant should not be active"
            finally:
                await pool.close()

    asyncio.run(_run())


def test_revoke_grant() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                grant_id = await store.grant("guild", 2001, 9999, None, None)
                grant = await store.find_active("guild", 2001)
                assert grant is not None

                await store.revoke(grant_id)
                grant = await store.find_active("guild", 2001)
                assert grant is None, "revoked grant should not be active"
            finally:
                await pool.close()

    asyncio.run(_run())


def test_sweep_expired() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                # One active, one already expired.
                await store.grant("user", 3001, 9999, "active", _future_ts(7))
                await store.grant("user", 3002, 9999, "expired", _past_ts(1))

                swept = await store.sweep_expired()
                assert swept == 1, f"expected 1 swept, got {swept}"

                # Active one is still findable.
                assert await store.find_active("user", 3001) is not None
                # Expired one is gone (revoked).
                assert await store.find_active("user", 3002) is None

                # Second sweep is a no-op.
                swept2 = await store.sweep_expired()
                assert swept2 == 0
            finally:
                await pool.close()

    asyncio.run(_run())


def test_permanent_grant() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _make_store(tmp)
            try:
                await store.grant("user", 4001, 9999, "permanent", None)
                grant = await store.find_active("user", 4001)
                assert grant is not None
                assert grant.expires_at is None
            finally:
                await pool.close()

    asyncio.run(_run())
