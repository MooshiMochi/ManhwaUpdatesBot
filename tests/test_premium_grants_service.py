"""Tests for GrantsService and parse_duration."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.premium_grants import PremiumGrantStore
from manhwa_bot.premium.grants import GrantsService, parse_duration


def _parse(s: str) -> datetime | None:
    out = parse_duration(s)
    if out is None:
        return None
    return datetime.strptime(out, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def test_parse_duration_permanent_returns_none() -> None:
    assert parse_duration("permanent") is None
    assert parse_duration("PERMANENT") is None


def test_parse_duration_relative_units() -> None:
    now = datetime.now(tz=UTC)

    assert (_parse("7d") - now) - timedelta(days=7) < timedelta(seconds=5)  # type: ignore[operator]
    assert (_parse("48h") - now) - timedelta(hours=48) < timedelta(seconds=5)  # type: ignore[operator]
    assert (_parse("1mo") - now) - timedelta(days=30) < timedelta(seconds=5)  # type: ignore[operator]
    assert (_parse("30m") - now) - timedelta(minutes=30) < timedelta(seconds=5)  # type: ignore[operator]


def test_parse_duration_iso_timestamp() -> None:
    iso = "2030-01-02T03:04:05+00:00"
    parsed = _parse(iso)
    assert parsed == datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_parse_duration_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_duration("nonsense")
    with pytest.raises(ValueError):
        parse_duration("")


async def _make_service(tmp: str) -> tuple[DbPool, GrantsService]:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    store = PremiumGrantStore(pool)
    return pool, GrantsService(store, sweep_interval=0.05)


def test_is_active_delegates_to_store() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, service = await _make_service(tmp)
            try:
                assert await service.is_active("user", 100) is False
                await service.store.grant("user", 100, 1, "trial", parse_duration("7d"))
                assert await service.is_active("user", 100) is True

                await service.store.grant("guild", 200, 1, "trial", parse_duration("7d"))
                assert await service.is_active("guild", 200) is True
                assert await service.is_active("guild", 999) is False
            finally:
                await pool.close()

    asyncio.run(_run())


def test_sweep_loop_revokes_expired_entries() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, service = await _make_service(tmp)
            try:
                past = (datetime.now(tz=UTC) - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
                await service.store.grant("user", 555, 1, "expired", past)
                assert await service.is_active("user", 555) is False  # filter by datetime('now')

                await service.start()
                # The sweep moves revoked_at to a non-NULL value so the row no
                # longer counts as active even if expires_at had been in the
                # future.  Wait for at least one tick.
                await asyncio.sleep(0.2)
                await service.stop()

                row = await pool.fetchone(
                    "SELECT revoked_at FROM premium_grants WHERE target_id = ?", (555,)
                )
                assert row is not None
                assert row["revoked_at"] is not None
            finally:
                await pool.close()

    asyncio.run(_run())


def test_stop_is_idempotent_when_never_started() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, service = await _make_service(tmp)
            try:
                await service.stop()  # should not raise
            finally:
                await pool.close()

    asyncio.run(_run())
