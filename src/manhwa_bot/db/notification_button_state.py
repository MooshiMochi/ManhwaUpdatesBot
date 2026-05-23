"""Persistent state for notification button callbacks."""

from __future__ import annotations

from dataclasses import dataclass

from .bookmarks import Bookmark
from .pool import DbPool


@dataclass(frozen=True)
class MarkReadToggleState:
    user_id: int
    website_key: str
    url_name: str
    chapter_index: int
    previous_bookmark_exists: bool
    previous_folder: str | None
    previous_last_read_chapter: str | None
    previous_last_read_index: int | None


class MarkReadToggleStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def get(
        self,
        user_id: int,
        website_key: str,
        url_name: str,
        chapter_index: int,
    ) -> MarkReadToggleState | None:
        row = await self._pool.fetchone(
            """
            SELECT *
            FROM notification_mark_read_toggles
            WHERE user_id = ?
              AND website_key = ?
              AND url_name = ?
              AND chapter_index = ?
            """,
            (user_id, website_key, url_name, chapter_index),
        )
        if row is None:
            return None
        return MarkReadToggleState(
            user_id=int(row["user_id"]),
            website_key=str(row["website_key"]),
            url_name=str(row["url_name"]),
            chapter_index=int(row["chapter_index"]),
            previous_bookmark_exists=bool(row["previous_bookmark_exists"]),
            previous_folder=row["previous_folder"],
            previous_last_read_chapter=row["previous_last_read_chapter"],
            previous_last_read_index=row["previous_last_read_index"],
        )

    async def save_previous(
        self,
        *,
        user_id: int,
        website_key: str,
        url_name: str,
        chapter_index: int,
        bookmark: Bookmark | None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO notification_mark_read_toggles (
              user_id,
              website_key,
              url_name,
              chapter_index,
              previous_bookmark_exists,
              previous_folder,
              previous_last_read_chapter,
              previous_last_read_index
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, website_key, url_name, chapter_index) DO UPDATE SET
              previous_bookmark_exists = excluded.previous_bookmark_exists,
              previous_folder = excluded.previous_folder,
              previous_last_read_chapter = excluded.previous_last_read_chapter,
              previous_last_read_index = excluded.previous_last_read_index
            """,
            (
                user_id,
                website_key,
                url_name,
                chapter_index,
                1 if bookmark is not None else 0,
                bookmark.folder if bookmark is not None else None,
                bookmark.last_read_chapter if bookmark is not None else None,
                bookmark.last_read_index if bookmark is not None else None,
            ),
        )

    async def clear(
        self,
        user_id: int,
        website_key: str,
        url_name: str,
        chapter_index: int,
    ) -> None:
        await self._pool.execute(
            """
            DELETE FROM notification_mark_read_toggles
            WHERE user_id = ?
              AND website_key = ?
              AND url_name = ?
              AND chapter_index = ?
            """,
            (user_id, website_key, url_name, chapter_index),
        )
