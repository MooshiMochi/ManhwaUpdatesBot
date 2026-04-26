"""Parser for the dev cog's ``sql`` command.

Mirrors v1's ``--args`` syntax: ``SELECT * FROM t WHERE x=? --args=value1, value2``.
"""

from __future__ import annotations

import re

_ARGS_SPLIT = re.compile(r"--args\s*=?\s*", re.IGNORECASE)


def parse(text: str) -> tuple[str, list[str]]:
    """Split a raw ``sql`` argument into ``(query, args)``."""
    parts = _ARGS_SPLIT.split(text, maxsplit=1)
    query = parts[0].strip()
    if query.startswith('"') and query.endswith('"') and len(query) >= 2:
        query = query[1:-1]
    args: list[str] = []
    if len(parts) == 2 and parts[1].strip():
        args = [a.strip() for a in parts[1].split(",") if a.strip()]
    return query, args
