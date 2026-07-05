"""Unit tests for encoding profiles and VP9 parameters (FR-ENC-02, FR-ENC-03)."""

from __future__ import annotations

import pytest

from clipforge.encoding.profiles import (
    calculate_keyframe_interval,
    calculate_lag_in_frames,
    calculate_tile_columns,
    get_profile,
)


def test_profile_settings() -> None:
    fast = get_profile("fast")
    assert fast.cpu_used == 4
    assert fast.passes == 1
    assert fast.deadline == "good"

    balanced = get_profile("balanced")
    assert balanced.cpu_used == 2
    assert balanced.passes == 1
    assert balanced.deadline == "good"

    best = get_profile("best")
    assert best.cpu_used == 1
    assert best.passes == 2
    assert best.deadline == "good"


def test_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match="Unknown profile"):
        get_profile("invalid_profile")  # type: ignore[arg-type]


def test_calculate_tile_columns() -> None:
    # 720p and below
    assert calculate_tile_columns(1279) == 1
    assert calculate_tile_columns(640) == 1

    # 1080p, 1440p
    assert calculate_tile_columns(1280) == 2
    assert calculate_tile_columns(1920) == 2
    assert calculate_tile_columns(2560) == 2

    # 4K and above
    assert calculate_tile_columns(3840) == 3
    assert calculate_tile_columns(4096) == 3


def test_calculate_lag_in_frames() -> None:
    # Standard resolutions
    assert calculate_lag_in_frames(1920, 1080) == 25
    assert calculate_lag_in_frames(1280, 720) == 25

    # 4K resolutions (reduced to save RAM)
    assert calculate_lag_in_frames(3840, 2160) == 16
    assert calculate_lag_in_frames(4096, 2160) == 16


def test_calculate_keyframe_interval() -> None:
    # 10s at 30 fps = 300 frames (no interior keyframes)
    assert calculate_keyframe_interval(10.0, 30.0) == 300
    # 10s at 60 fps = 600 frames
    assert calculate_keyframe_interval(10.0, 60.0) == 600
    # 5.5s at 24 fps = 132 frames
    assert calculate_keyframe_interval(5.5, 24.0) == 132
