"""Unit tests for time parsing and formatting utility functions."""

from __future__ import annotations

import pytest

from clipforge.core.errors import UsageError
from clipforge.utils.timeutil import (
    format_duration_short,
    format_microseconds,
    parse_time_to_microseconds,
)


def test_parse_microseconds_numeric() -> None:
    assert parse_time_to_microseconds(10) == 10_000_000
    assert parse_time_to_microseconds(1.5) == 1_500_000


def test_parse_microseconds_strings() -> None:
    assert parse_time_to_microseconds("10") == 10_000_000
    assert parse_time_to_microseconds("10s") == 10_000_000
    assert parse_time_to_microseconds("1.5s") == 1_500_000
    assert parse_time_to_microseconds("01:30") == 90_000_000
    assert parse_time_to_microseconds("00:01:30") == 90_000_000
    assert parse_time_to_microseconds("01:00:00") == 3_600_000_000
    assert parse_time_to_microseconds("00:00:01.500") == 1_500_000


def test_parse_microseconds_invalid_format() -> None:
    with pytest.raises(UsageError):
        parse_time_to_microseconds("invalid_time")
    with pytest.raises(UsageError):
        parse_time_to_microseconds("10:20:30:40")


def test_format_microseconds() -> None:
    assert format_microseconds(0) == "00:00:00.000000"
    assert format_microseconds(10_000_000) == "00:00:10.000000"
    assert format_microseconds(3_661_500_000) == "01:01:01.500000"


def test_format_duration_short() -> None:
    assert format_duration_short(500_000) == "0.50 s"
    assert format_duration_short(10_000_000) == "10.00 s"
    assert format_duration_short(65_000_000) == "1m 5.0s"
    assert format_duration_short(3_665_000_000) == "1h 1m 5s"
