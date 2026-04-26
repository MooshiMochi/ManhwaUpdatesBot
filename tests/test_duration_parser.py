"""Tests for ``dev_helpers.duration_parser`` (re-exports ``parse_duration``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from manhwa_bot.dev_helpers.duration_parser import parse_duration

_FORMAT = "%Y-%m-%d %H:%M:%S"


def _parsed(s: str) -> datetime:
    return datetime.strptime(s, _FORMAT).replace(tzinfo=UTC)


def _approx_delta(
    actual: datetime, expected_delta: timedelta, *, tolerance_seconds: int = 5
) -> None:
    now = datetime.now(tz=UTC)
    diff = abs((actual - (now + expected_delta)).total_seconds())
    assert diff <= tolerance_seconds, f"expected ~{expected_delta}, got delta={diff:.1f}s"


def test_seven_days() -> None:
    out = parse_duration("7d")
    assert out is not None
    _approx_delta(_parsed(out), timedelta(days=7))


def test_forty_eight_hours_is_two_days() -> None:
    out = parse_duration("48h")
    assert out is not None
    _approx_delta(_parsed(out), timedelta(hours=48))


def test_one_month_is_thirty_days() -> None:
    out = parse_duration("1mo")
    assert out is not None
    _approx_delta(_parsed(out), timedelta(days=30))


def test_minutes_and_seconds() -> None:
    m_out = parse_duration("30m")
    s_out = parse_duration("45s")
    assert m_out is not None
    assert s_out is not None
    _approx_delta(_parsed(m_out), timedelta(minutes=30))
    _approx_delta(_parsed(s_out), timedelta(seconds=45))


def test_permanent() -> None:
    assert parse_duration("permanent") is None
    assert parse_duration("Permanent") is None


def test_iso_timestamp() -> None:
    out = parse_duration("2030-01-01T00:00:00")
    assert out == "2030-01-01 00:00:00"


def test_iso_with_timezone_normalised_to_utc() -> None:
    out = parse_duration("2030-01-01T05:00:00+05:00")
    assert out == "2030-01-01 00:00:00"


@pytest.mark.parametrize("bad", ["", "forever", "3y", "abc", "12"])
def test_bad_strings_raise(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(bad)
