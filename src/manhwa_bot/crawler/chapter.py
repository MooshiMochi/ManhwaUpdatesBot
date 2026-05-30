"""Chapter dataclass — single representation of a chapter across the bot.

Crawler responses arrive as raw dicts with several historic key aliases (``chapter``
vs ``name`` vs ``text``; ``url`` vs ``chapter_url``; ``is_premium`` vs ``premium``
vs ``is_paid`` vs ``locked``). Centralising the parsing here means downstream views
never have to reach into the dict and can just call ``str(chapter)`` to render the
canonical hyperlink (with the lock emoji on premium chapters).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Chapter:
    """A single chapter entry returned by the crawler."""

    name: str
    url: str
    index: int | None
    is_premium: bool

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        fallback_idx: int | None = None,
    ) -> Chapter:
        name = str(
            data.get("chapter")
            or data.get("name")
            or data.get("text")
            or data.get("chapter_number")
            or (f"#{fallback_idx}" if fallback_idx is not None else "?")
        )
        url = str(data.get("url") or data.get("chapter_url") or "")
        idx_raw = data.get("index")
        if isinstance(idx_raw, bool):
            index: int | None = fallback_idx
        elif isinstance(idx_raw, (int, float)):
            index = int(idx_raw)
        else:
            index = fallback_idx
        premium = bool(
            data.get("is_premium")
            or data.get("premium")
            or data.get("is_paid")
            or data.get("paid")
            or data.get("is_locked")
            or data.get("locked")
        )
        return cls(name=name, url=url, index=index, is_premium=premium)

    @classmethod
    def list_from_payload(cls, payload: Mapping[str, Any]) -> list[Chapter]:
        """Deserialise a crawler response's ``chapters``/``latest_chapters`` array."""
        raw: Any = payload.get("chapters")
        if raw is None:
            raw = payload.get("latest_chapters") or []
        result: list[Chapter] = []
        for i, item in enumerate(raw or []):
            if isinstance(item, Chapter):
                result.append(item)
            elif isinstance(item, Mapping):
                result.append(cls.from_dict(item, fallback_idx=i))
        return result

    def __str__(self) -> str:
        from ..ui import emojis

        # The premium lock emoji must sit OUTSIDE the masked link: Discord
        # breaks `[text](url)` rendering when the label contains a custom emoji,
        # spilling the raw markdown into the message. See discord-api-docs#6116.
        if self.url:
            link = f"[{self.name}]({self.url})"
            return f"{link} {emojis.LOCK}" if self.is_premium else link
        return f"{emojis.LOCK} {self.name}" if self.is_premium else self.name
