"""Unit tests for budget math (FR-OPT-02, FR-OPT-03, RULE-29)."""

from __future__ import annotations

import pytest

from clipforge.core.constants import TARGET_CLIP_SIZE_BYTES
from clipforge.optimizer.budget import (
    calculate_budget,
    default_audio_bitrate_bps,
)


def test_blueprint_worked_example() -> None:
    """The worked example from blueprint section 18 and Phases.md:

    10 s clip (10_000_000 µs), stereo 64 kbps, 5% safety margin on 4 MiB:
    audio = 80,000 bytes
    video = 3,123,671 bps
    target = 3,984,589 bytes
    """
    duration_us = 10_000_000
    audio_bps = 64_000
    budget = calculate_budget(duration_us, audio_bps=audio_bps)

    assert budget.target_bytes == TARGET_CLIP_SIZE_BYTES
    assert budget.target_bytes == 3_984_589
    assert budget.audio_bytes == 80_000
    assert budget.video_bps == 3_123_671
    assert budget.duration_us == duration_us
    assert round(budget.video_kbps, 1) == 3123.7
    assert budget.audio_kbps == 64.0


def test_default_audio_bitrate_bps_by_channel() -> None:
    assert default_audio_bitrate_bps(None) == 0
    assert default_audio_bitrate_bps(0) == 0
    assert default_audio_bitrate_bps(1) == 40_000
    assert default_audio_bitrate_bps(2) == 64_000
    assert default_audio_bitrate_bps(6) == 160_000
    assert default_audio_bitrate_bps(8) == 224_000


def test_audio_bytes_subtracted_first() -> None:
    duration_us = 5_000_000  # 5 seconds
    audio_bps = 64_000
    budget = calculate_budget(duration_us, audio_bps=audio_bps)

    # 64,000 bps * 5 s = 320,000 bits = 40,000 bytes
    assert budget.audio_bytes == 40_000
    remaining = TARGET_CLIP_SIZE_BYTES - 40_000
    expected_video_bps = (remaining * 8 * 1_000_000) // duration_us
    assert budget.video_bps == expected_video_bps


def test_no_audio_allocates_full_budget_to_video() -> None:
    duration_us = 10_000_000
    budget = calculate_budget(duration_us, audio_bps=0)

    assert budget.audio_bytes == 0
    expected_video_bps = (TARGET_CLIP_SIZE_BYTES * 8 * 1_000_000) // duration_us
    assert budget.video_bps == expected_video_bps


def test_invalid_duration_raises() -> None:
    with pytest.raises(ValueError, match="duration_us must be positive"):
        calculate_budget(0)
    with pytest.raises(ValueError, match="duration_us must be positive"):
        calculate_budget(-1000)


def test_excessive_audio_budget_raises() -> None:
    # 10s at 4,000,000 bps audio = 5,000,000 bytes > 3,984,589 target
    with pytest.raises(ValueError, match=r"audio budget.*exceeds clip target"):
        calculate_budget(10_000_000, audio_bps=4_000_000)
