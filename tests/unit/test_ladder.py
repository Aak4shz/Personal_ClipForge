"""Unit tests for the degradation ladder (Phase 7, FR-OPT-12, RULE-50)."""

from __future__ import annotations

from clipforge.optimizer.ladder import (
    MIN_FPS_FOR_HALVING,
    DegradationState,
    calculate_downscaled_dimensions,
    can_halve_fps,
    get_next_height_step,
    next_degradation_step,
)


def test_can_halve_fps() -> None:
    assert can_halve_fps(60.0) is True
    assert can_halve_fps(48.0) is True
    assert can_halve_fps(59.94) is True
    assert can_halve_fps(30.0) is False
    assert can_halve_fps(24.0) is False
    assert can_halve_fps(MIN_FPS_FOR_HALVING) is True
    assert can_halve_fps(MIN_FPS_FOR_HALVING - 0.1) is False


def test_get_next_height_step() -> None:
    # 2160 -> 1440 -> 1080 -> 720 -> 480 -> None
    assert get_next_height_step(2160) == 1440
    assert get_next_height_step(1440) == 1080
    assert get_next_height_step(1080) == 720
    assert get_next_height_step(720) == 480
    assert get_next_height_step(480) is None
    assert get_next_height_step(360) is None
    # Non-standard intermediate heights drop to the next standard step below
    assert get_next_height_step(1920) == 1440
    assert get_next_height_step(900) == 720


def test_calculate_downscaled_dimensions_aspect_and_even() -> None:
    # 16:9 standard: 1920x1080 -> 720p => 1280x720
    w, h = calculate_downscaled_dimensions(1920, 1080, 720)
    assert (w, h) == (1280, 720)
    assert w % 2 == 0 and h % 2 == 0

    # 16:9 4K: 3840x2160 -> 1440p => 2560x1440
    w, h = calculate_downscaled_dimensions(3840, 2160, 1440)
    assert (w, h) == (2560, 1440)
    assert w % 2 == 0 and h % 2 == 0

    # Odd aspect or odd dimensions are rounded to even integers
    w, h = calculate_downscaled_dimensions(1919, 1079, 720)
    assert w % 2 == 0 and h % 2 == 0

    # Vertical video (9:16): 1080x1920 -> 1080p height => 608x1080
    w, h = calculate_downscaled_dimensions(1080, 1920, 1080)
    assert w % 2 == 0 and h % 2 == 0


def test_next_degradation_step_policy_fail() -> None:
    state = DegradationState()
    # 'fail' policy never degrades
    assert next_degradation_step(state, "fail", 1920, 1080, 60.0) is None


def test_next_degradation_step_policy_fps() -> None:
    state = DegradationState()
    # 60 fps source can halve to 30 fps
    step1 = next_degradation_step(state, "fps", 1920, 1080, 60.0)
    assert step1 is not None
    assert step1.fps_halved is True
    assert step1.target_fps == 30.0
    assert step1.downscaled is False
    assert "fps_30.0" in step1.steps_applied

    # Once halved, policy 'fps' has no further steps
    step2 = next_degradation_step(step1, "fps", 1920, 1080, 60.0)
    assert step2 is None

    # Source < 48 fps cannot halve under policy 'fps'
    assert next_degradation_step(state, "fps", 1920, 1080, 30.0) is None


def test_next_degradation_step_policy_downscale() -> None:
    state = DegradationState()
    # Downscale from 1080 to 720
    step1 = next_degradation_step(state, "downscale", 1920, 1080, 60.0)
    assert step1 is not None
    assert step1.fps_halved is False
    assert step1.downscaled is True
    assert step1.target_width == 1280
    assert step1.target_height == 720
    assert "downscale_720p" in step1.steps_applied

    # Once downscaled, one-step downscale policy is exhausted
    step2 = next_degradation_step(step1, "downscale", 1920, 1080, 60.0)
    assert step2 is None


def test_next_degradation_step_policy_both() -> None:
    state = DegradationState()
    # Step 1: Halve FPS on 60 fps source
    step1 = next_degradation_step(state, "both", 1920, 1080, 60.0)
    assert step1 is not None
    assert step1.fps_halved is True
    assert step1.target_fps == 30.0
    assert step1.downscaled is False

    # Step 2: Downscale next
    step2 = next_degradation_step(step1, "both", 1920, 1080, 60.0)
    assert step2 is not None
    assert step2.fps_halved is True
    assert step2.target_fps == 30.0
    assert step2.downscaled is True
    assert step2.target_width == 1280
    assert step2.target_height == 720
    assert step2.steps_applied == ("fps_30.0", "downscale_720p")

    # Step 3: Fully exhausted
    step3 = next_degradation_step(step2, "both", 1920, 1080, 60.0)
    assert step3 is None


def test_next_degradation_step_policy_both_low_fps() -> None:
    state = DegradationState()
    # Source is 30 fps (< 48 fps), so FPS step is skipped and goes straight to downscaling
    step1 = next_degradation_step(state, "both", 1920, 1080, 30.0)
    assert step1 is not None
    assert step1.fps_halved is False
    assert step1.downscaled is True
    assert step1.target_width == 1280
    assert step1.target_height == 720

    # Exhausted
    step2 = next_degradation_step(step1, "both", 1920, 1080, 30.0)
    assert step2 is None
