"""Durable short-token contexts for persistent notification buttons."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from .pool import DbPool


@dataclass(frozen=True)
class NotificationActionContext:
    token: str
    website_key: str
    url_name: str
    series_url: str
    chapter_index: int
    chapter_name: str | None
    chapter_url: str | None


class NotificationActionContextStore:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    async def get(self, token: str) -> NotificationActionContext | None:
        row = await self._pool.fetchone(
            "SELECT * FROM notification_action_contexts WHERE token = ?",
            (str(token),),
        )
        if row is None:
            return None
        return NotificationActionContext(
            token=str(row["token"]),
            website_key=str(row["website_key"]),
            url_name=str(row["url_name"]),
            series_url=str(row["series_url"]),
            chapter_index=int(row["chapter_index"]),
            chapter_name=row["chapter_name"],
            chapter_url=row["chapter_url"],
        )

    async def get_or_create(
        self,
        *,
        website_key: str,
        url_name: str,
        series_url: str,
        chapter_index: int,
        chapter_name: str | None,
        chapter_url: str | None,
    ) -> NotificationActionContext:
        fields = (
            str(website_key).strip(),
            str(url_name).strip(),
            str(series_url).strip(),
            int(chapter_index),
            str(chapter_name).strip() if chapter_name else None,
            str(chapter_url).strip() if chapter_url else None,
        )
        token = _context_token(fields)
        await self._pool.execute(
            """
            INSERT INTO notification_action_contexts (
              token, website_key, url_name, series_url,
              chapter_index, chapter_name, chapter_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(token) DO NOTHING
            """,
            (token, *fields),
        )
        context = await self.get(token)
        if context is None:
            raise RuntimeError("notification action context was not persisted")
        expected = NotificationActionContext(token, *fields)
        if context != expected:
            raise RuntimeError("notification action token collision")
        return context


def _context_token(fields: tuple[object, ...]) -> str:
    payload = json.dumps(fields, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.blake2s(payload, digest_size=12).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
