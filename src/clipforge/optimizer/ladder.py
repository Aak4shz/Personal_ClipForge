"""Degradation ladder for oversized clips (FR-OPT-12, RULE-29, RULE-50).

When an encode exhausts its standard size retries and remains oversize, the
degradation ladder offers policy-controlled fallbacks behind `--on-oversize`:
1. FPS halving (only on sources of 48 fps or more)
2. Downscale one standard height step (2160 -> 1440 -> 1080 -> 720 -> 480, aspect kept)
"""

from __future__ import annotations

from dataclasses import dataclass

from clipforge.core.config import OversizePolicy

STANDARD_HEIGHT_STEPS: tuple[int, ...] = (2160, 1440, 1080, 720, 480)
MIN_FPS_FOR_HALVING: float = 48.0


@dataclass(frozen=True)
class DegradationState:
    """Tracks degradation steps applied to a clip."""

    fps_halved: bool = False
    downscaled: bool = False
    target_width: int | None = None
    target_height: int | None = None
    target_fps: float | None = None
    steps_applied: tuple[str, ...] = ()


def can_halve_fps(source_fps: float) -> bool:
    """Return True if the source framerate is 48 fps or higher (FR-OPT-12)."""
    return source_fps >= MIN_FPS_FOR_HALVING


def get_next_height_step(current_height: int) -> int | None:
    """Return the next standard step down from current_height, or None if at/below minimum.

    Steps: 2160 -> 1440 -> 1080 -> 720 -> 480.
    """
    for step in STANDARD_HEIGHT_STEPS:
        if current_height > step:
            return step
    return None


def calculate_downscaled_dimensions(
    source_width: int,
    source_height: int,
    target_height: int,
) -> tuple[int, int]:
    """Calculate target width preserving aspect ratio, rounded to even integers.

    Args:
        source_width: Original video width.
        source_height: Original video height.
        target_height: Downscaled height step.

    Returns:
        (target_width, target_height) where both dimensions are even.
    """
    if source_height <= 0:
        return (source_width, target_height)

    aspect = source_width / source_height
    # Round to nearest even integer for YUV420p codec compatibility
    target_width = max(2, int(round((target_height * aspect) / 2.0) * 2))
    even_target_height = max(2, int(round(target_height / 2.0) * 2))
    return (target_width, even_target_height)


def next_degradation_step(
    current_state: DegradationState,
    policy: OversizePolicy,
    source_width: int,
    source_height: int,
    source_fps: float,
) -> DegradationState | None:
    """Determine and return the next degradation state, or None if exhausted or disallowed.

    Policy rules:
    - 'fail': no degradation permitted.
    - 'fps': only FPS halving (sources >= 48 fps).
    - 'downscale': only one-step downscale.
    - 'both': FPS halving first (if >= 48 fps), followed by downscale.

    Args:
        current_state: Currently applied degradation state.
        policy: Configured `--on-oversize` policy.
        source_width: Source video width in pixels.
        source_height: Source video height in pixels.
        source_fps: Source average frames per second.

    Returns:
        New DegradationState if a step is applicable, else None.
    """
    if policy == "fail":
        return None

    # Step 1: FPS halving (policy 'fps' or 'both')
    if policy in ("fps", "both") and not current_state.fps_halved:
        if can_halve_fps(source_fps):
            half_fps = source_fps / 2.0
            step_name = f"fps_{half_fps:.1f}"
            return DegradationState(
                fps_halved=True,
                downscaled=current_state.downscaled,
                target_width=current_state.target_width,
                target_height=current_state.target_height,
                target_fps=half_fps,
                steps_applied=(*current_state.steps_applied, step_name),
            )
        # If policy is 'fps' only and fps < 48, cannot degrade further
        if policy == "fps":
            return None

    # Step 2: Downscaling (policy 'downscale' or 'both')
    if policy in ("downscale", "both") and not current_state.downscaled:
        curr_h = current_state.target_height if current_state.target_height else source_height
        curr_w = current_state.target_width if current_state.target_width else source_width
        next_h = get_next_height_step(curr_h)
        if next_h is not None:
            new_w, new_h = calculate_downscaled_dimensions(curr_w, curr_h, next_h)
            step_name = f"downscale_{new_h}p"
            return DegradationState(
                fps_halved=current_state.fps_halved,
                downscaled=True,
                target_width=new_w,
                target_height=new_h,
                target_fps=current_state.target_fps,
                steps_applied=(*current_state.steps_applied, step_name),
            )

    return None
