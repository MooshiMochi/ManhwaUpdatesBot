"""Clear all application data from the bot's SQLite database.

Truncates every user table (DELETE FROM) while preserving the schema and the
``schema_migrations`` ledger, so the bot does not re-run migrations on the next
startup. Run with ``--yes`` to actually modify data, or ``--dry-run`` to inspect
which tables would be cleared.

Usage:
    python -m manhwa_bot.scripts.clear_database --dry-run
    python -m manhwa_bot.scripts.clear_database --yes
    python -m manhwa_bot.scripts.clear_database --yes --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass

from ..config import load_config
from ..db.pool import DbPool

PRESERVED_TABLES: frozenset[str] = frozenset({"schema_migrations"})


@dataclass(frozen=True)
class ClearResult:
    action: str
    db_path: str
    tables: list[str]
    preserved_tables: list[str]
    rows_deleted: dict[str, int]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear application data from the bot's SQLite database while preserving the schema.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation flag. Without this flag the script will not modify data.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the tables that would be cleared without changing any data.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the result as JSON.",
    )
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to config.toml (default: config.toml in current working directory).",
    )
    return parser.parse_args()


async def _list_user_tables(pool: DbPool) -> list[str]:
    rows = await pool.fetchall(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    )
    return [str(row["name"]) for row in rows if str(row["name"]) not in PRESERVED_TABLES]


async def _count_rows(pool: DbPool, table: str) -> int:
    row = await pool.fetchone(f'SELECT COUNT(*) AS c FROM "{table}"')
    return int(row["c"]) if row is not None else 0


async def clear_database(
    *,
    config_path: str = "config.toml",
    dry_run: bool = False,
) -> ClearResult:
    cfg = load_config(config_path)
    pool = await DbPool.open(cfg.db.path)
    try:
        tables = await _list_user_tables(pool)
        rows_deleted: dict[str, int] = {}

        if dry_run:
            for table in tables:
                rows_deleted[table] = await _count_rows(pool, table)
            return ClearResult(
                action="dry_run",
                db_path=cfg.db.path,
                tables=tables,
                preserved_tables=sorted(PRESERVED_TABLES),
                rows_deleted=rows_deleted,
            )

        async with pool.transaction() as conn:
            await conn.execute("PRAGMA defer_foreign_keys = ON")
            for table in tables:
                async with conn.execute(f'SELECT COUNT(*) FROM "{table}"') as cur:
                    row = await cur.fetchone()
                    rows_deleted[table] = int(row[0]) if row is not None else 0
                await conn.execute(f'DELETE FROM "{table}"')
            # Reset AUTOINCREMENT counters if the sequence table exists.
            async with conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
            ) as cur:
                has_sequence = await cur.fetchone()
            if has_sequence is not None:
                await conn.execute("DELETE FROM sqlite_sequence")

        # VACUUM cannot run inside a transaction.
        await pool.execute("VACUUM")

        return ClearResult(
            action="clear",
            db_path=cfg.db.path,
            tables=tables,
            preserved_tables=sorted(PRESERVED_TABLES),
            rows_deleted=rows_deleted,
        )
    finally:
        await pool.close()


def _emit_result(result: ClearResult, *, as_json: bool) -> None:
    total_rows = sum(result.rows_deleted.values())
    if as_json:
        print(
            json.dumps(
                {
                    "action": result.action,
                    "db_path": result.db_path,
                    "table_count": len(result.tables),
                    "tables": result.tables,
                    "preserved_tables": result.preserved_tables,
                    "rows_total": total_rows,
                    "rows_per_table": result.rows_deleted,
                },
                indent=2,
            )
        )
        return

    verb = "Would clear" if result.action == "dry_run" else "Cleared"
    print(f"{verb} {len(result.tables)} table(s) ({total_rows} row(s)) in {result.db_path}.")
    print("Preserved tables:")
    for table in result.preserved_tables:
        print(f"  {table}")
    if result.tables:
        print("Affected tables:")
        for table in result.tables:
            count = result.rows_deleted.get(table, 0)
            print(f"  {table} ({count} row(s))")


async def _run() -> int:
    args = _parse_args()
    if not args.yes and not args.dry_run:
        print("Refusing to clear SQLite data without --yes. Use --dry-run to inspect first.")
        return 2

    result = await clear_database(
        config_path=str(args.config),
        dry_run=bool(args.dry_run),
    )
    _emit_result(result, as_json=args.json)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
