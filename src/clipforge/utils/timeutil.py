"""Time and microsecond utilities (RULE-23, FR-SPL-03, FR-INP-08)."""

from __future__ import annotations

import re

from clipforge.core.errors import UsageError

_TIMECODE_PATTERN = re.compile(
    r"^(?:(?:(?P<hours>\d+):)?(?P<minutes>[0-5]?\d):)?(?P<seconds>[0-5]?\d(?:\.\d+)?)$"
)


def parse_time_to_microseconds(value: str | int | float) -> int:
    """Parse time specification into integer microseconds.

    Supports:
        - int / float seconds: 10 -> 10_000_000, 0.5 -> 500_000
        - string formats: "HH:MM:SS", "HH:MM:SS.ffffff", "MM:SS.ffffff", "SS.ffffff"
    """
    if isinstance(value, (int, float)):
        if value < 0:
            raise UsageError(
                what=f"invalid negative time: {value}",
                meaning="timestamps cannot be negative",
                fix="provide a non-negative timestamp",
            )
        return round(value * 1_000_000)

    val_str = str(value).strip()
    if val_str.lower().endswith("s") and not val_str.lower().endswith("ms"):
        val_str = val_str[:-1].strip()

    match = _TIMECODE_PATTERN.match(val_str)
    if not match:
        # Try raw float/int string
        try:
            seconds_float = float(val_str)
            if seconds_float < 0:
                raise UsageError(
                    what=f"invalid negative time: {val_str}",
                    meaning="timestamps cannot be negative",
                    fix="provide a non-negative timestamp",
                )
            return round(seconds_float * 1_000_000)
        except ValueError:
            raise UsageError(
                what=f"invalid time format: '{val_str}'",
                meaning="expected seconds or HH:MM:SS format",
                fix="use a format like '00:01:30' or '90' or '90.5'",
            ) from None

    parts = match.groupdict()
    hours = int(parts["hours"] or 0)
    minutes = int(parts["minutes"] or 0)
    seconds = float(parts["seconds"])

    total_seconds = hours * 3600 + minutes * 60 + seconds
    return round(total_seconds * 1_000_000)


def format_microseconds(us: int) -> str:
    """Format integer microseconds as HH:MM:SS.ffffff string."""
    sign = "-" if us < 0 else ""
    abs_us = abs(us)
    total_seconds, remainder_us = divmod(abs_us, 1_000_000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}.{remainder_us:06d}"


def format_duration_short(us: int) -> str:
    """Format duration in microseconds to a concise human-readable string."""
    seconds = us / 1_000_000
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes, remainder_seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remainder_seconds:.1f}s"
    hours, remainder_minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(remainder_minutes)}m {remainder_seconds:.0f}s"
