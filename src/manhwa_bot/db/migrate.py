"""File-based SQLite migrations runner.

Reads every ``*.sql`` file from the ``migrations/`` directory adjacent to this
module, sorted lexicographically, and applies each one that hasn't been
recorded in ``schema_migrations``.  Each migration runs inside its own
transaction; a failure aborts and re-raises so startup fails loudly.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .pool import DbPool

_log = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def apply_pending(pool: DbPool) -> None:
    """Apply all not-yet-applied migrations in lexicographic order."""
    # Ensure the tracking table exists before we query it.
    async with pool.transaction():
        await pool._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              filename   TEXT PRIMARY KEY,
              applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    applied: set[str] = {
        row[0]
        for row in await pool.fetchall("SELECT filename FROM schema_migrations ORDER BY filename")
    }

    migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    for path in migration_files:
        name = path.name
        if name in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        _log.info("applying migration %s", name)
        async with pool.transaction():
            for stmt in (s.strip() for s in sql.split(";")):
                if stmt:
                    await pool._conn.execute(stmt)
            await pool._conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (name,))
    if not migration_files:
        _log.warning("no migration files found in %s", _MIGRATIONS_DIR)
