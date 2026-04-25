"""Store for the premium_grants table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .pool import DbPool

_ACTIVE_FILTER = "revoked_at IS NULL AND (expires_at IS NULL OR expires_at > datetime('now'))"


@dataclass(frozen=True)
class PremiumGrant:
    id: int
    scope: str
    target_id: int
    granted_by: int
    reason: str | None
    granted_at: str
    expires_at: str | None
    revoked_at: str | None


def _row_to_grant(row: Any) -> PremiumGrant:
    return PremiumGrant(
        id=row["id"],
        scope=row["scope"],
        target_id=row["target_id"],
        granted_by=row["granted_by"],
        reason=row["reason"],
        granted_at=row["granted_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
    )


class PremiumGrantStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def grant(
        self,
        scope: str,
        target_id: int,
        granted_by: int,
        reason: str | None,
        expires_at: str | None,
    ) -> int:
        cursor = await self._pool.execute(
            """
            INSERT INTO premium_grants (scope, target_id, granted_by, reason, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scope, target_id, granted_by, reason, expires_at),
        )
        return cursor.lastrowid  # type: ignore[return-value]

    async def revoke(self, grant_id: int) -> None:
        await self._pool.execute(
            "UPDATE premium_grants SET revoked_at = datetime('now') WHERE id = ?",
            (grant_id,),
        )

    async def revoke_for_target(self, scope: str, target_id: int) -> None:
        await self._pool.execute(
            f"UPDATE premium_grants SET revoked_at = datetime('now') WHERE scope = ? AND target_id = ? AND {_ACTIVE_FILTER}",
            (scope, target_id),
        )

    async def list(
        self,
        scope: str | None = None,
        *,
        active_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PremiumGrant]:
        clauses = []
        params: list[Any] = []
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if active_only:
            clauses.append(_ACTIVE_FILTER)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = await self._pool.fetchall(
            f"SELECT * FROM premium_grants {where} ORDER BY granted_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [_row_to_grant(r) for r in rows]

    async def find_active(self, scope: str, target_id: int) -> PremiumGrant | None:
        row = await self._pool.fetchone(
            f"SELECT * FROM premium_grants WHERE scope = ? AND target_id = ? AND {_ACTIVE_FILTER} LIMIT 1",
            (scope, target_id),
        )
        return _row_to_grant(row) if row else None

    async def sweep_expired(self) -> int:
        cursor = await self._pool.execute(
            """
            UPDATE premium_grants
            SET revoked_at = datetime('now')
            WHERE revoked_at IS NULL
              AND expires_at IS NOT NULL
              AND expires_at <= datetime('now')
            """,
        )
        return cursor.rowcount  # type: ignore[return-value]
