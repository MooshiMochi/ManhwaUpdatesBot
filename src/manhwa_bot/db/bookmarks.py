"""Store for the bookmarks table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .pool import DbPool


@dataclass(frozen=True)
class Bookmark:
    user_id: int
    website_key: str
    url_name: str
    folder: str
    last_read_chapter: str | None
    last_read_index: int | None
    created_at: str
    updated_at: str


def _row_to_bookmark(row: Any) -> Bookmark:
    return Bookmark(
        user_id=row["user_id"],
        website_key=row["website_key"],
        url_name=row["url_name"],
        folder=row["folder"],
        last_read_chapter=row["last_read_chapter"],
        last_read_index=row["last_read_index"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class BookmarkStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def upsert_bookmark(
        self,
        user_id: int,
        website_key: str,
        url_name: str,
        folder: str = "Reading",
        last_read_chapter: str | None = None,
        last_read_index: int | None = None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO bookmarks
              (user_id, website_key, url_name, folder, last_read_chapter, last_read_index)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, website_key, url_name) DO UPDATE SET
              folder            = excluded.folder,
              last_read_chapter = excluded.last_read_chapter,
              last_read_index   = excluded.last_read_index,
              updated_at        = CURRENT_TIMESTAMP
            """,
            (user_id, website_key, url_name, folder, last_read_chapter, last_read_index),
        )

    async def get_bookmark(self, user_id: int, website_key: str, url_name: str) -> Bookmark | None:
        row = await self._pool.fetchone(
            "SELECT * FROM bookmarks WHERE user_id = ? AND website_key = ? AND url_name = ?",
            (user_id, website_key, url_name),
        )
        return _row_to_bookmark(row) if row else None

    async def list_user_bookmarks(
        self,
        user_id: int,
        *,
        folder: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Bookmark]:
        if folder is not None:
            rows = await self._pool.fetchall(
                """
                SELECT * FROM bookmarks
                WHERE user_id = ? AND folder = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, folder, limit, offset),
            )
        else:
            rows = await self._pool.fetchall(
                """
                SELECT * FROM bookmarks
                WHERE user_id = ?
                ORDER BY folder, updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            )
        return [_row_to_bookmark(r) for r in rows]

    async def delete_bookmark(self, user_id: int, website_key: str, url_name: str) -> None:
        await self._pool.execute(
            "DELETE FROM bookmarks WHERE user_id = ? AND website_key = ? AND url_name = ?",
            (user_id, website_key, url_name),
        )

    async def update_last_read(
        self,
        user_id: int,
        website_key: str,
        url_name: str,
        *,
        chapter_text: str,
        chapter_index: int,
    ) -> None:
        await self._pool.execute(
            """
            UPDATE bookmarks
            SET last_read_chapter = ?, last_read_index = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND website_key = ? AND url_name = ?
            """,
            (chapter_text, chapter_index, user_id, website_key, url_name),
        )

    async def update_folder(
        self, user_id: int, website_key: str, url_name: str, folder: str
    ) -> None:
        await self._pool.execute(
            """
            UPDATE bookmarks
            SET folder = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND website_key = ? AND url_name = ?
            """,
            (folder, user_id, website_key, url_name),
        )

    async def count_for_user(self, user_id: int) -> int:
        row = await self._pool.fetchone(
            "SELECT COUNT(*) AS cnt FROM bookmarks WHERE user_id = ?",
            (user_id,),
        )
        return row["cnt"] if row else 0
