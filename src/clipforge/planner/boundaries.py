"""Boundary calculation in integer microseconds (RULE-23, FR-SPL-03, RULE-29)."""

from __future__ import annotations

from dataclasses import dataclass

from clipforge.core.config import TailPolicy
from clipforge.planner.tail import decide_tail


@dataclass(frozen=True)
class ClipBoundary:
    """One clip's boundary in integer microseconds (RULE-23).

    Interval is half-open: [start_us, end_us).
    """

    index: int
    start_us: int
    end_us: int

    @property
    def duration_us(self) -> int:
        return self.end_us - self.start_us

    @property
    def start_seconds(self) -> float:
        return self.start_us / 1_000_000

    @property
    def end_seconds(self) -> float:
        return self.end_us / 1_000_000

    @property
    def duration_seconds(self) -> float:
        return self.duration_us / 1_000_000


def calculate_boundaries(
    duration_us: int,
    clip_duration_us: int = 10_000_000,
    source_start_us: int = 0,
    tail_policy: TailPolicy = "merge_into_previous",
    min_tail_us: int = 1_000_000,
) -> list[ClipBoundary]:
    """Calculate half-open [start_us, end_us) boundaries in integer microseconds.

    Args:
        duration_us: Total duration to split, in microseconds.
        clip_duration_us: Target duration of each clip (default 10 s = 10,000,000 µs).
        source_start_us: Offset added to all boundaries (default 0).
        tail_policy: 'keep', 'merge_into_previous', or 'drop'.
        min_tail_us: Threshold below which a tail is considered an orphan.

    Returns:
        List of ClipBoundary instances.

    Raises:
        ValueError: If duration_us <= 0, clip_duration_us <= 0, or source_start_us < 0.
    """
    if duration_us <= 0:
        raise ValueError(f"duration_us must be positive, got {duration_us}")
    if clip_duration_us <= 0:
        raise ValueError(f"clip_duration_us must be positive, got {clip_duration_us}")
    if source_start_us < 0:
        raise ValueError(f"source_start_us must be non-negative, got {source_start_us}")

    full_count = duration_us // clip_duration_us
    tail_us = duration_us % clip_duration_us

    if full_count == 0:
        # Video is shorter than a single clip duration
        return [
            ClipBoundary(
                index=0,
                start_us=source_start_us,
                end_us=source_start_us + duration_us,
            )
        ]

    clips: list[ClipBoundary] = []
    for i in range(full_count):
        c_start = source_start_us + i * clip_duration_us
        c_end = c_start + clip_duration_us
        clips.append(ClipBoundary(index=i, start_us=c_start, end_us=c_end))

    decision, extra_us = decide_tail(
        tail_us=tail_us,
        min_tail_us=min_tail_us,
        policy=tail_policy,
        has_previous_clip=True,
    )

    if decision == "merged":
        last = clips[-1]
        clips[-1] = ClipBoundary(
            index=last.index,
            start_us=last.start_us,
            end_us=last.end_us + extra_us,
        )
    elif decision == "kept":
        tail_start = source_start_us + full_count * clip_duration_us
        clips.append(
            ClipBoundary(
                index=full_count,
                start_us=tail_start,
                end_us=tail_start + tail_us,
            )
        )

    # Verify half-open integrity
    for j in range(len(clips) - 1):
        assert clips[j].end_us == clips[j + 1].start_us, (
            f"Boundary drift at clip {j}: {clips[j].end_us} != {clips[j + 1].start_us}"
        )

    return clips
