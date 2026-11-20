"""Unit tests for boundary calculation in integer microseconds (RULE-23, FR-SPL-03, RULE-29)."""

from __future__ import annotations

import pytest

from clipforge.planner.boundaries import calculate_boundaries


def test_ten_minute_exact_sixty_clips() -> None:
    """A 10-minute (600 s) video produces exactly 60 clips of 10 seconds."""
    duration_us = 600_000_000  # 600 s
    clip_duration_us = 10_000_000  # 10 s

    boundaries = calculate_boundaries(duration_us, clip_duration_us)
    assert len(boundaries) == 60

    for i, clip in enumerate(boundaries):
        assert clip.index == i
        assert clip.start_us == i * clip_duration_us
        assert clip.end_us == (i + 1) * clip_duration_us
        assert clip.duration_us == clip_duration_us
        assert clip.duration_seconds == 10.0


def test_six_hundred_point_two_seconds_merge_tail() -> None:
    """A 600.2 s video under merge_into_previous must not plan a 0.2 s orphan clip."""
    duration_us = 600_200_000  # 600.2 s
    clip_duration_us = 10_000_000  # 10.0 s

    boundaries = calculate_boundaries(
        duration_us,
        clip_duration_us,
        tail_policy="merge_into_previous",
        min_tail_us=1_000_000,
    )
    # Must produce 60 clips, NOT 61
    assert len(boundaries) == 60

    # First 59 clips are 10.0 s
    for i in range(59):
        assert boundaries[i].duration_us == 10_000_000

    # 60th clip (index 59) has the 0.2 s merged into it: 10.2 s
    last_clip = boundaries[-1]
    assert last_clip.index == 59
    assert last_clip.start_us == 590_000_000
    assert last_clip.end_us == 600_200_000
    assert last_clip.duration_us == 10_200_000
    assert last_clip.duration_seconds == 10.2


def test_six_hundred_point_two_seconds_drop_tail() -> None:
    """A 600.2 s video under drop policy drops the 0.2 s tail."""
    duration_us = 600_200_000
    clip_duration_us = 10_000_000

    boundaries = calculate_boundaries(
        duration_us,
        clip_duration_us,
        tail_policy="drop",
        min_tail_us=1_000_000,
    )
    assert len(boundaries) == 60
    assert boundaries[-1].duration_us == 10_000_000
    assert boundaries[-1].end_us == 600_000_000


def test_six_hundred_point_two_seconds_keep_tail() -> None:
    """A 600.2 s video under keep policy keeps the 0.2 s tail as a 61st clip."""
    duration_us = 600_200_000
    clip_duration_us = 10_000_000

    boundaries = calculate_boundaries(
        duration_us,
        clip_duration_us,
        tail_policy="keep",
        min_tail_us=1_000_000,
    )
    assert len(boundaries) == 61
    assert boundaries[-1].index == 60
    assert boundaries[-1].start_us == 600_000_000
    assert boundaries[-1].end_us == 600_200_000
    assert boundaries[-1].duration_us == 200_000


def test_tail_above_threshold_is_kept_under_all_policies() -> None:
    """A 605.0 s video has a 5.0 s tail (>= 1.0 s threshold), so it is kept as clip 60."""
    duration_us = 605_000_000
    clip_duration_us = 10_000_000

    for policy in ("merge_into_previous", "keep", "drop"):
        boundaries = calculate_boundaries(
            duration_us,
            clip_duration_us,
            tail_policy=policy,
            min_tail_us=1_000_000,
        )
        assert len(boundaries) == 61
        assert boundaries[-1].duration_us == 5_000_000


def test_non_zero_source_start_time() -> None:
    """Boundaries hold across a non-zero source start time offset."""
    source_start_us = 120_500_000  # Starts at 120.5 seconds
    duration_us = 25_000_000  # 25 seconds
    clip_duration_us = 10_000_000

    boundaries = calculate_boundaries(
        duration_us=duration_us,
        clip_duration_us=clip_duration_us,
        source_start_us=source_start_us,
        tail_policy="merge_into_previous",
    )
    # 25s = 10s + 15s (10s + 5s tail >= 1s threshold -> kept as 3rd clip)
    assert len(boundaries) == 3
    assert boundaries[0].start_us == 120_500_000
    assert boundaries[0].end_us == 130_500_000

    assert boundaries[1].start_us == 130_500_000
    assert boundaries[1].end_us == 140_500_000

    assert boundaries[2].start_us == 140_500_000
    assert boundaries[2].end_us == 145_500_000


def test_short_video_smaller_than_clip_duration() -> None:
    """A video shorter than clip duration produces a single clip of its exact duration."""
    duration_us = 4_500_000  # 4.5 s
    boundaries = calculate_boundaries(duration_us, clip_duration_us=10_000_000)
    assert len(boundaries) == 1
    assert boundaries[0].start_us == 0
    assert boundaries[0].end_us == 4_500_000
    assert boundaries[0].duration_us == 4_500_000


def test_boundary_continuity_no_drift() -> None:
    """Half-open intervals [start, end) must be strictly contiguous."""
    boundaries = calculate_boundaries(
        duration_us=123_456_789,
        clip_duration_us=10_000_000,
        source_start_us=50_000_000,
        tail_policy="merge_into_previous",
    )
    for i in range(len(boundaries) - 1):
        assert boundaries[i].end_us == boundaries[i + 1].start_us


def test_invalid_arguments_raise() -> None:
    with pytest.raises(ValueError, match="duration_us must be positive"):
        calculate_boundaries(0)
    with pytest.raises(ValueError, match="clip_duration_us must be positive"):
        calculate_boundaries(10_000_000, clip_duration_us=0)
    with pytest.raises(ValueError, match="source_start_us must be non-negative"):
        calculate_boundaries(10_000_000, source_start_us=-1)
