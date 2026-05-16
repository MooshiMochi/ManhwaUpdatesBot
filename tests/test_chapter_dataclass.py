"""Tests for the Chapter crawler dataclass."""

from __future__ import annotations

from manhwa_bot.crawler.chapter import Chapter
from manhwa_bot.ui import emojis


def test_from_dict_prefers_chapter_key() -> None:
    ch = Chapter.from_dict(
        {"chapter": "Chapter 42", "name": "ignored", "url": "https://example.test/42"},
        fallback_idx=3,
    )
    assert ch.name == "Chapter 42"
    assert ch.url == "https://example.test/42"
    assert ch.index == 3
    assert ch.is_premium is False


def test_from_dict_falls_back_through_name_and_text_and_chapter_number() -> None:
    name_only = Chapter.from_dict({"name": "Ch.5", "url": "u"})
    text_only = Chapter.from_dict({"text": "Ch.5", "url": "u"})
    num_only = Chapter.from_dict({"chapter_number": 5, "url": "u"}, fallback_idx=4)
    fallback = Chapter.from_dict({"url": ""}, fallback_idx=7)
    no_fallback = Chapter.from_dict({})

    assert name_only.name == "Ch.5"
    assert text_only.name == "Ch.5"
    assert num_only.name == "5"
    assert fallback.name == "#7"
    assert no_fallback.name == "?"


def test_from_dict_reads_url_aliases_and_premium_aliases() -> None:
    a = Chapter.from_dict({"chapter": "1", "chapter_url": "https://example.test/1"})
    assert a.url == "https://example.test/1"

    for key in ("is_premium", "premium", "is_paid", "paid", "is_locked", "locked"):
        ch = Chapter.from_dict({"chapter": "1", key: True})
        assert ch.is_premium is True, key

    assert Chapter.from_dict({"chapter": "1"}).is_premium is False


def test_from_dict_uses_explicit_index_when_present() -> None:
    ch = Chapter.from_dict({"chapter": "1", "index": 12}, fallback_idx=99)
    assert ch.index == 12


def test_str_renders_hyperlink_with_lock_when_premium() -> None:
    premium = Chapter(name="Chapter 9", url="https://example.test/9", index=0, is_premium=True)
    free = Chapter(name="Chapter 1", url="https://example.test/1", index=0, is_premium=False)
    no_url = Chapter(name="Chapter 5", url="", index=0, is_premium=False)
    no_url_premium = Chapter(name="Chapter 5", url="", index=0, is_premium=True)

    assert str(premium) == f"[Chapter 9 {emojis.LOCK}](https://example.test/9)"
    assert str(free) == "[Chapter 1](https://example.test/1)"
    assert str(no_url) == "Chapter 5"
    assert str(no_url_premium) == f"{emojis.LOCK} Chapter 5"


def test_list_from_payload_handles_chapters_key_and_alias() -> None:
    chapters_payload = {
        "chapters": [
            {"name": "Ch 1", "url": "https://example.test/1"},
            {"name": "Ch 2", "url": "https://example.test/2", "is_premium": True},
        ]
    }
    latest_payload = {
        "latest_chapters": [
            {"name": "Latest", "url": "https://example.test/latest"},
        ]
    }
    empty = {}

    chapters = Chapter.list_from_payload(chapters_payload)
    latest = Chapter.list_from_payload(latest_payload)

    assert [c.name for c in chapters] == ["Ch 1", "Ch 2"]
    assert chapters[1].is_premium is True
    assert chapters[0].index == 0 and chapters[1].index == 1
    assert [c.name for c in latest] == ["Latest"]
    assert Chapter.list_from_payload(empty) == []


def test_list_from_payload_preserves_existing_chapter_instances() -> None:
    existing = Chapter(name="Pre-wrapped", url="u", index=4, is_premium=False)
    out = Chapter.list_from_payload({"chapters": [existing, {"name": "Other"}]})
    assert out[0] is existing
    assert out[1].name == "Other"
