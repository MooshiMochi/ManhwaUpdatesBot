"""Tests for the migrations runner."""

import asyncio
import tempfile
from pathlib import Path

from src.manhwa_bot.db.migrate import apply_pending
from src.manhwa_bot.db.pool import DbPool


def test_all_migrations_apply() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await DbPool.open(str(Path(tmp) / "test.db"))
            try:
                await apply_pending(pool)
                rows = await pool.fetchall(
                    "SELECT filename FROM schema_migrations ORDER BY filename"
                )
                names = [r["filename"] for r in rows]
                assert len(names) == 9, f"expected 9 migrations, got {len(names)}: {names}"
                # Check all expected files are recorded.
                for i in range(1, 10):
                    prefix = f"{i:03d}_"
                    assert any(n.startswith(prefix) for n in names), (
                        f"migration {prefix}* not found in {names}"
                    )
            finally:
                await pool.close()

    asyncio.run(_run())


def test_migrations_are_idempotent() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await DbPool.open(str(Path(tmp) / "test.db"))
            try:
                await apply_pending(pool)
                # Running a second time must not raise or double-insert.
                await apply_pending(pool)
                rows = await pool.fetchall("SELECT filename FROM schema_migrations")
                assert len(rows) == 9
            finally:
                await pool.close()

    asyncio.run(_run())


def test_expected_tables_exist() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = await DbPool.open(str(Path(tmp) / "test.db"))
            try:
                await apply_pending(pool)
                expected = {
                    "schema_migrations",
                    "tracked_series",
                    "tracked_in_guild",
                    "subscriptions",
                    "bookmarks",
                    "guild_settings",
                    "guild_scanlator_channels",
                    "dm_settings",
                    "consumer_state",
                    "premium_grants",
                    "patreon_links",
                }
                rows = await pool.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
                actual = {r["name"] for r in rows}
                missing = expected - actual
                assert not missing, f"missing tables: {missing}"
            finally:
                await pool.close()

    asyncio.run(_run())
