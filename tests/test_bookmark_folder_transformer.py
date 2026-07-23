"""The bookmark ``folder`` option tolerates legacy / stale choice values.

Regression test for the ``TransformerError: Failed to convert reading to Choice``
crash in ``/bookmark new``. Discord clients that still hold the pre-migration
(v1) command definition send *lowercase* folder values (``"reading"`` etc.,
which were ``BookmarkFolderType``'s enum values), while v2 registers
capitalized choice values (``"Reading"``). A plain ``Choice[str]`` param does an
exact, case-sensitive match and raises; the custom transformer normalizes
instead.
"""

from __future__ import annotations

import asyncio

from manhwa_bot.cogs.bookmarks import _FolderTransformer
from manhwa_bot.ui.components.bookmark import BOOKMARK_FOLDERS


def _transform(value: str):
    return asyncio.run(_FolderTransformer().transform(None, value))  # type: ignore[arg-type]


def test_legacy_lowercase_values_normalize_to_canonical_folders() -> None:
    # These are exactly the lowercase values v1's BookmarkFolderType enum
    # registered as choice values.
    cases = {
        "reading": "Reading",
        "subscribed": "Subscribed",
        "planned": "Planned",
        "finished": "Finished",
        "dropped": "Dropped",
    }
    for legacy, expected in cases.items():
        assert _transform(legacy) == expected


def test_current_capitalized_values_pass_through_unchanged() -> None:
    for folder in BOOKMARK_FOLDERS:
        assert _transform(folder) == folder


def test_mixed_case_is_tolerated() -> None:
    assert _transform("ReAdInG") == "Reading"


def test_unknown_or_dropped_folder_returns_none_instead_of_crashing() -> None:
    # v1's "all" folder was dropped in v2; a stale client can still send it.
    assert _transform("all") is None
    assert _transform("on hold") is None


def test_choices_expose_every_current_folder() -> None:
    choices = _FolderTransformer().choices
    assert choices is not None
    assert [c.value for c in choices] == list(BOOKMARK_FOLDERS)
    assert [c.name for c in choices] == list(BOOKMARK_FOLDERS)
