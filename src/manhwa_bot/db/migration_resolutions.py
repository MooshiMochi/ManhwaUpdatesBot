"""Records user actions on `migration_leftovers.json` entries.

Each row remembers that the invoker resolved (or skipped) a specific
(scope, v1_scanlator, v1_url) leftover so the wizard does not re-prompt for it.
"""

from __future__ import annotations

from .pool import DbPool


class MigrationResolutionsStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def record(
        self,
        scope: str,
        owner_id: int,
        v1_scanlator: str,
        v1_url: str,
        v2_website_key: str | None,
        v2_url_name: str | None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO migration_resolutions
              (scope, owner_id, v1_scanlator, v1_url, v2_website_key, v2_url_name)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope, owner_id, v1_scanlator, v1_url) DO UPDATE SET
              v2_website_key = excluded.v2_website_key,
              v2_url_name    = excluded.v2_url_name,
              resolved_at    = CURRENT_TIMESTAMP
            """,
            (scope, owner_id, v1_scanlator, v1_url, v2_website_key, v2_url_name),
        )

    async def resolved_keys(self, scope: str, owner_id: int) -> set[tuple[str, str]]:
        rows = await self._pool.fetchall(
            "SELECT v1_scanlator, v1_url FROM migration_resolutions"
            " WHERE scope = ? AND owner_id = ?",
            (scope, owner_id),
        )
        return {(r["v1_scanlator"], r["v1_url"]) for r in rows}
